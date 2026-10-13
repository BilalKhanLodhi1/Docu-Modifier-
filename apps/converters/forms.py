from django import forms

from apps.documents.forms import UploadForm
from apps.documents.models import Document


class ConvertForm(UploadForm):
    file = forms.FileField(required=False, widget=forms.ClearableFileInput(attrs={"accept": ".docx,.pdf"}))
    document = forms.ModelChoiceField(queryset=Document.objects.none(), required=False)
    ocr = forms.ChoiceField(choices=[("auto", "Detect automatically"), ("force", "Always use OCR"),
                                     ("off", "Never use OCR")], initial="auto", required=False,
                            label="OCR for scanned PDFs")
    ocr_lang = forms.ChoiceField(choices=[("eng", "English"), ("urd", "Urdu"), ("ara", "Arabic"),
                                          ("fra", "French"), ("deu", "German"), ("spa", "Spanish")],
                                 initial="eng", required=False, label="OCR language")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["document"].queryset = Document.objects.filter(owner=user)

    def clean_file(self):
        if not self.cleaned_data.get("file"):
            return None
        return super().clean_file()

    def clean(self):
        data = super().clean()
        if not data.get("file") and not data.get("document"):
            raise forms.ValidationError("Upload a file or choose one of your documents.")
        return data
