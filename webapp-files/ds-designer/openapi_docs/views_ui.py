from django.views.generic import TemplateView
from django.urls import reverse

class SwaggerUIView(TemplateView):
    template_name = "openapi_docs/swagger_ui.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        service_id = self.kwargs["service_id"]
        version = self.kwargs.get("version")
        # Se è passata una versione, uso l'endpoint versionato,
        # altrimenti la latest.
        ctx["spec_url"] = reverse(
            "openapi_docs:atomic-oas-version",
            args=[service_id, version]
        ) if version else reverse(
            "openapi_docs:atomic-oas-latest",
            args=[service_id]
        )
        return ctx
    
class SwaggerUIViewCPPS(TemplateView):
    """
    Mostra Swagger UI per un CPPS.
    - /openapi_docs/docs/cpps/<group_id>         -> latest
    - /openapi_docs/docs/cpps/<group_id>/versions/<version> -> specifica versione
    Il template usato è lo stesso che usi per gli Atomic: swagger_ui.html
    Si aspetta una variabile 'spec_url' nel context.
    """
    template_name = "openapi_docs/swagger_ui.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        group_id = self.kwargs["group_id"]
        version = self.kwargs.get("version")

        if version:
            ctx["spec_url"] = reverse(
                "openapi_docs:cpps-oas-version", args=[group_id, version]
            )
            ctx["page_title"] = f"CPPS {group_id} – Swagger (v{version})"
        else:
            ctx["spec_url"] = reverse(
                "openapi_docs:cpps-oas-latest", args=[group_id]
            )
            ctx["page_title"] = f"CPPS {group_id} – Swagger"

        return ctx
    

class SwaggerUIViewCPPN(TemplateView):
    template_name = "openapi_docs/swagger_ui.html"
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        gid = self.kwargs["group_id"]
        ver = self.kwargs.get("version")
        if ver:
            ctx["spec_url"] = reverse("openapi_docs:cppn-oas-version", args=[gid, ver])
            ctx["page_title"] = f"CPPN {gid} – Swagger (v{ver})"
        else:
            ctx["spec_url"] = reverse("openapi_docs:cppn-oas-latest", args=[gid])
            ctx["page_title"] = f"CPPN {gid} – Swagger"
        return ctx
