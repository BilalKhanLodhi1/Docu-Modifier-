from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("workspace/", views.workspace, name="workspace"),
    path("documents/upload/", views.upload, name="upload"),
    path("documents/<int:pk>/", views.detail, name="detail"),
    path("documents/<int:pk>/preview/<int:version_pk>/", views.preview, name="preview"),
    path("documents/<int:pk>/delete/", views.delete, name="delete"),
    path("documents/<int:pk>/pipeline/", views.pipeline, name="pipeline"),
    path("documents/<int:pk>/original/", views.download_original, name="download_original"),
    path("versions/<int:version_pk>/current/", views.make_current, name="make_current"),
    path("files/version/<int:version_pk>/", views.download_version, name="download_version"),
    path("files/output/<int:output_pk>/", views.download_output, name="download_output"),
    path("jobs/<int:pk>/", views.job_detail, name="job"),
    path("jobs/<int:pk>/status/", views.job_status, name="job_status"),
    path("jobs/<int:pk>/retry/", views.job_retry, name="job_retry"),
]
