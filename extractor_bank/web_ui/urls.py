from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("procesar/", views.process_pdf, name="process_pdf"),
]