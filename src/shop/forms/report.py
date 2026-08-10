from typing import Any

from django import forms

from shop.forms.base import AssignedToShopFormMixin, LineListFieldMixin
from shop.models.report import Report


class MultipleFileInput(forms.FileInput):
    allow_multiple_selected = True

    def __init__(self, attrs: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(attrs=attrs, **kwargs)
        self.attrs['multiple'] = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data: Any, initial: Any = None) -> list[Any]:
        if not data:
            return []

        if isinstance(data, (list, tuple)):
            cleaned_files: list[Any] = []
            for item in data:
                if item:
                    cleaned_files.append(super().clean(item, initial))
            return cleaned_files

        cleaned_file = super().clean(data, initial)
        return [cleaned_file] if cleaned_file else []


class ReportForm(LineListFieldMixin, AssignedToShopFormMixin, forms.ModelForm):
    attachments = MultipleFileField(
        required=False,
        widget=MultipleFileInput(attrs={
            'accept': 'image/*,video/*,.pdf,.doc,.docx',
            'capture': 'environment',
        }),
        help_text='Upload one or more photos, videos, or documents.',
    )
    external_links = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'textarea',
            'rows': 3,
            'placeholder': 'One external link per line (OneDrive, Google Drive, etc.)',
        }),
        help_text='Add one external link per line. OneDrive and Google Drive share links work well.',
    )
    documents = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'textarea', 'rows': 3, 'placeholder': 'One document URL or path per line'}),
        help_text='Add one document URL or path per line.',
    )
    photos = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'textarea', 'rows': 3, 'placeholder': 'One photo URL or path per line'}),
        help_text='Add one photo URL or path per line.',
    )

    class Meta:
        model = Report
        fields = [
            'mileage',
            'job_name',
            'assigned_to',
            'assigned_shop',
            'date_done',
            'documents',
            'photos',
            'note',
            'additional_information',
        ]
        widgets = {
            'mileage': forms.NumberInput(attrs={'class': 'input', 'placeholder': 'Mileage at completion'}),
            'job_name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Work performed'}),
            'assigned_to': forms.Select(attrs={'class': 'input'}),
            'assigned_shop': forms.Select(attrs={'class': 'input'}),
            'date_done': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'note': forms.Textarea(attrs={'class': 'textarea', 'rows': 6, 'placeholder': 'Write the maintenance report details here'}),
            'additional_information': forms.Textarea(
                attrs={'class': 'textarea', 'rows': 3, 'placeholder': 'Extra information (parts, warranty notes, follow-up, etc.)'}
            ),
        }
        labels = {
            'note': 'Maintenance report',
            'additional_information': 'Additional information',
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.configure_assigned_fields()
        if self.instance and self.instance.pk:
            self.fields['documents'].initial = '\n'.join(self.instance.documents or [])
            self.fields['photos'].initial = '\n'.join(self.instance.photos or [])

    def clean_external_links(self) -> list[str]:
        raw = self.cleaned_data.get('external_links', '')
        return [item.strip() for item in raw.splitlines() if item.strip()]

    def clean_documents(self) -> list[str]:
        return self._clean_line_list_field('documents')

    def clean_photos(self) -> list[str]:
        return self._clean_line_list_field('photos')
