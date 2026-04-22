from django.urls import path
from . import views

urlpatterns = [
    path('', views.data_view_editor, name='diagram_list'),  # pagina HTML
    path('api/list/', views.list_diagrams, name='list_diagrams'),
    path('api/<str:diagram_id>/', views.get_diagram, name='get_diagram'),
    path('by-name/<str:diagram_name>/', views.view_diagram_by_name, name='diagram_view_by_name'),

]
