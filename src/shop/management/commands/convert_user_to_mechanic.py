from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Convert a user into a mechanic profile using the user's email address."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("email", help="Email address of the user to convert to mechanic.")
        parser.add_argument(
            "--revoke",
            action="store_true",
            help="Revoke mechanic status instead of granting it.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        email = options["email"].strip().lower()
        if not email:
            raise CommandError("Email cannot be empty.")

        user_model = get_user_model()
        user = user_model.objects.filter(email__iexact=email).first()
        if not user:
            raise CommandError(f"No user found with email '{email}'.")

        revoke = options["revoke"]
        if revoke:
            user.is_mechanic = False
            user.mechanic_promoted_at = None
            user.save(update_fields=["is_mechanic", "mechanic_promoted_at"])
            self.stdout.write(self.style.SUCCESS(f"Revoked mechanic role for {user.email or user.username}."))
            return

        user.is_mechanic = True
        if user.mechanic_promoted_at is None:
            user.mechanic_promoted_at = timezone.now()
        user.save(update_fields=["is_mechanic", "mechanic_promoted_at"])
        self.stdout.write(self.style.SUCCESS(f"User {user.email or user.username} converted to mechanic."))
