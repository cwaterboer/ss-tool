from django import forms

from .models import Scan


class ScanCreateForm(forms.ModelForm):
    upload = forms.FileField(
        label='Upload video (.mp4) or image zip (.zip)',
        widget=forms.FileInput(attrs={'accept': '.mp4,.zip'}),
    )

    class Meta:
        model = Scan
        fields = ['name', 'notes', 'input_type', 'fps', 'mode', 'kv_window_size', 'keyframe_interval', 'conf_threshold']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'w-full rounded-lg border-slate-300'}),
            'name': forms.TextInput(attrs={'class': 'w-full rounded-lg border-slate-300'}),
            'fps': forms.NumberInput(attrs={'class': 'w-full rounded-lg border-slate-300'}),
            'kv_window_size': forms.NumberInput(attrs={'class': 'w-full rounded-lg border-slate-300'}),
            'keyframe_interval': forms.NumberInput(attrs={'class': 'w-full rounded-lg border-slate-300'}),
            'conf_threshold': forms.NumberInput(attrs={'step': '0.1', 'class': 'w-full rounded-lg border-slate-300'}),
        }
