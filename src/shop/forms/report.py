from typing import Any

from django import forms

from shop.forms.base import AssignedToShopFormMixin, LineListFieldMixin
from shop.models.report import Report


class ReportForm(LineListFieldMixin, AssignedToShopFormMixin, forms.ModelForm):
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
        ]
        widgets = {
            'mileage': forms.NumberInput(attrs={'class': 'input', 'placeholder': 'Mileage at completion'}),
            'job_name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Work performed'}),
            'assigned_to': forms.Select(attrs={'class': 'input'}),
            'assigned_shop': forms.Select(attrs={'class': 'input'}),
            'date_done': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'note': forms.Textarea(attrs={'class': 'textarea', 'rows': 4, 'placeholder': 'Notes about the work done'}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.configure_assigned_fields()
        if self.instance and self.instance.pk:
            self.fields['documents'].initial = '\n'.join(self.instance.documents or [])
            self.fields['photos'].initial = '\n'.join(self.instance.photos or [])

    def clean_documents(self) -> list[str]:
        return self._clean_line_list_field('documents')

    def clean_photos(self) -> list[str]:
        return self._clean_line_list_field('photos')
