from django.urls import path
from .views import (
    openapi_docs_home,       
    atomic_docs_list,        
    atomic_upsert,
    atomic_oas_latest,
    atomic_oas_version,
    atomic_republish,
)

from .views import ( 
    cpps_upsert,
    cpps_oas_latest,
    cpps_oas_version,
    cpps_republish,
    cpps_docs_list,
    cppn_upsert,
    cppn_republish,
    cppn_oas_latest,
    cppn_oas_version,
    cppn_docs_list
)
from .views_ui import SwaggerUIViewCPPS ,SwaggerUIViewCPPN

from .views_ui import SwaggerUIView

app_name = "openapi_docs"

urlpatterns = [

    # Homepage OpenAPI
    path("openapi_docs/", openapi_docs_home, name="openapi-docs-page"),       # NEW

    # Lista Atomic
    path("openapi_docs/docs/atomic/", atomic_docs_list, name="atomic-docs"),  # NEW

    # API Atomic
    path("api/openapi/atomic", atomic_upsert, name="atomic-upsert"),
    path("api/openapi/atomic/<str:service_id>/publish", atomic_republish, name="atomic-republish"),

    # JSON OpenAPI
    path("openapi/services/<str:service_id>", atomic_oas_latest, name="atomic-oas-latest"),
    path("openapi/services/<str:service_id>/versions/<str:version>", atomic_oas_version, name="atomic-oas-version"),

    # Swagger UI
    path("docs/services/<str:service_id>", SwaggerUIView.as_view(), name="atomic-docs-latest"),
    path("docs/services/<str:service_id>/versions/<str:version>", SwaggerUIView.as_view(), name="atomic-docs-version"),

    # ----- CPPS: pagina elenco con link JSON e Swagger -----
    path(
        "openapi_docs/docs/cpps/",
        cpps_docs_list,
        name="cpps-docs",
    ),

    # ----- CPPS: API per upsert & publish -----
    path(
        "openapi_docs/api/openapi/cpps",
        cpps_upsert,
        name="cpps-upsert",
    ),
    path(
        "openapi_docs/api/openapi/cpps/<str:group_id>/publish",
        cpps_republish,
        name="cpps-republish",
    ),

    # ----- CPPS: JSON OpenAPI (latest & by-version) -----
    path(
        "openapi_docs/openapi/cpps/<str:group_id>",
        cpps_oas_latest,
        name="cpps-oas-latest",
    ),
    path(
        "openapi_docs/openapi/cpps/<str:group_id>/versions/<str:version>",
        cpps_oas_version,
        name="cpps-oas-version",
    ),

    # ----- CPPS: Swagger UI -----
    path(
        "openapi_docs/docs/cpps/<str:group_id>",
        SwaggerUIViewCPPS.as_view(),
        name="swagger-viewer-cpps",
    ),
    path(
        "openapi_docs/docs/cpps/<str:group_id>/versions/<str:version>",
        SwaggerUIViewCPPS.as_view(),
        name="swagger-viewer-cpps-version",
    ),

    path("openapi_docs/api/openapi/cppn", cppn_upsert, name="cppn-upsert"),
    path("openapi_docs/api/openapi/cppn/<str:group_id>/publish", cppn_republish, name="cppn-republish"),
    path("openapi_docs/openapi/cppn/<str:group_id>", cppn_oas_latest, name="cppn-oas-latest"),
    path("openapi_docs/openapi/cppn/<str:group_id>/versions/<str:version>", cppn_oas_version, name="cppn-oas-version"),
    path("openapi_docs/docs/cppn/", cppn_docs_list, name="cppn-docs"),
    path("openapi_docs/docs/cppn/<str:group_id>", SwaggerUIViewCPPN.as_view(), name="swagger-viewer-cppn"),
    path("openapi_docs/docs/cppn/<str:group_id>/versions/<str:version>", SwaggerUIViewCPPN.as_view(), name="swagger-viewer-cppn-version"),


]
