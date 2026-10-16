from django import template

register = template.Library()

TONES = {
    "completed": "ok", "ready": "ok", "running": "busy", "queued": "busy", "processing": "busy",
    "failed": "bad", "uploaded": "quiet", "changed": "ok", "reverted": "warn", "preserved": "quiet",
    "unchanged": "quiet",
}


@register.filter
def tone(status):
    """Map a status word to a colour tone used by .badge--<tone>."""
    return TONES.get(str(status), "quiet")


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def add_class(field, css):
    return field.as_widget(attrs={"class": css})


@register.inclusion_tag("partials/field.html")
def field(bound_field, hint=None, wide=False, mark_optional=True):
    """Render a form field with label, help text and errors in one consistent shape."""
    widget = bound_field.field.widget.__class__.__name__
    return {
        "f": bound_field, "hint": hint or bound_field.help_text, "wide": wide, "mark_optional": mark_optional,
        "is_check": widget == "CheckboxInput",
        "is_choice_list": widget in ("RadioSelect", "CheckboxSelectMultiple"),
    }
