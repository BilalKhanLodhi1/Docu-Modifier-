from django import forms

from apps.documents.models import Document
from services.prompts import MODE_LABELS


class RewriteForm(forms.Form):
    document = forms.ModelChoiceField(queryset=Document.objects.none())
    mode = forms.ChoiceField(choices=list(MODE_LABELS.items()), widget=forms.RadioSelect, initial="professional")
    audience = forms.CharField(max_length=200, required=False,
                               widget=forms.TextInput(attrs={"placeholder": "For example: hiring managers, course instructor"}))
    custom_instructions = forms.CharField(max_length=1500, required=False, widget=forms.Textarea(
        attrs={"rows": 3, "placeholder": "For example: use British English and keep each paragraph under 120 words"}))

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["document"].queryset = Document.objects.filter(owner=user).word_documents()

    def clean(self):
        data = super().clean()
        if data.get("mode") == "custom" and not (data.get("custom_instructions") or "").strip():
            self.add_error("custom_instructions", "Describe how you want the document rewritten.")
        return data
