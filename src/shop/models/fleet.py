import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.core.mail import send_mail
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Fleet(models.Model):
    """A shared fleet workspace that contains cars and members."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_fleets",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="FleetMembership",
        related_name="fleets",
    )

    class Meta:
        db_table = "fleet"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class FleetMembership(models.Model):
    """Membership relation between a user and a fleet."""

    ROLE_OWNER = "owner"
    ROLE_ADMIN = "admin"
    ROLE_MECHANIC = "mechanic"
    ROLE_VIEWER = "viewer"

    # Backward-compatible aliases used by historical code/tests.
    ROLE_MANAGER = ROLE_ADMIN
    ROLE_MEMBER = ROLE_VIEWER

    ROLE_CHOICES = [
        (ROLE_OWNER, _("Owner")),
        (ROLE_ADMIN, _("Admin")),
        (ROLE_MECHANIC, _("Mechanic")),
        (ROLE_VIEWER, _("Viewer")),
    ]

    MANAGEMENT_ROLES = {ROLE_OWNER, ROLE_ADMIN}
    WRITE_DATA_ROLES = {ROLE_OWNER, ROLE_ADMIN, ROLE_MECHANIC}

    fleet = models.ForeignKey(Fleet, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="fleet_memberships")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_VIEWER)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "fleet_membership"
        unique_together = ("fleet", "user")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=['owner', 'admin', 'mechanic', 'viewer']),
                name="fleet_membership_valid_role",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} in fleet {self.fleet} ({self.role})"


class FleetInvitation(models.Model):
    """Invitation used to share a fleet with an email recipient."""

    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_DECLINED = "declined"
    STATUS_CANCELLED = "cancelled"
    STATUS_EXPIRED = "expired"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_DECLINED, "Declined"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_EXPIRED, "Expired"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fleet = models.ForeignKey(Fleet, on_delete=models.CASCADE, related_name="invitations")
    invited_email = models.EmailField(db_index=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sent_fleet_invitations",
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    role = models.CharField(
        max_length=20,
        choices=FleetMembership.ROLE_CHOICES,
        default=FleetMembership.ROLE_VIEWER,
    )
    message = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="accepted_fleet_invitations",
    )
    declined_at = models.DateTimeField(null=True, blank=True)
    declined_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="declined_fleet_invitations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "fleet_invitation"
        indexes = [
            models.Index(fields=["invited_email"]),
            models.Index(fields=["status", "expires_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["fleet", "invited_email"],
                condition=models.Q(status="pending"),
                name="uniq_pending_invitation_per_fleet_email",
            ),
        ]

    def __str__(self) -> str:
        return f"Invite {self.invited_email} to fleet {self.fleet}"

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and self.expires_at <= timezone.now())

    def send_invitation_email(self, accept_base_url: str, sender_email: str | None = None) -> int:
        """Send invitation email containing a tokenized acceptance URL."""
        tokenized_url = f"{accept_base_url.rstrip('/')}/{self.token}"
        subject = _("You have been invited to join the fleet '%(name)s'") % {'name': self.fleet.name}
        body = _(
            "You have been invited to join a shared fleet. "
            "Sign in with your social account (Google, Microsoft, or GitHub) to accept the invitation.\n\n"
            "Accept invitation: %(url)s\n\n"
            "Fleet: %(name)s\n"
        ) % {'url': tokenized_url, 'name': self.fleet.name}
        if self.message:
            body += _("\nMessage from inviter:\n%(message)s\n") % {'message': self.message}

        return send_mail(
            subject=subject,
            message=body,
            from_email=sender_email,
            recipient_list=[self.invited_email],
            fail_silently=False,
        )


class KnownShop(models.Model):
    """Directory of known shops available for assignment."""

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='created_known_shops',
    )
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True, db_index=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "known_shop"
        indexes = [models.Index(fields=["name"])]

    def __str__(self) -> str:
        return self.name


class KnownShopProof(models.Model):
    """A document or note supporting a known shop record."""

    shop = models.ForeignKey(KnownShop, on_delete=models.CASCADE, related_name='proofs')
    title = models.CharField(max_length=255)
    content = models.TextField(blank=True)
    attachments = GenericRelation('shop.Attachment')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-created_at']

    def __str__(self) -> str:
        return f"{self.title} ({self.shop})"
