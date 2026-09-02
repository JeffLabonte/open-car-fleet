from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from shop.forms.base import AssignedToShopFormMixin, LineListFieldMixin
from shop.models.job import WorkJob


class WorkJobForm(LineListFieldMixin, AssignedToShopFormMixin, forms.ModelForm):
    required_items = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'textarea', 'rows': 3, 'placeholder': _('One item per line')}),
        help_text=_('Add one required item per line.'),
    )

    class Meta:
        model = WorkJob
        fields = [
            'title',
            'maintenance_type',
            'assigned_to',
            'assigned_shop',
            'planned_date',
            'status',
            'is_done',
            'done_date',
            'urgency',
            'required_items',
            'notes',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'input', 'placeholder': _('Work title')}),
            'maintenance_type': forms.TextInput(attrs={'class': 'input', 'placeholder': _('Maintenance type')}),
            'assigned_to': forms.Select(attrs={'class': 'input'}),
            'assigned_shop': forms.Select(attrs={'class': 'input'}),
            'planned_date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'done_date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'input'}),
            'urgency': forms.Select(attrs={'class': 'input'}),
            'notes': forms.Textarea(attrs={'class': 'textarea', 'rows': 4, 'placeholder': _('Additional notes')}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.configure_assigned_fields()
        if self.instance and self.instance.pk:
            self.fields['required_items'].initial = '\n'.join(self.instance.required_items or [])

    def clean_required_items(self) -> list[str]:
        return self._clean_line_list_field('required_items')
