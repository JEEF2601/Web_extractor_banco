from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="home"),
    path("download-csv/", views.download_csv, name="download_csv"),
]
