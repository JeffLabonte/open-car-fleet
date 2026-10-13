from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from shop.models.garage import Garage, GarageInvitation


def expire_stale_pending_invitations(garage: Garage) -> int:
    """Mark pending invitations whose expiration has passed as expired."""
    now = timezone.now()
    expired_ids = list(
        garage.invitations.filter(
            status=GarageInvitation.STATUS_PENDING,
            expires_at__lte=now,
        ).values_list('id', flat=True)
    )
    if expired_ids:
        GarageInvitation.objects.filter(id__in=expired_ids).update(
            status=GarageInvitation.STATUS_EXPIRED
        )
    return len(expired_ids)


@dataclass(slots=True)
class GarageInvitationResult:
    invitation: GarageInvitation
    created: bool
    updated: bool
    email_sent: bool
    accept_url: str


def create_or_update_garage_invitation(
    garage: Garage,
    *,
    invited_email: str,
    role: str,
    message: str,
    invited_by: Any,
    expires_in_days: int,
) -> tuple[GarageInvitation, bool, bool]:
    """Create a new pending invitation or update an existing one.

    Returns ``(invitation, created, updated)``.
    """
    existing_pending = garage.invitations.filter(
        invited_email__iexact=invited_email,
        status=GarageInvitation.STATUS_PENDING,
    ).first()
    if existing_pending:
        existing_pending.role = role
        existing_pending.expires_at = timezone.now() + timedelta(days=expires_in_days)
        existing_pending.save(update_fields=['role', 'expires_at', 'updated_at'])
        return existing_pending, False, True

    invitation = GarageInvitation.objects.create(
        garage=garage,
        invited_email=invited_email,
        invited_by=invited_by,
        message=message,
        role=role,
        expires_at=timezone.now() + timedelta(days=expires_in_days),
    )
    return invitation, True, False


def build_invitation_accept_url(request: Any, invitation: GarageInvitation) -> str:
    """Return the absolute URL a recipient uses to accept the invitation."""
    return request.build_absolute_uri(
        reverse('shop-garage-invitation-accept', args=[invitation.token])
    )


def send_garage_invitation_email(
    invitation: GarageInvitation,
    accept_base_url: str,
) -> int:
    """Send the invitation email and return the number of messages sent."""
    return invitation.send_invitation_email(
        accept_base_url=accept_base_url,
        sender_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
    )


def invite_to_garage(
    request: Any,
    garage: Garage,
    *,
    invited_email: str,
    role: str,
    message: str,
    invited_by: Any,
    expires_in_days: int,
) -> GarageInvitationResult:
    """Create or update an invitation and send its notification email."""
    expire_stale_pending_invitations(garage)
    invitation, created, updated = create_or_update_garage_invitation(
        garage,
        invited_email=invited_email,
        role=role,
        message=message,
        invited_by=invited_by,
        expires_in_days=expires_in_days,
    )
    accept_url = build_invitation_accept_url(request, invitation)
    base_url = accept_url.rsplit('/', 2)[0]
    try:
        send_garage_invitation_email(invitation, base_url)
        email_sent = True
    except Exception:
        email_sent = False
    return GarageInvitationResult(
        invitation=invitation,
        created=created,
        updated=updated,
        email_sent=email_sent,
        accept_url=accept_url,
    )
