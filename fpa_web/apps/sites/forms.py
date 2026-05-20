from django import forms

from .models import JobSite


class JobSiteForm(forms.ModelForm):
    class Meta:
        model = JobSite
        fields = ['name', 'address', 'place_id', 'latitude', 'longitude', 'store_type', 'notes']
        widgets = {
            'address': forms.TextInput(
                attrs={
                    'id': 'address-input',
                    'autocomplete': 'off',
                    'placeholder': 'Start typing an address…',
                    'class': 'w-full rounded-lg border-slate-300',
                }
            ),
            'place_id': forms.HiddenInput(),
            'latitude': forms.HiddenInput(),
            'longitude': forms.HiddenInput(),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'w-full rounded-lg border-slate-300'}),
        }
