from django import forms
from django.utils.translation import gettext_lazy as _

from car_docs.models import CarDoc
from shop.forms.base import AttachmentField, MultipleFileInput, StagedAttachmentsMixin


class CarDocForm(StagedAttachmentsMixin, forms.ModelForm):
    attachments = AttachmentField(
        required=False,
        widget=MultipleFileInput(attrs={
            'accept': 'image/*,video/*,.pdf,.doc,.docx',
        }),
        help_text=_('Upload one or more photos, videos, or documents.'),
    )

    class Meta:
        model = CarDoc
        fields = ['title', 'content']
        labels = {
            'title': _('Document title'),
            'content': _('Notes'),
            'attachments': _('Attachments'),
        }
        widgets = {
            'title': forms.TextInput(attrs={'class': 'input', 'placeholder': _('Document title')}),
            'content': forms.Textarea(attrs={'class': 'textarea', 'rows': 10, 'placeholder': _('Add notes, instructions, or summary details...')}),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # The unified attachment mechanism renders at the bottom of the form.
        self.order_fields([name for name in ('title', 'content') if name in self.fields] + ['attachments'])
