from django.urls import path

from . import views

app_name = "splitting"
urlpatterns = [
    path("", views.index, name="index"),
    path("preview/<str:token>/", views.preview, name="preview"),
]
