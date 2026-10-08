from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("procesar/", views.process_pdf, name="process_pdf"),
    path("renombrar/", views.rename_page, name="rename_page"),
    path("renombrar/api/", views.rename_pdf, name="rename_pdf"),
]