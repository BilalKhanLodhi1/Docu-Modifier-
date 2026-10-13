from django import forms
from django.conf import settings

from services.document_validator import detect_type
from services.exceptions import UnsupportedFileError


class UploadForm(forms.Form):
    file = forms.FileField(widget=forms.ClearableFileInput(attrs={"accept": ".docx,.pdf"}))

    def clean_file(self):
        f = self.cleaned_data["file"]
        limit = settings.DOCUCRAFT_MAX_UPLOAD_MB * 1024 * 1024
        if f.size > limit:
            raise forms.ValidationError(f"The file is larger than the {settings.DOCUCRAFT_MAX_UPLOAD_MB} MB limit.")
        if f.size == 0:
            raise forms.ValidationError("The file is empty.")
        try:
            self.detected_type = detect_type(f, f.name)
        except UnsupportedFileError as exc:
            raise forms.ValidationError(str(exc))
        return f


class PipelineForm(forms.Form):
    STEPS = [("rewrite", "Rewrite content with AI"), ("format", "Apply a template"),
             ("export_pdf", "Export a PDF copy")]
    steps = forms.MultipleChoiceField(choices=STEPS, widget=forms.CheckboxSelectMultiple)
    mode = forms.ChoiceField(required=False)
    template = forms.ModelChoiceField(queryset=None, required=False)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.templates_manager.models import DocumentTemplate
        from services.prompts import MODE_LABELS
        self.fields["mode"].choices = [(k, v) for k, v in MODE_LABELS.items() if k != "custom"]
        self.fields["template"].queryset = DocumentTemplate.objects.visible_to(user)

    def clean(self):
        data = super().clean()
        if "format" in data.get("steps", []) and not data.get("template"):
            self.add_error("template", "Choose a template for the formatting step.")
        return data
