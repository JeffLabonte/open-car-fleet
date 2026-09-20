from typing import Any

from django.core.management.base import BaseCommand

from shop.views import purge_stale_staged_attachments


class Command(BaseCommand):
    help = "Delete staged attachment uploads whose parent form never claimed them (12h retention)."

    def handle(self, *args: Any, **options: Any) -> None:
        purged = purge_stale_staged_attachments()
        self.stdout.write(self.style.SUCCESS(f"Purged {purged} stale staged attachment(s)."))
