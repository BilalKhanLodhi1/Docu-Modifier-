from django.urls import path

from . import views

app_name = "image_tools"
urlpatterns = [
    path("", views.index, name="index"),
    path("<int:doc_pk>/", views.gallery, name="gallery"),
    path("<int:doc_pk>/<int:index>/", views.editor, name="editor"),
    path("<int:doc_pk>/<int:index>/raw/", views.raw, name="raw"),
    path("<int:doc_pk>/<int:index>/preview/", views.preview, name="preview"),
    path("<int:doc_pk>/<int:index>/apply/", views.apply, name="apply"),
    path("<int:doc_pk>/<int:index>/ai/", views.ai_edit, name="ai_edit"),
]
