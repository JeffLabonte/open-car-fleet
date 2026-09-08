import logging

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import EmailMessage

logger = logging.getLogger(__name__)


class MailgunEmailBackend(BaseEmailBackend):
    """Django email backend that sends messages through the Mailgun HTTP API."""

    def send_messages(self, email_messages: list[EmailMessage]) -> int:
        if not email_messages:
            return 0

        api_key = getattr(settings, 'MAILGUN_API_KEY', '')
        domain = getattr(settings, 'MAILGUN_SANDBOX_DOMAIN', '')
        base_url = getattr(settings, 'MAILGUN_BASE_DOMAIN', 'https://api.mailgun.net')

        if not api_key or not domain:
            if not self.fail_silently:
                raise ValueError('MAILGUN_API_KEY and MAILGUN_SANDBOX_DOMAIN must be configured to send email.')
            return 0

        sent_count = 0
        for message in email_messages:
            if not message.recipients():
                continue
            try:
                response = requests.post(
                    f"{base_url.rstrip('/')}/v3/{domain}/messages",
                    auth=('api', api_key),
                    data={
                        'from': message.from_email,
                        'to': message.to,
                        'cc': message.cc,
                        'bcc': message.bcc,
                        'subject': message.subject,
                        'text': message.body,
                    },
                    timeout=10,
                )
                response.raise_for_status()
                sent_count += 1
            except requests.RequestException:
                logger.exception('Failed to send email via Mailgun to %s', message.to)
                if not self.fail_silently:
                    raise
        return sent_count
