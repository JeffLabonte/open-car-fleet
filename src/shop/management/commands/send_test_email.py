from typing import Any

from anymail.exceptions import AnymailError
from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a test email through the configured email backend to verify dispatch."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--to", required=True, help="Recipient email address.")
        parser.add_argument(
            "--from",
            dest="from_email",
            default=None,
            help="From address (defaults to settings.DEFAULT_FROM_EMAIL).",
        )
        parser.add_argument(
            "--backend",
            default=None,
            help="Email backend path to use (defaults to settings.EMAIL_BACKEND).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        recipient = options["to"].strip()
        if not recipient:
            raise CommandError("Recipient email cannot be empty.")

        backend_path = options["backend"]
        from_email = options["from_email"] or getattr(settings, "DEFAULT_FROM_EMAIL", "webmaster@localhost")

        message = EmailMessage(
            subject="Open Car Fleet test email",
            body=(
                "This is a test message sent by the send_test_email command.\n"
                f"Backend: {backend_path or getattr(settings, 'EMAIL_BACKEND', '<django default>')}\n"
            ),
            from_email=from_email,
            to=[recipient],
            connection=get_connection(backend=backend_path, fail_silently=False),
        )

        try:
            sent = message.send()
        except AnymailError as exc:
            raise CommandError(f"Email dispatch failed via Anymail: {exc}") from exc
        except Exception as exc:
            raise CommandError(f"Email dispatch failed: {exc}") from exc

        if not sent:
            raise CommandError("No messages were sent.")

        self.stdout.write(self.style.SUCCESS(f"Sent test email to {recipient}."))
        anymail_status = getattr(message, "anymail_status", None)
        if anymail_status is not None:
            self.stdout.write(f"anymail_status: {anymail_status.status}")
            message_id = anymail_status.message_id
            if message_id:
                self.stdout.write(f"message_id: {message_id}")
