from django import forms

from apps.documents.models import Document

PDF_METHODS = [("ranges", "By page ranges"), ("pages", "Into individual pages"), ("every_n", "Every N pages")]
DOCX_METHODS = [("heading", "By headings"), ("tasks", "By tasks, chapters or exercises"),
                ("custom", "Custom selection of sections")]


class SplitForm(forms.Form):
    document = forms.ModelChoiceField(queryset=Document.objects.none())
    method = forms.ChoiceField(choices=PDF_METHODS + DOCX_METHODS)
    ranges = forms.CharField(required=False, max_length=300,
                             widget=forms.TextInput(attrs={"placeholder": "1-3, 4-6, 7-end"}))
    pages_per_file = forms.IntegerField(required=False, min_value=1, max_value=500, initial=2)
    heading_level = forms.ChoiceField(choices=[("1", "Heading 1 only"), ("2", "Heading 1 and 2"),
                                               ("3", "Headings 1 to 3")], initial="1", required=False)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["document"].queryset = Document.objects.filter(owner=user).with_current_type()

    def clean(self):
        data = super().clean()
        doc = data.get("document")
        method = data.get("method")
        if not doc or not method:
            return data
        ftype = doc.current_version.file_type
        if ftype == "pdf" and method not in dict(PDF_METHODS):
            self.add_error("method", "PDFs are split by pages. Convert to Word to split by headings.")
        if ftype == "docx" and method not in dict(DOCX_METHODS):
            self.add_error("method", "Word documents have no fixed pages. Split by headings, or export to PDF first and split the PDF.")
        if method == "ranges" and not data.get("ranges"):
            self.add_error("ranges", "Enter page ranges, for example 1-3, 4-6.")
        if method == "every_n" and not data.get("pages_per_file"):
            self.add_error("pages_per_file", "Enter how many pages each file should contain.")
        return data
