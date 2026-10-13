from django.urls import path

from . import views

app_name = "converters"
urlpatterns = [path("", views.index, name="index")]
