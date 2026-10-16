"""Navigation shared by every page."""
from django.urls import reverse

NAV = [
    ("documents:dashboard", "Overview", ("documents:dashboard",)),
    ("documents:workspace", "Documents", ("documents:workspace", "documents:detail", "documents:job")),
    ("rewriting:index", "Rewrite", ("rewriting:",)),
    ("templates_manager:index", "Templates", ("templates_manager:",)),
    ("image_tools:index", "Images", ("image_tools:",)),
    ("splitting:index", "Split", ("splitting:",)),
    ("converters:index", "Convert", ("converters:",)),
    ("history:index", "History", ("history:",)),
]


def navigation(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    match = getattr(request, "resolver_match", None)
    current = f"{match.namespace}:{match.url_name}" if match and match.namespace else ""
    items = []
    for url_name, label, prefixes in NAV:
        active = any(current == p or (p.endswith(":") and current.startswith(p)) for p in prefixes)
        items.append({"url": reverse(url_name), "label": label, "active": active})
    return {"nav_items": items}
