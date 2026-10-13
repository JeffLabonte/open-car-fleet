from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from shop.models.fleet import Fleet, FleetInvitation


def expire_stale_pending_invitations(fleet: Fleet) -> int:
    """Mark pending invitations whose expiration has passed as expired."""
    now = timezone.now()
    expired_ids = list(
        fleet.invitations.filter(
            status=FleetInvitation.STATUS_PENDING,
            expires_at__lte=now,
        ).values_list('id', flat=True)
    )
    if expired_ids:
        FleetInvitation.objects.filter(id__in=expired_ids).update(
            status=FleetInvitation.STATUS_EXPIRED
        )
    return len(expired_ids)


@dataclass(slots=True)
class FleetInvitationResult:
    invitation: FleetInvitation
    created: bool
    updated: bool
    email_sent: bool
    accept_url: str


def create_or_update_fleet_invitation(
    fleet: Fleet,
    *,
    invited_email: str,
    role: str,
    message: str,
    invited_by: Any,
    expires_in_days: int,
) -> tuple[FleetInvitation, bool, bool]:
    """Create a new pending invitation or update an existing one.

    Returns ``(invitation, created, updated)``.
    """
    existing_pending = fleet.invitations.filter(
        invited_email__iexact=invited_email,
        status=FleetInvitation.STATUS_PENDING,
    ).first()
    if existing_pending:
        existing_pending.role = role
        existing_pending.expires_at = timezone.now() + timedelta(days=expires_in_days)
        existing_pending.save(update_fields=['role', 'expires_at', 'updated_at'])
        return existing_pending, False, True

    invitation = FleetInvitation.objects.create(
        fleet=fleet,
        invited_email=invited_email,
        invited_by=invited_by,
        message=message,
        role=role,
        expires_at=timezone.now() + timedelta(days=expires_in_days),
    )
    return invitation, True, False


def build_invitation_accept_url(request: Any, invitation: FleetInvitation) -> str:
    """Return the absolute URL a recipient uses to accept the invitation."""
    return request.build_absolute_uri(
        reverse('shop-fleet-invitation-accept', args=[invitation.token])
    )


def send_fleet_invitation_email(
    invitation: FleetInvitation,
    accept_base_url: str,
) -> int:
    """Send the invitation email and return the number of messages sent."""
    return invitation.send_invitation_email(
        accept_base_url=accept_base_url,
        sender_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
    )


def invite_to_fleet(
    request: Any,
    fleet: Fleet,
    *,
    invited_email: str,
    role: str,
    message: str,
    invited_by: Any,
    expires_in_days: int,
) -> FleetInvitationResult:
    """Create or update an invitation and send its notification email."""
    expire_stale_pending_invitations(fleet)
    invitation, created, updated = create_or_update_fleet_invitation(
        fleet,
        invited_email=invited_email,
        role=role,
        message=message,
        invited_by=invited_by,
        expires_in_days=expires_in_days,
    )
    accept_url = build_invitation_accept_url(request, invitation)
    base_url = accept_url.rsplit('/', 2)[0]
    try:
        send_fleet_invitation_email(invitation, base_url)
        email_sent = True
    except Exception:
        email_sent = False
    return FleetInvitationResult(
        invitation=invitation,
        created=created,
        updated=updated,
        email_sent=email_sent,
        accept_url=accept_url,
    )
