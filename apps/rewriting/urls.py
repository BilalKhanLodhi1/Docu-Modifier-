from django.urls import path

from . import views

app_name = "rewriting"
urlpatterns = [
    path("", views.index, name="index"),
    path("review/<int:job_pk>/", views.review, name="review"),
]
