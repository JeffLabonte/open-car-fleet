from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from shop.models.garage import KnownShop


class LineListFieldMixin:
    def _clean_line_list_field(self, field_name: str) -> list[str]:
        raw = self.cleaned_data.get(field_name, '')
        return [item.strip() for item in raw.splitlines() if item.strip()]


class AssignedToShopFormMixin:
    def configure_assigned_fields(self) -> None:
        self.fields['assigned_to'].queryset = get_user_model().objects.filter(is_mechanic=True)
        self.fields['assigned_to'].help_text = _('Only users converted to mechanics can be selected.')
        self.fields['assigned_shop'].queryset = KnownShop.objects.order_by('name')
        self.fields['assigned_shop'].help_text = _('Assign to a known shop instead of a mechanic user.')

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        if cleaned_data.get('assigned_to') and cleaned_data.get('assigned_shop'):
            raise ValidationError(_('Assign either a mechanic user or a known shop, not both.'))
        return cleaned_data
