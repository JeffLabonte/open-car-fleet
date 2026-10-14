import datetime
import gzip
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Restore the database and media from snapshots. "
        "This command self-orchestrates via docker compose, so it must be run "
        "inside a container that has the Docker socket and backup directories "
        "mounted (typically as root)."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--db-snapshot",
            required=True,
            help="Path to the gzipped SQL dump to restore (inside the container).",
        )
        parser.add_argument(
            "--media-snapshot",
            required=True,
            help="Path to the media tarball to restore (inside the container).",
        )
        parser.add_argument(
            "--compose-file",
            default="/opt/open-car-fleet/docker-compose.prod.yml",
            help="Path to the Docker Compose file on the Docker host.",
        )
        parser.add_argument(
            "--db-backup-dir",
            default="/opt/backups/database",
            help="Directory for pre-restore DB safety backups.",
        )
        parser.add_argument(
            "--media-backup-dir",
            default="/opt/backups/media",
            help="Directory for pre-restore media safety backups.",
        )
        parser.add_argument(
            "--noinput",
            action="store_true",
            help="Skip interactive confirmation.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        self.db_snapshot = Path(options["db_snapshot"])
        self.media_snapshot = Path(options["media_snapshot"])
        self.compose_file = Path(options["compose_file"])
        self.db_backup_dir = Path(options["db_backup_dir"])
        self.media_backup_dir = Path(options["media_backup_dir"])
        self.noinput = options["noinput"]
        self.dry_run = options["dry_run"]
        self.timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

        self._validate_environment()

        if self.dry_run:
            self.stdout.write(self.style.WARNING("Dry run complete. No changes made."))
            return

        self._confirm()

        self._stop_web()
        self._safety_backup()
        self._reset_db()
        self._restore_db()
        self._reconcile_schema()
        self._migrate()
        self._start_web()
        self._restore_media()
        self._verify()

        self.stdout.write(
            self.style.SUCCESS(
                "Restore complete. Safety backups (if any) are in:\n"
                f"  {self.db_backup_dir}/snapshot-pre-restore-{self.timestamp}.sql.gz\n"
                f"  {self.media_backup_dir}/snapshot-pre-restore-{self.timestamp}.tar.gz"
            )
        )

    def _validate_environment(self) -> None:
        """Ensure the command is running in a usable restore environment."""
        if os.geteuid() != 0:
            raise CommandError(
                "This command must be run as root so it can access the Docker socket "
                "and backup directories. Use --user root when starting the container."
            )

        if not Path("/var/run/docker.sock").exists():
            raise CommandError(
                "Docker socket not found at /var/run/docker.sock. "
                "Mount it with -v /var/run/docker.sock:/var/run/docker.sock"
            )

        if not self._run(["docker", "compose", "version"], capture=True).returncode == 0:
            raise CommandError(
                "docker compose is not available inside this container. "
                "Ensure the web image includes the Docker CLI and Compose plugin."
            )

        for snapshot in (self.db_snapshot, self.media_snapshot):
            if not snapshot.exists():
                raise CommandError(f"Snapshot not found: {snapshot}")

        self.db_backup_dir.mkdir(parents=True, exist_ok=True)
        self.media_backup_dir.mkdir(parents=True, exist_ok=True)

        # Derive Postgres credentials from the container environment.
        # Docker Compose injects these from the env_file at runtime.
        self.postgres_user = os.environ.get("POSTGRES_USER", "open_garage_user")
        self.postgres_db = os.environ.get("POSTGRES_DB", "open_garage")

    def _confirm(self) -> None:
        if self.noinput:
            return
        self.stdout.write(
            self.style.WARNING(
                "This will DESTROY the current database and media volume, "
                "then restore from:\n"
                f"  DB:    {self.db_snapshot}\n"
                f"  Media: {self.media_snapshot}\n"
                "A safety backup of the current state will be created first."
            )
        )
        answer = input("Type 'restore' to continue: ")
        if answer.strip().lower() != "restore":
            raise CommandError("Restore aborted by user.")

    def _stop_web(self) -> None:
        self._step("Stopping web container")
        self._compose(["stop", "web"], check=False)

    def _safety_backup(self) -> None:
        self._step("Creating safety backups of current DB and media")

        db_backup_path = self.db_backup_dir / f"snapshot-pre-restore-{self.timestamp}.sql.gz"
        try:
            with gzip.open(db_backup_path, "wb") as outfile:
                result = self._compose_exec(
                    "db",
                    ["pg_dump", "-U", self.postgres_user, "-d", self.postgres_db],
                    stdout=outfile,
                    check=False,
                )
                if result.returncode != 0:
                    self.stdout.write(
                        self.style.WARNING("Current DB backup failed (DB may be empty).")
                    )
                    db_backup_path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.WARNING(f"Current DB backup failed: {exc}"))
            db_backup_path.unlink(missing_ok=True)

        media_temp_dir = self.media_backup_dir / f"media-pre-restore-{self.timestamp}"
        media_backup_path = self.media_backup_dir / f"snapshot-pre-restore-{self.timestamp}.tar.gz"
        try:
            self._compose_cp("web:/app/src/media/.", str(media_temp_dir), check=False)
            if media_temp_dir.exists():
                shutil.make_archive(
                    str(media_backup_path.with_suffix("").with_suffix("")),
                    "gztar",
                    root_dir=media_temp_dir,
                )
                shutil.rmtree(media_temp_dir)
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.WARNING(f"Current media backup failed: {exc}"))
            shutil.rmtree(media_temp_dir, ignore_errors=True)
            media_backup_path.unlink(missing_ok=True)

    def _reset_db(self) -> None:
        self._step("Resetting Postgres volume")
        self._compose(["down", "-v", "--remove-orphans"])
        self._compose(["up", "-d", "db"])
        self._wait_for_db()

    def _wait_for_db(self) -> None:
        self.stdout.write("Waiting for Postgres to be ready...")
        for attempt in range(1, 61):
            result = self._compose_exec(
                "db",
                ["pg_isready", "-U", self.postgres_user, "-d", self.postgres_db],
                check=False,
                capture=True,
            )
            if result.returncode == 0:
                self.stdout.write(self.style.SUCCESS("Postgres is ready."))
                return
            if attempt == 60:
                self._compose(["ps"])
                raise CommandError("Postgres did not become ready in time.")
            time.sleep(2)

    def _restore_db(self) -> None:
        self._step(f"Restoring DB snapshot: {self.db_snapshot}")
        if self.db_snapshot.suffix == ".gz" or str(self.db_snapshot).endswith(".gzip"):
            decompressor = ["zcat", str(self.db_snapshot)]
        elif self.db_snapshot.suffix == ".sql":
            decompressor = ["cat", str(self.db_snapshot)]
        else:
            raise CommandError("DB snapshot must be .sql.gz, .gz, or .sql")

        decomp = subprocess.Popen(decompressor, stdout=subprocess.PIPE)
        try:
            self._compose_exec(
                "db",
                ["psql", "-U", self.postgres_user, "-d", self.postgres_db, "-v", "ON_ERROR_STOP=1"],
                stdin=decomp.stdout,
            )
        finally:
            decomp.wait()

    def _reconcile_schema(self) -> None:
        self._step("Reconciling migration history")
        result = self._compose_exec(
            "db",
            [
                "psql",
                "-U",
                self.postgres_user,
                "-d",
                self.postgres_db,
                "-tAc",
                "SELECT 1 FROM information_schema.columns WHERE table_name='shop_attachment' AND column_name='size_bytes'",
            ],
            capture=True,
            check=False,
        )
        if result.stdout.decode().strip() == "1":
            self.stdout.write("  Found legacy size_bytes column; cleaning up...")
            sql = (
                "BEGIN; "
                "DELETE FROM django_migrations WHERE app = 'shop' AND name = '0018_attachment_size_bytes'; "
                "ALTER TABLE shop_attachment DROP COLUMN IF EXISTS size_bytes; "
                "COMMIT;"
            )
            self._compose_exec(
                "db",
                [
                    "psql",
                    "-U",
                    self.postgres_user,
                    "-d",
                    self.postgres_db,
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-c",
                    sql,
                ],
            )
        else:
            self.stdout.write("  No legacy size_bytes column found; nothing to reconcile.")

    def _migrate(self) -> None:
        self._step("Running Django migrations (garage -> fleet rename will apply here)")
        self._compose_run(["web", "python", "/app/src/manage.py", "migrate", "--noinput"])

    def _start_web(self) -> None:
        self._step("Starting web container")
        self._compose(["up", "-d", "web"])
        for attempt in range(1, 31):
            result = self._compose(["ps", "-q", "web"], capture=True, check=False)
            if result.stdout.decode().strip():
                return
            if attempt == 30:
                raise CommandError("Web container did not start.")
            time.sleep(1)

    def _restore_media(self) -> None:
        self._step(f"Restoring media snapshot: {self.media_snapshot}")
        remote_tarball = "/tmp/media-snapshot.tar.gz"
        self._compose_cp(str(self.media_snapshot), f"web:{remote_tarball}", direction="to")
        self._compose_exec("web", ["tar", "xzf", remote_tarball, "-C", "/app/src/media"], user="root")
        self._compose_exec("web", ["chown", "-R", "django:django", "/app/src/media"], user="root")
        self._compose_exec("web", ["rm", "-f", remote_tarball], user="root")
        self._compose(["up", "-d", "--build", "web"])

    def _verify(self) -> None:
        self._step("Running verification")
        self._compose(["ps"])
        self._compose_run(
            ["web", "python", "/app/src/manage.py", "showmigrations", "--list", "shop", "car_docs"],
            check=False,
        )
        self._compose_exec(
            "db",
            [
                "psql",
                "-U",
                self.postgres_user,
                "-d",
                self.postgres_db,
                "-c",
                (
                    "SELECT 'fleets' AS entity, COUNT(*) AS n FROM fleet "
                    "UNION ALL SELECT 'cars', COUNT(*) FROM shop_car "
                    "UNION ALL SELECT 'users', COUNT(*) FROM shop_user "
                    "UNION ALL SELECT 'attachments', COUNT(*) FROM shop_attachment;"
                ),
            ],
            check=False,
        )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _step(self, message: str) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.NOTICE(f"[ {message} ]"))

    def _run(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        self.stdout.write(f"$ {' '.join(cmd)}")
        if "capture" in kwargs:
            kwargs["capture_output"] = kwargs.pop("capture")
        return subprocess.run(cmd, **kwargs)

    def _compose(self, args: list[str], *, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
        cmd = ["docker", "compose", "-f", str(self.compose_file)] + args
        kwargs = {"check": check}
        if capture:
            kwargs["capture_output"] = True
        return self._run(cmd, **kwargs)

    def _compose_exec(
        self,
        service: str,
        command: list[str],
        *,
        user: str | None = None,
        stdin: Any = None,
        stdout: Any = None,
        capture: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        cmd = ["docker", "compose", "-f", str(self.compose_file), "exec", "-T"]
        if user:
            cmd.extend(["--user", user])
        cmd.append(service)
        cmd.extend(command)
        kwargs: dict[str, Any] = {"check": check}
        if stdin is not None:
            kwargs["stdin"] = stdin
        if stdout is not None:
            kwargs["stdout"] = stdout
        if capture:
            kwargs["capture_output"] = True
        return self._run(cmd, **kwargs)

    def _compose_run(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
        cmd = ["docker", "compose", "-f", str(self.compose_file), "run", "--rm"] + args
        return self._run(cmd, check=check)

    def _compose_cp(
        self,
        source: str,
        destination: str,
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        """Copy files to/from a container."""
        cmd = ["docker", "compose", "-f", str(self.compose_file), "cp", source, destination]
        return self._run(cmd, check=check)
