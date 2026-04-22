# openapi_docs/services.py
from __future__ import annotations
import hashlib, json
from datetime import datetime
from typing import Optional, Tuple
# riuso diretto delle collection dal tuo modulo
from utilities.mongodb_handler import atomic_services_collection, cpps_collection, cppn_collection, openapi_collection

from openapi_docs.openapi_generator import OpenAPIGenerator
from openapi_docs.oas_validation import validate_openapi


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

def _sha256(obj) -> str:
    canon = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canon).hexdigest()

def _parse_semver(v: str) -> Tuple[int, int, int]:
    try:
        M, m, p = v.split(".")
        return int(M), int(m), int(p)
    except Exception:
        return (0, 0, 0)

def _format_semver(t: Tuple[int,int,int]) -> str:
    return f"{t[0]}.{t[1]}.{t[2]}"

def _latest_published_version(service_id: str) -> Optional[str]:
    """
    Cerca in `openapi` la versione pubblicata più alta (semver) per il servizio.
    """
    cur = openapi_collection.find(
        {"level": "atomic", "service_id": service_id, "status": "published"},
        {"version": 1, "_id": 0}
    )
    best = None
    best_t = (-1, -1, -1)
    for doc in cur:
        v = doc.get("version")
        if not v:
            continue
        t = _parse_semver(v)
        if t > best_t:
            best_t, best = t, v
    return best

def _bump_patch(v: Optional[str]) -> str:
    if not v:
        return "1.0.0"   # prima pubblicazione
    M, m, p = _parse_semver(v)
    return _format_semver((M, m, p + 1))


def upsert_atomic(doc: dict) -> dict:
    """
    Salva/aggiorna il documento Atomic (senza toccare le OpenAPI).
    doc deve contenere: diagram_id, task_id, name, atomic_type, method, url, owner, input, output
    """
    atomic_services_collection.update_one(
        {"task_id": doc["task_id"]},
        {"$set": {
            "diagram_id": doc["diagram_id"],
            "name": doc["name"],
            "atomic_type": doc["atomic_type"],
            "method": doc["method"],
            "url": doc["url"],
            "owner": doc["owner"],
            "input": doc["input"],
            "output": doc["output"],
            "updated_at": _now_iso()
        }, "$setOnInsert": {"created_at": _now_iso()}},
        upsert=True
    )
    return atomic_services_collection.find_one({"task_id": doc["task_id"]}, {"_id": 0})


def publish_atomic_spec(service_id: str, servers: list[dict] | None = None) -> dict:
    """
    Pubblica la OAS per un Atomic service (version bump patch).
    """
    # 1) recupera il documento atomic
    doc = atomic_services_collection.find_one({"task_id": service_id}, {"_id": 0})
    if not doc:
        return {"status": "error", "errors": [f"Atomic service '{service_id}' not found"]}

    # 2) calcola la prossima versione (patch) guardando le versioni "published"
    latest = _latest_published_version("atomic", "service_id", service_id)
    version = _next_patch(latest)

    # 3) genera OAS
    oas = OpenAPIGenerator.generate_atomic_openapi(doc, version=version)
    if servers:
        oas["servers"] = servers

    # 4) valida OAS 3.1
    ok, errors = validate_openapi(oas)
    if not ok:
        return {"status": "error", "errors": errors}

    # 5) salva su collection openapi
    openapi_collection.insert_one({
        "level": "atomic",
        "service_id": service_id,
        "version": version,
        "status": "published",
        "oas": oas
    })

    return {"status": "ok", "version": version}

def republish_atomic_spec(service_id: str, servers: list|None=None) -> dict:
    """
    Pubblica una nuova versione della OAS per un atomic già presente.
    Versione = latest patch + 1 (o 1.0.0 se non esiste nulla).
    """
    atomic = atomic_services_collection.find_one({"task_id": service_id})
    if not atomic:
        return {"status": "error", "detail": "Atomic not found"}

    base = _latest_published_version(service_id)
    version = _bump_patch(base)

    oas = OpenAPIGenerator.generate_atomic_openapi(atomic, version=version)
    if servers:
        oas["servers"] = servers

    ok, errs = validate_openapi(oas)
    if not ok:
        return {"status": "error", "errors": errs}

    openapi_collection.insert_one({
        "level": "atomic",
        "service_id": service_id,
        "diagram_id": atomic.get("diagram_id"),
        "owner": atomic.get("owner"),
        "name": atomic.get("name"),
        "version": version,
        "status": "published",
        "hash": _sha256(oas),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "oas": oas,
        "meta": {"source": "generator", "tags": []}
    })
    return {"status": "ok", "service_id": service_id, "version": version}

# Versioning CPPS
# ------------------------------------------------------------
def _latest_published_cpps_version(group_id: str) -> Optional[str]:
    cur = openapi_collection.find(
        {"level": "cpps", "group_id": group_id, "status": "published"},
        {"version": 1, "_id": 0}
    )
    best_v, best_t = None, (-1, -1, -1)
    for d in cur:
        v = d.get("version")
        if not v:
            continue
        t = _parse_semver(v)
        if t > best_t:
            best_t, best_v = t, v
    return best_v

# ------------------------------------------------------------
# Upsert documento CPPS (Mongo: cpps_collection)
# ------------------------------------------------------------
def upsert_cpps(doc: dict) -> dict:
    """
    Allinea/salva il documento CPPS in cpps_collection.
    """
    cpps_collection.update_one(
        {"group_id": doc["group_id"]},
        {
            "$set": {
                "diagram_id": doc["diagram_id"],
                "name": doc["name"],
                "description": doc.get("description"),
                "owner": doc["owner"],
                "group_type": doc.get("group_type", "CPPS"),
                "components": doc.get("components", []),
                "workflow": doc.get("workflow", {}),
                "workflow_type": doc.get("workflow_type", "sequence"),
                "endpoints": doc.get("endpoints", []),
                "updated_at": _now_iso(),
            },
            "$setOnInsert": {"created_at": _now_iso()},
        },
        upsert=True,
    )
    # torna il doc senza _id per uso immediato
    return cpps_collection.find_one({"group_id": doc["group_id"]}, {"_id": 0})

# ------------------------------------------------------------
# Publish / Republish CPPS OpenAPI (openapi_collection)
# ------------------------------------------------------------
def publish_cpps_spec(group_id: str, servers: list | None = None) -> dict:
    """
    Genera OpenAPI 3.1 per il CPPS e la salva in openapi_collection con status=published.
    Versioning: patch bump su latest.
    """
    cpps = cpps_collection.find_one({"group_id": group_id})
    if not cpps:
        return {"status": "error", "detail": "CPPS not found"}

    base = _latest_published_cpps_version(group_id)
    version = _bump_patch(base)

    # Genera OAS
    oas = OpenAPIGenerator.generate_cpps_openapi(cpps, version=version)
    if servers:
        oas["servers"] = servers

    # Valida
    ok, errs = validate_openapi(oas)
    if not ok:
        return {"status": "error", "errors": errs}

    # Persisti OAS
    openapi_collection.insert_one({
        "level": "cpps",
        "group_id": group_id,
        "diagram_id": cpps.get("diagram_id"),
        "owner": cpps.get("owner"),
        "name": cpps.get("name"),
        "version": version,
        "status": "published",
        "hash": _sha256(oas),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "oas": oas,
        "meta": {"source": "generator", "tags": []},
    })

    return {"status": "ok", "group_id": group_id, "version": version}

def republish_cpps_spec(group_id: str, servers: list | None = None) -> dict:
    """
    Per semplicità, republish = nuova publish con patch bump (come atomic).
    """
    return publish_cpps_spec(group_id, servers=servers)


def upsert_cppn(data: dict) -> dict:
    # upsert by group_id
    cppn_collection.update_one(
        {"group_id": data["group_id"]},
        {"$set": data, "$setOnInsert": {"group_type": "CPPN"}},
        upsert=True
    )
    return cppn_collection.find_one({"group_id": data["group_id"]}, {"_id":0})

def _next_patch(version: str | None) -> str:
    if not version: return "1.0.0"
    try:
        M,m,p = [int(x) for x in version.split(".")]
        return f"{M}.{m}.{p+1}"
    except:
        return "1.0.0"

def _latest_published_version(level: str, ident_key: str, ident_val: str) -> str | None:
    cur = openapi_collection.find(
        {"level": level, ident_key: ident_val, "status":"published"},
        {"_id":0,"version":1}
    )
    best, best_t = None, (-1,-1,-1)
    for d in cur:
        try:
            t = tuple(int(x) for x in (d.get("version") or "0.0.0").split("."))
        except:
            t = (0,0,0)
        if t > best_t: best_t, best = t, d.get("version")
    return best

def publish_cppn_spec(group_id: str, servers: list[dict] | None = None) -> dict:
    doc = cppn_collection.find_one({"group_id": group_id}, {"_id":0})
    if not doc:
        return {"status":"error","errors":["CPPN not found"]}

    latest = _latest_published_version("cppn","group_id",group_id)
    version = _next_patch(latest)

    oas = OpenAPIGenerator.generate_cppn_openapi(doc, version=version)
    if servers:
        oas["servers"] = servers

    ok, errors = validate_openapi(oas)
    if not ok:
        return {"status":"error","errors": errors}

    openapi_collection.insert_one({
        "level":"cppn",
        "group_id": group_id,
        "version": version,
        "status":"published",
        "oas": oas
    })
    return {"status":"ok","version": version}