from django import forms

from services.docx_writer import DEFAULT_CONFIG, merged_config

from .models import DocumentTemplate

FONT_CHOICES = [(f, f) for f in ("Times New Roman", "Georgia", "Cambria", "Garamond", "Book Antiqua",
                                 "Calibri", "Arial", "Helvetica", "Segoe UI", "Liberation Serif")]
CODE_FONTS = [(f, f) for f in ("Consolas", "Courier New", "Menlo", "Source Code Pro", "Liberation Mono")]


class TemplateForm(forms.ModelForm):
    """Edits DocumentTemplate.config through ordinary, validated fields."""
    page_size = forms.ChoiceField(choices=[("A4", "A4"), ("Letter", "US Letter"), ("Legal", "US Legal")])
    orientation = forms.ChoiceField(choices=[("portrait", "Portrait"), ("landscape", "Landscape")])
    margin_top = forms.DecimalField(min_value=0.3, max_value=2.5, decimal_places=2, label="Top margin (in)")
    margin_bottom = forms.DecimalField(min_value=0.3, max_value=2.5, decimal_places=2, label="Bottom margin (in)")
    margin_left = forms.DecimalField(min_value=0.3, max_value=2.5, decimal_places=2, label="Left margin (in)")
    margin_right = forms.DecimalField(min_value=0.3, max_value=2.5, decimal_places=2, label="Right margin (in)")
    body_font = forms.ChoiceField(choices=FONT_CHOICES)
    body_size = forms.DecimalField(min_value=8, max_value=16, decimal_places=1, label="Body size (pt)")
    line_spacing = forms.DecimalField(min_value=1.0, max_value=2.5, decimal_places=2)
    space_after_pt = forms.DecimalField(min_value=0, max_value=24, decimal_places=1, label="Space after paragraphs (pt)")
    justify = forms.BooleanField(required=False, label="Justify body paragraphs")
    heading_font = forms.ChoiceField(choices=FONT_CHOICES)
    h1_size = forms.DecimalField(min_value=10, max_value=28, decimal_places=1, label="Heading 1 (pt)")
    h2_size = forms.DecimalField(min_value=9, max_value=24, decimal_places=1, label="Heading 2 (pt)")
    h3_size = forms.DecimalField(min_value=8, max_value=20, decimal_places=1, label="Heading 3 (pt)")
    title_size = forms.DecimalField(min_value=14, max_value=40, decimal_places=1, label="Title (pt)")
    code_font = forms.ChoiceField(choices=CODE_FONTS)
    code_size = forms.DecimalField(min_value=7, max_value=14, decimal_places=1, label="Code size (pt)")
    page_break_before_h1 = forms.BooleanField(required=False, label="Start each main section on a new page")
    cover_enabled = forms.BooleanField(required=False, label="Include a cover page")
    cover_style = forms.ChoiceField(choices=[("academic", "Academic (centred, submitted by / to)"),
                                             ("corporate", "Corporate (title, prepared for / by)")])
    toc = forms.BooleanField(required=False, label="Include a table of contents")
    page_numbers = forms.BooleanField(required=False)
    page_number_style = forms.CharField(max_length=60, required=False,
                                        help_text="Use {PAGE} and optionally {NUMPAGES}.")
    header_text = forms.CharField(max_length=150, required=False)
    footer_text = forms.CharField(max_length=150, required=False)

    class Meta:
        model = DocumentTemplate
        fields = ("name", "description", "kind", "logo", "is_shared")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cfg = merged_config(self.instance.config if self.instance and self.instance.pk else {})
        m = cfg["margins_in"]
        init = {
            "page_size": cfg["page_size"], "orientation": cfg["orientation"],
            "margin_top": m["top"], "margin_bottom": m["bottom"], "margin_left": m["left"], "margin_right": m["right"],
            "body_font": cfg["body_font"], "body_size": cfg["body_size"], "line_spacing": cfg["line_spacing"],
            "space_after_pt": cfg["space_after_pt"], "justify": cfg["justify"], "heading_font": cfg["heading_font"],
            "h1_size": cfg["heading_sizes"]["1"], "h2_size": cfg["heading_sizes"]["2"],
            "h3_size": cfg["heading_sizes"]["3"], "title_size": cfg["title_size"], "code_font": cfg["code_font"],
            "code_size": cfg["code_size"], "page_break_before_h1": cfg["page_break_before_h1"],
            "cover_enabled": cfg["cover"]["enabled"], "cover_style": cfg["cover"]["style"], "toc": cfg["toc"],
            "page_numbers": cfg["page_numbers"], "page_number_style": cfg["page_number_style"],
            "header_text": cfg["header_text"], "footer_text": cfg["footer_text"],
        }
        for k, v in init.items():
            self.fields[k].initial = v

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo and hasattr(logo, "size") and logo.size > 2 * 1024 * 1024:
            raise forms.ValidationError("The logo must be smaller than 2 MB.")
        return logo

    def build_config(self):
        d = self.cleaned_data
        f = float
        return {
            "page_size": d["page_size"], "orientation": d["orientation"],
            "margins_in": {"top": f(d["margin_top"]), "bottom": f(d["margin_bottom"]),
                           "left": f(d["margin_left"]), "right": f(d["margin_right"])},
            "body_font": d["body_font"], "body_size": f(d["body_size"]), "line_spacing": f(d["line_spacing"]),
            "space_after_pt": f(d["space_after_pt"]), "justify": d["justify"], "heading_font": d["heading_font"],
            "heading_sizes": {"1": f(d["h1_size"]), "2": f(d["h2_size"]), "3": f(d["h3_size"])},
            "title_size": f(d["title_size"]), "code_font": d["code_font"], "code_size": f(d["code_size"]),
            "page_break_before_h1": d["page_break_before_h1"],
            "cover": {"enabled": d["cover_enabled"], "style": d["cover_style"]}, "toc": d["toc"],
            "page_numbers": d["page_numbers"], "page_number_style": d["page_number_style"] or "Page {PAGE}",
            "header_text": d["header_text"], "footer_text": d["footer_text"],
        }

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.config = self.build_config()
        if commit:
            obj.save()
        return obj


class FormatForm(forms.Form):
    """Per-run choices when applying a template to one document."""
    template = forms.ModelChoiceField(queryset=DocumentTemplate.objects.none(), empty_label=None)
    include_cover = forms.BooleanField(required=False, initial=True, label="Include a cover page")
    include_toc = forms.BooleanField(required=False, label="Include a table of contents")
    page_numbers = forms.BooleanField(required=False, initial=True, label="Add page numbers")
    scope = forms.ChoiceField(choices=[("all", "Entire document"), ("selected", "Selected sections only")],
                              initial="all", widget=forms.RadioSelect)
    sections = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    logo = forms.ImageField(required=False, help_text="Optional. Overrides the template's logo for this document.")
    organization = forms.CharField(max_length=200, required=False, label="Institution or company")
    department = forms.CharField(max_length=200, required=False)
    program = forms.CharField(max_length=200, required=False, label="Degree, program or category")
    title = forms.CharField(max_length=250)
    subtitle = forms.CharField(max_length=250, required=False)
    report_number = forms.CharField(max_length=100, required=False, label="Report, task or assignment number")
    author = forms.CharField(max_length=150, required=False, label="Author name")
    author_id = forms.CharField(max_length=60, required=False, label="Student or employee ID")
    course = forms.CharField(max_length=200, required=False, label="Course, project or department")
    submitted_to = forms.CharField(max_length=200, required=False, label="Submitted to / prepared for")
    date = forms.CharField(max_length=60, required=False)

    META_FIELDS = ("organization", "department", "program", "title", "subtitle", "report_number", "author",
                   "author_id", "course", "submitted_to", "date")

    def __init__(self, *args, user=None, sections=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["template"].queryset = DocumentTemplate.objects.visible_to(user)
        self.fields["sections"].choices = [(s["id"], s["text"]) for s in (sections or [])]

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo and logo.size > 2 * 1024 * 1024:
            raise forms.ValidationError("The logo must be smaller than 2 MB.")
        return logo

    def clean(self):
        data = super().clean()
        if data.get("scope") == "selected" and not data.get("sections"):
            self.add_error("sections", "Choose at least one section, or apply to the entire document.")
        return data
