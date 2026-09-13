from typing import Any
from urllib.parse import urlparse

from django import forms
from django.utils.translation import gettext_lazy as _

from shop.forms.base import AssignedToShopFormMixin, AttachmentField, MultipleFileInput
from shop.models.report import Report


class ReportForm(AssignedToShopFormMixin, forms.ModelForm):
    attachments = AttachmentField(
        required=False,
        widget=MultipleFileInput(attrs={
            'accept': 'image/*,video/*,.pdf,.doc,.docx',
            'capture': 'environment',
        }),
        help_text=_('Upload one or more photos, videos, or documents.'),
    )
    external_links = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'textarea',
            'rows': 3,
            'placeholder': _('One external link per line (OneDrive, Google Drive, etc.)'),
        }),
        help_text=_('Add one external link per line. OneDrive and Google Drive share links work well.'),
    )

    class Meta:
        model = Report
        fields = [
            'mileage',
            'job_name',
            'assigned_to',
            'assigned_shop',
            'date_done',
            'note',
            'additional_information',
        ]
        widgets = {
            'mileage': forms.NumberInput(attrs={'class': 'input', 'placeholder': _('Mileage at completion')}),
            'job_name': forms.TextInput(attrs={'class': 'input', 'placeholder': _('Work performed')}),
            'assigned_to': forms.Select(attrs={'class': 'input'}),
            'assigned_shop': forms.Select(attrs={'class': 'input'}),
            'date_done': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'note': forms.Textarea(attrs={'class': 'textarea', 'rows': 6, 'placeholder': _('Write the maintenance report details here')}),
            'additional_information': forms.Textarea(
                attrs={'class': 'textarea', 'rows': 3, 'placeholder': _('Extra information (parts, warranty notes, follow-up, etc.)')}
            ),
        }
        labels = {
            'mileage': _('Mileage'),
            'job_name': _('Work performed'),
            'assigned_to': _('Assigned to'),
            'assigned_shop': _('Known shop'),
            'date_done': _('Date completed'),
            'note': _('Maintenance report'),
            'additional_information': _('Additional information'),
            'attachments': _('Attachments'),
            'external_links': _('External links'),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        user = kwargs.pop('user', None)
        garage = kwargs.pop('garage', None)
        super().__init__(*args, **kwargs)
        self.configure_assigned_fields(user=user, garage=garage)
        # The unified attachment mechanism renders at the bottom of the form.
        self.order_fields([
            name for name in self.fields
            if name not in ('external_links', 'attachments')
        ] + [name for name in ('external_links', 'attachments') if name in self.fields])

    def clean_external_links(self) -> list[str]:
        raw = self.cleaned_data.get('external_links', '')
        links = [item.strip() for item in raw.splitlines() if item.strip()]
        for link in links:
            parsed = urlparse(link)
            if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
                raise forms.ValidationError(_('External links must use http:// or https://.'))
        return links
