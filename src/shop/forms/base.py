from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from shop.models.garage import KnownShop


class LineListFieldMixin:
    def _clean_line_list_field(self, field_name: str) -> list[str]:
        raw = self.cleaned_data.get(field_name, '')
        return [item.strip() for item in raw.splitlines() if item.strip()]


class AssignedToShopFormMixin:
    def __init__(self, *args: Any, user: Any = None, garage: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.configure_assigned_fields(user=user, garage=garage)

    def configure_assigned_fields(self, *, user: Any = None, garage: Any = None) -> None:
        mechanics = get_user_model().objects.filter(is_mechanic=True)
        if garage is not None:
            mechanics = mechanics.filter(garage_memberships__garage=garage).distinct()
        self.fields['assigned_to'].queryset = mechanics
        self.fields['assigned_to'].help_text = _('Only users converted to mechanics can be selected.')
        shops = KnownShop.objects.all()
        if user is not None:
            shops = shops.filter(Q(created_by__isnull=True) | Q(created_by=user))
        self.fields['assigned_shop'].queryset = shops.order_by('name')
        self.fields['assigned_shop'].help_text = _('Assign to a known shop instead of a mechanic user.')

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        if cleaned_data.get('assigned_to') and cleaned_data.get('assigned_shop'):
            raise ValidationError(_('Assign either a mechanic user or a known shop, not both.'))
        return cleaned_data
