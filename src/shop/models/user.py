from django.contrib.auth.models import AbstractUser
from django.db import models


class ShopUser(AbstractUser):
    """Local user profile for Hanko-authenticated users and other shop users."""

    email = models.EmailField("email address", blank=True, db_index=True)

    hanko_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    display_name = models.CharField(max_length=255, blank=True)
    avatar_url = models.URLField(max_length=500, blank=True)
    auth_provider = models.CharField(max_length=50, default='local')
    last_login_at = models.DateTimeField(null=True, blank=True)
    is_mechanic = models.BooleanField(default=False)
    mechanic_promoted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'shop_user'
