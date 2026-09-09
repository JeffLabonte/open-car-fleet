from django import forms

from shop.models.garage import KnownShop, KnownShopProof
from shop.file_validation import validate_pdf_upload


class KnownShopForm(forms.ModelForm):
    class Meta:
        model = KnownShop
        fields = ['name', 'email', 'phone', 'address', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
            'email': forms.EmailInput(attrs={'class': 'input'}),
            'phone': forms.TextInput(attrs={'class': 'input'}),
            'address': forms.TextInput(attrs={'class': 'input'}),
            'notes': forms.Textarea(attrs={'class': 'textarea', 'rows': 4}),
        }


class KnownShopProofForm(forms.ModelForm):
    class Meta:
        model = KnownShopProof
        fields = ['title', 'content', 'file']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'input'}),
            'content': forms.Textarea(attrs={'class': 'textarea', 'rows': 6}),
            'file': forms.ClearableFileInput(attrs={'class': 'input', 'accept': '.pdf,application/pdf'}),
        }

    def clean_file(self):
        uploaded_file = self.cleaned_data.get('file')
        return validate_pdf_upload(
            uploaded_file,
            message='Only valid PDF files can be uploaded as shop proofs.',
        )
