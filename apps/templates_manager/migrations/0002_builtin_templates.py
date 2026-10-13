from django.db import migrations

BUILTINS = [
    {
        "name": "Reference Report (Academic)",
        "kind": "academic",
        "description": "Centred cover page, Times New Roman 12 pt, justified body, bold 16/14 pt headings, "
                       "shaded monospaced code. Suited to lab reports and assignments.",
        "config": {"body_font": "Times New Roman", "body_size": 12, "heading_font": "Times New Roman",
                   "heading_sizes": {"1": 16, "2": 14, "3": 12}, "title_size": 22, "justify": True,
                   "line_spacing": 1.15, "cover": {"enabled": True, "style": "academic"}, "page_numbers": True},
    },
    {
        "name": "Corporate Clean",
        "kind": "corporate",
        "description": "Prepared-for / prepared-by title page, Calibri 11 pt, left-aligned body, generous spacing "
                       "and a table of contents. Suited to proposals and business reports.",
        "config": {"body_font": "Calibri", "body_size": 11, "heading_font": "Calibri",
                   "heading_sizes": {"1": 16, "2": 13, "3": 11.5}, "title_size": 26, "justify": False,
                   "line_spacing": 1.2, "space_after_pt": 10, "heading_color": "1F3A68",
                   "cover": {"enabled": True, "style": "corporate"}, "toc": True,
                   "page_number_style": "{PAGE}", "page_break_before_h1": True},
    },
    {
        "name": "Simple Document (No Cover)",
        "kind": "corporate",
        "description": "Consistent fonts, spacing and page numbers without adding a cover page.",
        "config": {"body_font": "Georgia", "body_size": 11, "heading_font": "Georgia", "justify": False,
                   "cover": {"enabled": False, "style": "academic"}, "page_numbers": True},
    },
]


def create(apps, schema_editor):
    T = apps.get_model("templates_manager", "DocumentTemplate")
    for b in BUILTINS:
        T.objects.get_or_create(name=b["name"], owner=None, defaults={**b, "is_shared": True})


def remove(apps, schema_editor):
    T = apps.get_model("templates_manager", "DocumentTemplate")
    T.objects.filter(owner=None, name__in=[b["name"] for b in BUILTINS]).delete()


class Migration(migrations.Migration):
    dependencies = [("templates_manager", "0001_initial")]
    operations = [migrations.RunPython(create, remove)]
