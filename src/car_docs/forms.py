from django import forms

from car_docs.models import CarDoc
from shop.file_validation import validate_pdf_upload


class CarDocForm(forms.ModelForm):
    class Meta:
        model = CarDoc
        fields = ['title', 'content', 'file']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Document title'}),
            'content': forms.Textarea(attrs={'class': 'textarea', 'rows': 10, 'placeholder': 'Add notes, instructions, or summary details...'}),
            'file': forms.ClearableFileInput(attrs={'class': 'input', 'accept': '.pdf,application/pdf'}),
        }

    def clean_file(self):
        uploaded_file = self.cleaned_data.get('file')
        return validate_pdf_upload(
            uploaded_file,
            message='Only valid PDF files can be uploaded for car documents.',
        )
