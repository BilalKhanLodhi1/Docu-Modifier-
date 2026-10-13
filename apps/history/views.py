from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render

from .models import ProcessingHistory


@login_required
def index(request):
    qs = ProcessingHistory.objects.filter(user=request.user).select_related("document", "job")
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    if status in ("completed", "failed", "queued"):
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(document_name__icontains=q)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "history/index.html", {"page": page, "status": status, "q": q})
