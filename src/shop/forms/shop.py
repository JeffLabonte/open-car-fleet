from django import forms
from django.utils.translation import gettext_lazy as _

from shop.forms.base import AttachmentField, MultipleFileInput, StagedAttachmentsMixin
from shop.models.garage import KnownShop, KnownShopProof


class KnownShopForm(forms.ModelForm):
    class Meta:
        model = KnownShop
        fields = ['name', 'email', 'phone', 'address', 'notes']
        labels = {
            'name': _('Shop name'),
            'email': _('Email'),
            'phone': _('Phone'),
            'address': _('Address'),
            'notes': _('Notes'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
            'email': forms.EmailInput(attrs={'class': 'input'}),
            'phone': forms.TextInput(attrs={'class': 'input'}),
            'address': forms.TextInput(attrs={'class': 'input'}),
            'notes': forms.Textarea(attrs={'class': 'textarea', 'rows': 4}),
        }


class KnownShopProofForm(StagedAttachmentsMixin, forms.ModelForm):
    attachments = AttachmentField(
        required=False,
        widget=MultipleFileInput(attrs={
            'accept': 'image/*,video/*,.pdf,.doc,.docx',
        }),
        help_text=_('Upload one or more photos, videos, or documents.'),
    )

    class Meta:
        model = KnownShopProof
        fields = ['title', 'content']
        labels = {
            'title': _('Proof title'),
            'content': _('Notes'),
            'attachments': _('Attachments'),
        }
        widgets = {
            'title': forms.TextInput(attrs={'class': 'input'}),
            'content': forms.Textarea(attrs={'class': 'textarea', 'rows': 6}),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # The unified attachment mechanism renders at the bottom of the form.
        self.order_fields([name for name in ('title', 'content') if name in self.fields] + ['attachments'])
