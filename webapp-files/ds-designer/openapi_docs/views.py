from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from utilities.mongodb_handler import openapi_collection,cppn_collection, cpps_collection, atomic_services_collection

from openapi_docs.serializers import AtomicUpsertSerializer, CPPSUpsertSerializer, CPPNUpsertSerializer
from openapi_docs.services import (
    upsert_atomic,
    publish_atomic_spec,
    republish_atomic_spec,
    _latest_published_version,
    upsert_cpps,
    publish_cpps_spec,
    upsert_cppn,
    publish_cppn_spec
)

from django.shortcuts import render
from django.urls import reverse
import re

def openapi_docs_home(request):
    return render(request, "openapi_docs/openapi_docs.html")


@api_view(["POST"])
#@permission_classes([IsAuthenticated])   # testare senza auth
def atomic_upsert(request):
    """
    Upsert dell'atomic + pubblicazione automatica della sua OpenAPI.
    """
    ser = AtomicUpsertSerializer(data=request.data)
    ser.is_valid(raise_exception=True)

    atomic_doc = upsert_atomic(ser.validated_data)

    # opzionale: aggiunta servers alla OAS con la base URL calcolata dalla request
    servers = [{"url": request.build_absolute_uri("/").rstrip("/")}]

    pub = publish_atomic_spec(service_id=atomic_doc["task_id"], servers=servers)
    if pub.get("status") != "ok":
        return Response(pub, status=status.HTTP_400_BAD_REQUEST)

    return Response({"status": "ok", "atomic": atomic_doc, "openapi": pub}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
#@permission_classes([IsAuthenticated])   # testare senza auth
def atomic_oas_latest(request, service_id: str):
    """
    Ritorna la OAS JSON latest (versione pubblicata più alta) per l'atomic indicato.
    """
    latest = _latest_published_version("atomic", "service_id", service_id)
    if not latest:
        return Response({"detail": "No published version"}, status=404)

    doc = openapi_collection.find_one({
        "level": "atomic",
        "service_id": service_id,
        "version": latest,
        "status": "published"
    }, {"_id": 0, "oas": 1})

    if not doc:
        return Response({"detail": "Spec not found"}, status=404)

    return Response(doc["oas"])


@api_view(["GET"])
#@permission_classes([IsAuthenticated])   # testare senza auth
def atomic_oas_version(request, service_id: str, version: str):
    """
    Ritorna la OAS JSON per versione specifica.
    """
    doc = openapi_collection.find_one({
        "level": "atomic",
        "service_id": service_id,
        "version": version
    }, {"_id": 0, "oas": 1})

    if not doc:
        return Response({"detail": "Spec not found"}, status=404)

    return Response(doc["oas"])

@api_view(["POST"])
def atomic_republish(request, service_id: str):
    servers = [{"url": request.build_absolute_uri("/").rstrip("/")}]
    res = republish_atomic_spec(service_id=service_id, servers=servers)
    status_code = 200 if res.get("status") == "ok" else 400
    return Response(res, status=status_code)


def atomic_docs_list(request):
    cur = atomic_services_collection.find({}, {"_id":0,"task_id":1,"name":1,"method":1,"url":1}).sort("name", 1)
    services = []
    for d in cur:
        task_id = d["task_id"]
        services.append({
            "task_id": task_id,
            "name": d["name"],
            "method": d["method"],
            "url": d["url"],
            "json_url": reverse("openapi_docs:atomic-oas-latest", args=[task_id]),
            "swagger_url": reverse("openapi_docs:atomic-docs-latest", args=[task_id]),
        })
    return render(request, "openapi_docs/atomic_docs.html", {"services": services})

def _latest_published_cpps_version(group_id: str) -> str | None:
    cur = openapi_collection.find(
        {"level": "cpps", "group_id": group_id, "status": "published"},
        {"version": 1, "_id": 0},
    )
    best, best_t = None, (-1, -1, -1)
    for d in cur:
        v = d.get("version")
        if not v: 
            continue
        try:
            M, m, p = [int(x) for x in v.split(".")]
            t = (M, m, p)
        except Exception:
            t = (0, 0, 0)
        if t > best_t:
            best_t, best = t, v
    return best

@api_view(["POST"])
def cpps_upsert(request):
    """
    Upsert del documento CPPS + publish immediato della OAS 3.1.
    """
    ser = CPPSUpsertSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    cpps_doc = upsert_cpps(ser.validated_data)

    # Server base per self-links nella spec
    servers = [{"url": request.build_absolute_uri("/").rstrip("/")}]

    pub = publish_cpps_spec(group_id=cpps_doc["group_id"], servers=servers)
    if pub.get("status") != "ok":
        return Response(pub, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        {"status": "ok", "cpps": cpps_doc, "openapi": pub},
        status=status.HTTP_201_CREATED,
    )

@api_view(["GET"])
def cpps_oas_latest(request, group_id: str):
    """
    Restituisce il JSON OpenAPI dell'ultima versione pubblicata per il CPPS.
    """
    latest = _latest_published_cpps_version(group_id)
    if not latest:
        return Response({"detail": "No published version"}, status=404)

    doc = openapi_collection.find_one(
        {"level": "cpps", "group_id": group_id, "version": latest, "status": "published"},
        {"_id": 0, "oas": 1},
    )
    if not doc:
        return Response({"detail": "Spec not found"}, status=404)
    return Response(doc["oas"])

@api_view(["GET"])
def cpps_oas_version(request, group_id: str, version: str):
    """
    Restituisce il JSON OpenAPI per una versione specifica.
    """
    doc = openapi_collection.find_one(
        {"level": "cpps", "group_id": group_id, "version": version},
        {"_id": 0, "oas": 1},
    )
    if not doc:
        return Response({"detail": "Spec not found"}, status=404)
    return Response(doc["oas"])

@api_view(["POST"])
def cpps_republish(request, group_id: str):
    """
    Ripubblica la OAS CPPS (patch-bump di versione). Utile se aggiorno il doc CPPS.
    """
    servers = [{"url": request.build_absolute_uri("/").rstrip("/")}]
    res = publish_cpps_spec(group_id=group_id, servers=servers)
    code = 200 if res.get("status") == "ok" else 400
    return Response(res, status=code)

def cpps_docs_list(request):
    """
    Pagina elenco CPPS per il template editor/templates/openapi_docs/cpps_docs.html.
    """
    cur = cpps_collection.find({}, {"_id": 0, "group_id": 1, "name": 1, "owner": 1})
    services = []
    for d in cur:
        gid = d["group_id"]
        services.append({
            "group_id": gid,
            "name": d.get("name"),
            "actor": d.get("owner"),
            "schema_url": reverse("openapi_docs:cpps-oas-latest", args=[gid]),
        })
    return render(request, "openapi_docs/cpps_docs.html", {"services": services})


def _latest_published_cppn_version(group_id: str) -> str | None:
    cur = openapi_collection.find({"level":"cppn","group_id":group_id,"status":"published"},{"version":1,"_id":0})
    best, best_t = None, (-1,-1,-1)
    for d in cur:
        try: t = tuple(int(x) for x in d["version"].split("."))
        except: t=(0,0,0)
        if t>best_t: best_t, best = t, d["version"]
    return best

@api_view(["POST"])
def cppn_upsert(request):
    ser = CPPNUpsertSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    doc = upsert_cppn(ser.validated_data)
    servers = [{"url": request.build_absolute_uri("/").rstrip("/")}]
    pub = publish_cppn_spec(group_id=doc["group_id"], servers=servers)
    code = status.HTTP_201_CREATED if pub.get("status")=="ok" else status.HTTP_400_BAD_REQUEST
    return Response({"status": pub.get("status"), "cppn": doc, "openapi": pub}, status=code)

@api_view(["GET"])
def cppn_oas_latest(request, group_id: str):
    latest = _latest_published_cppn_version(group_id)
    if not latest:
        return Response({"detail":"No published version"}, status=404)
    d = openapi_collection.find_one({"level":"cppn","group_id":group_id,"version":latest,"status":"published"},{"_id":0,"oas":1})
    if not d: return Response({"detail":"Spec not found"}, status=404)
    return Response(d["oas"])

@api_view(["GET"])
def cppn_oas_version(request, group_id: str, version: str):
    d = openapi_collection.find_one({"level":"cppn","group_id":group_id,"version":version},{"_id":0,"oas":1})
    if not d: return Response({"detail":"Spec not found"}, status=404)
    return Response(d["oas"])

@api_view(["POST"])
def cppn_republish(request, group_id: str):
    servers = [{"url": request.build_absolute_uri("/").rstrip("/")}]
    res = publish_cppn_spec(group_id=group_id, servers=servers)
    code = 200 if res.get("status")=="ok" else 400
    return Response(res, status=code)

def cppn_docs_list(request):
    cur = cppn_collection.find({}, {"_id":0,"group_id":1,"name":1,"actors":1})
    services = []

    for d in cur:
        gid = d["group_id"]
        actors_list = [re.sub(r"\s+", " ", a).strip() for a in d.get("actors", [])]
        services.append({
            "group_id": gid,
            "name": d.get("name",""),
            "actors": ", ".join(actors_list),
            "schema_url": reverse("openapi_docs:cppn-oas-latest", args=[gid]),
        })
    return render(request, "openapi_docs/cppn_docs.html", {"services": services})