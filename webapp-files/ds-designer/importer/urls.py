from django.urls import path
from . import views


urlpatterns = [
    path('', views.importer_home, name='importer_home'),
    path('upload/', views.upload_imported_diagram, name='import_upload'),
    path('summary/', views.import_summary, name='import_summary'), 
]
