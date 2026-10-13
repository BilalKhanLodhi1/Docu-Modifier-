from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("rewrite/", include("apps.rewriting.urls")),
    path("images/", include("apps.image_tools.urls")),
    path("split/", include("apps.splitting.urls")),
    path("convert/", include("apps.converters.urls")),
    path("templates/", include("apps.templates_manager.urls")),
    path("history/", include("apps.history.urls")),
    path("", include("apps.documents.urls")),
]
