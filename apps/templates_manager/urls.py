from django.urls import path

from . import views

app_name = "templates_manager"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.create, name="create"),
    path("<int:pk>/edit/", views.edit, name="edit"),
    path("<int:pk>/delete/", views.delete, name="delete"),
    path("apply/<int:doc_pk>/", views.apply, name="apply"),
]
