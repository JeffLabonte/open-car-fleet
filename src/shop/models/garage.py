import uuid

from django.conf import settings
from django.core.mail import send_mail
from django.db import models
from django.utils import timezone


class Garage(models.Model):
    """A shared garage workspace that contains cars and members."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_garages",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="GarageMembership",
        related_name="garages",
    )

    class Meta:
        db_table = "garage"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class GarageMembership(models.Model):
    """Membership relation between a user and a fleet."""

    ROLE_OWNER = "owner"
    ROLE_MANAGER = "manager"
    ROLE_MEMBER = "member"

    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_MEMBER, "Member"),
    ]

    garage = models.ForeignKey(Garage, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="garage_memberships")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "garage_membership"
        unique_together = ("garage", "user")

    def __str__(self) -> str:
        return f"{self.user} in fleet {self.garage} ({self.role})"


class GarageInvitation(models.Model):
    """Invitation used to share a fleet with an email recipient."""

    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_CANCELLED = "cancelled"
    STATUS_EXPIRED = "expired"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_EXPIRED, "Expired"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    garage = models.ForeignKey(Garage, on_delete=models.CASCADE, related_name="invitations")
    invited_email = models.EmailField(db_index=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sent_garage_invitations",
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    message = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="accepted_garage_invitations",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "garage_invitation"
        indexes = [
            models.Index(fields=["invited_email"]),
            models.Index(fields=["status", "expires_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["garage", "invited_email"],
                condition=models.Q(status="pending"),
                name="uniq_pending_invitation_per_garage_email",
            ),
        ]

    def __str__(self) -> str:
        return f"Invite {self.invited_email} to fleet {self.garage}"

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and self.expires_at <= timezone.now())

    def send_invitation_email(self, accept_base_url: str, sender_email: str | None = None) -> int:
        """Send invitation email containing a tokenized acceptance URL."""
        tokenized_url = f"{accept_base_url.rstrip('/')}/{self.token}"
        subject = f"You have been invited to join the fleet '{self.garage.name}'"
        body = (
            "You have been invited to join a shared fleet. "
            "Sign in with your social account (Google, Microsoft, or GitHub) to accept the invitation.\n\n"
            f"Accept invitation: {tokenized_url}\n\n"
            f"Fleet: {self.garage.name}\n"
        )
        if self.message:
            body += f"\nMessage from inviter:\n{self.message}\n"

        return send_mail(
            subject=subject,
            message=body,
            from_email=sender_email,
            recipient_list=[self.invited_email],
            fail_silently=False,
        )


class KnownShop(models.Model):
    """Directory of known shops available for assignment."""

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


# Fleet terminology aliases that preserve current database model names.
Fleet = Garage
FleetMembership = GarageMembership
FleetInvitation = GarageInvitation
