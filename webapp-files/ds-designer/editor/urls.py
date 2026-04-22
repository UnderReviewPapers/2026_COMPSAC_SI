from django.urls import path
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from . import views, views_rbac

urlpatterns = [
    path('', views.data_view_editor, name='editor'),
    path('analyze-bpmn/', views.analyze_bpmn_view, name='analyze_bpmn'),

    path('api/save-diagram/', views.save_diagram),  # POST
    path('api/save-diagram/<str:diagram_id>/', views.save_diagram),  # PUT

    path('api/save-atomic-service/', views.save_atomic_service, name='save_atomic_service'),
    path('api/atomic_service/<str:task_id>/', views.get_atomic_service, name='get_atomic_service'),

    path('api/save-cpps-service/', views.save_cpps_service, name='save_cpps_service'),
    path('api/save-cppn-service/', views.save_cppn_service, name='save_cppn_service'),
    path('api/generate-projects/', views.generate_laravel_projects, name='generate_laravel_projects'),

    path('api/cppn_service/<str:group_id>/', views.get_cppn_service, name='get_cppn_service'),
    path('api/cpps_service/<str:group_id>/', views.get_cpps_service, name='get_cpps_service'),
    path('api/check-name/', views.check_diagram_name, name='check_diagram_name'),

    path('api/all-services/', views.get_all_services, name='all-services'),
    path('api/delete_group/<str:group_id>/', views.delete_group, name='delete_group'),
    path('api/add-nested-cpps/<str:group_id>/', views.add_nested_cpps),
    path('api/delete-atomic/<str:atomic_id>/', views.delete_atomic),

    path('api/delete-diagram/<str:diagram_id>/', views.delete_diagram_and_services, name='delete_diagram_and_services'),

    path('policies', views.rbac_policies_view, name='rbac_policies'),
    path("policies/atomic/", views_rbac.rbac_atomic_view, name="rbac_atomic"),
    path("policies/atomic/<str:atomic_id>/edit/", views_rbac.rbac_atomic_edit, name="rbac_atomic_edit"),

    path("api/rbac/policies/atomic/by-diagram",
         views_rbac.get_diagram_atomic_rbac,
         name="rbac_atomic_by_diagram"),

    path(
        "api/rbac/policies/atomic/by-id",
        views_rbac.get_atomic_policy_by_atomic_id,
        name="rbac_atomic_by_atomic_id",
    ),

    path("api/actors", views_rbac.get_diagram_actors, name="diagram_actors"),

    path("api/rbac/policies/atomic/permissions",
         views_rbac.update_atomic_permissions,
         name="rbac_atomic_update_permissions"),
    
    path("api/rbac/policies/cpps/by-diagram",  views_rbac.get_cpps_by_diagram, name="rbac_cpps_by_diagram"),

    path("policies/cpps/", views_rbac.rbac_cpps_view, name="rbac_cpps"),
    path("api/rbac/policies/cpps/one",         views_rbac.get_cpps_one,        name="rbac_cpps_one"),
    path("api/rbac/policies/cpps/permissions", views_rbac.update_cpps_permissions, name="rbac_cpps_update_permissions"),

    path("policies/cpps/<str:cpps_id>/edit/", views_rbac.rbac_cpps_edit, name="rbac_cpps_edit"),
    path("policies/cppn/", views_rbac.rbac_cppn_view, name="rbac_cppn"),

     path("api/rbac/policies/cppn/by-diagram",
         views_rbac.get_cppn_by_diagram,
         name="rbac_cppn_by_diagram"),
    
    path("policies/cppn/<str:cppn_id>/edit/",
         views_rbac.rbac_cppn_edit,
         name="rbac_cppn_edit"),

    path(
        "policies/cppn/<str:cppn_id>/",
        views_rbac.rbac_cppn_services_view,
        name="rbac_cppn_services",
    ),

    # API: lista servizi (atomic/cpps) con attori che hanno invoke
    path(
        "api/rbac/policies/cppn/services",
        views_rbac.get_cppn_services,
        name="rbac_cppn_services_api",
    ),

    path("api/rbac/policies/cppn/one",         views_rbac.get_cppn_one,          name="rbac_cppn_one"),
    path("api/rbac/policies/cppn/permissions", views_rbac.update_cppn_permissions, name="rbac_cppn_update_permissions"),


]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)