from django import forms

from car_docs.models import CarDoc


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
        if uploaded_file is None:
            return uploaded_file

        if uploaded_file.content_type and uploaded_file.content_type != 'application/pdf':
            raise forms.ValidationError('Only PDF files can be uploaded for car documents.')

        if uploaded_file.name.lower().endswith('.pdf'):
            return uploaded_file

        raise forms.ValidationError('Only PDF files can be uploaded for car documents.')
