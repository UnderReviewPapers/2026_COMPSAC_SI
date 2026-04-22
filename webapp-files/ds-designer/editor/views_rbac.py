from utilities.mongodb_handler import rbac_collection, bpmn_collection
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import render
from datetime import datetime
from bson import ObjectId
from bson import ObjectId, errors as bson_errors

@api_view(['GET'])
def get_diagram_atomic_rbac(request):
    """
    GET /api/rbac/policies/atomic/by-diagram?id=<diagram_id>
    Returns atomic RBAC policies filtered by diagram_id.
    """
    diagram_id = request.query_params.get("id")
    if not diagram_id:
        return Response(
            {"detail": "Parametro 'id' (diagram_id) obbligatorio."},
            status=status.HTTP_400_BAD_REQUEST
        )

    query = {
        "diagram_id": diagram_id,
        "service_type": "atomic"
    }

    cursor = rbac_collection.find(query)

    results = []
    for doc in cursor:
        doc["_id"] = str(doc["_id"])
        results.append(doc)

    return Response({
        "count": len(results),
        "results": results
    }, status=status.HTTP_200_OK)

def rbac_atomic_view(request):
    return render(request, "editor/rbac_atomic.html")

def rbac_atomic_edit(request, atomic_id):

    return render(request, "editor/rbac_atomic_edit.html", {"atomic_id": atomic_id, "diagram_id": request.GET.get("id")})

def rbac_cpps_edit(request, cpps_id):
    return render(request, "editor/rbac_cpps_edit.html", {"cpps_id": cpps_id, "diagram_id": request.GET.get("id")})


def _sanitize(doc: dict) -> dict:
    if not doc:
        return doc
    d = dict(doc)
    if "_id" in d:
        d["_id"] = str(d["_id"])
    return d

@api_view(["GET"])
def get_atomic_policy_by_atomic_id(request):
    """
    GET /editor/api/rbac/policies/atomic/by-id?atomic_id=Activity_1u1y293[&diagram_id=...]
    Ritorna il documento RBAC (service_type=atomic) con quell'atomic_id.
    Se diagram_id è passato, filtra anche su quello.
    """
    atomic_id = request.query_params.get("atomic_id")
    if not atomic_id:
        return Response(
            {"detail": "Parametro 'atomic_id' obbligatorio."},
            status=status.HTTP_400_BAD_REQUEST
        )

    q = {"service_type": "atomic", "atomic_id": atomic_id}
    diagram_id = request.query_params.get("diagram_id")
    if diagram_id:
        q["diagram_id"] = diagram_id

    doc = rbac_collection.find_one(q)
    if not doc:
        return Response({"detail": "Policy non trovata."}, status=status.HTTP_404_NOT_FOUND)

    payload = _sanitize(doc)

    # --- aggiungi diagram_name se possibile ---
    if diagram_id:
        try:
            d = bpmn_collection.find_one({"_id": ObjectId(diagram_id)}, {"name": 1})
        except bson_errors.InvalidId:
            d = bpmn_collection.find_one({"_id": diagram_id}, {"name": 1})
        if d:
            payload["diagram_name"] = d.get("name")

    # opzionale: coerenza nei nomi
    if payload.get("service_name"):
        payload["atomic_name"] = payload["service_name"]

    return Response(payload, status=status.HTTP_200_OK)



@api_view(["GET"])
def get_diagram_actors(request):
    """
    GET /editor/api/actors?diagram_id=<id>
    Ritorna l'insieme (ordinato) degli attori del diagramma, basato SOLO su owner
    dei documenti RBAC atomic.
    """
    diagram_id = request.query_params.get("diagram_id") or request.query_params.get("id")
    if not diagram_id:
        return Response({"detail": "Parametro 'diagram_id' (o 'id') obbligatorio."},
                        status=status.HTTP_400_BAD_REQUEST)

    query = {"diagram_id": diagram_id, "service_type": "atomic"}
    projection = {"_id": 0, "owner": 1}

    actors = { (doc.get("owner") or "").strip()
               for doc in rbac_collection.find(query, projection)
               if (doc.get("owner") or "").strip() }

    return Response({
        "diagram_id": diagram_id,
        "count": len(actors),
        "actors": sorted(actors)
    }, status=status.HTTP_200_OK)


def _stringify_ids(d):
    if isinstance(d, list):
        return [_stringify_ids(x) for x in d]
    if isinstance(d, dict):
        out = {}
        for k, v in d.items():
            if isinstance(v, ObjectId):
                out[k] = str(v)
            else:
                out[k] = _stringify_ids(v)
        return out
    return d

@api_view(["PUT"])
def update_atomic_permissions(request):
    """
    PUT /editor/api/rbac/policies/atomic/permissions
    Body JSON:
    {
      "diagram_id": "...",          # obbligatorio
      "atomic_id": "...",           # obbligatorio
      "permission_actors": ["A1","A2"]  # opzionale: attori extra (≠ owner) con invoke
    }
    - Aggiorna SOLO le permissions del documento (owner resta invoke).
    - 404 se il documento non esiste.
    """
    body = request.data if isinstance(request.data, dict) else {}
    diagram_id = str(body.get("diagram_id", "")).strip()
    atomic_id  = str(body.get("atomic_id", "")).strip()
    if not diagram_id or not atomic_id:
        return Response({"detail": "diagram_id e atomic_id sono obbligatori."},
                        status=status.HTTP_400_BAD_REQUEST)

    # Recupera doc esistente (obbligatorio)
    filt = {"diagram_id": diagram_id, "atomic_id": atomic_id, "service_type": "atomic"}
    doc = rbac_collection.find_one(filt, {"owner": 1, "_id": 0})
    if not doc:
        return Response({"detail": "Policy non trovata."}, status=status.HTTP_404_NOT_FOUND)
    owner = (doc.get("owner") or "").strip()

    # Normalizza attori extra
    raw = body.get("permission_actors") or []
    if not isinstance(raw, list):
        return Response({"detail": "permission_actors deve essere una lista."},
                        status=status.HTTP_400_BAD_REQUEST)

    seen = set()
    extra = []
    for a in raw:
        a = str(a or "").strip()
        if not a or a == owner:
            continue
        k = a.lower()
        if k in seen:  # unici case-insensitive
            continue
        seen.add(k)
        extra.append(a)

    new_permissions = [{"actor": owner, "permission": "invoke"}] + [
        {"actor": a, "permission": "invoke"} for a in extra
    ]

    rbac_collection.update_one(
        filt,
        {"$set": {"permissions": new_permissions, "updated_at": datetime.utcnow()}}
    )
    out = rbac_collection.find_one(filt)

    # --- SYNC CPPN overlay ---
    # calcolo lista finale degli attori con invoke su questo atomic (owner + extra)
    actors_invoke = sorted({owner, *extra} - {""})
    sync_summary = sync_cppn_on_service_change(
        diagram_id=diagram_id,
        service_id=atomic_id,
        actors_invoke=actors_invoke
    )

    return Response({"status": "permissions_updated", 
                     "result": _stringify_ids(out),
                     "cppn_sync" : sync_summary},
                    status=status.HTTP_200_OK)

@api_view(["GET"])
def get_cpps_by_diagram(request):
    """
    GET /editor/api/rbac/policies/cpps/by-diagram?id=<diagram_id>
    Ritorna i documenti RBAC CPPS del diagram, arricchiti con 'service_name'
    in ogni permission, sia per Activity_* (atomic) sia per Group_* (cpps).
    """
    diagram_id = request.query_params.get("id")
    if not diagram_id:
        return Response({"detail": "diagram_id is mandatory."},
                        status=status.HTTP_400_BAD_REQUEST)

    # Carico i doc CPPS RBAC
    q = {"diagram_id": diagram_id, "service_type": "cpps"}
    docs = list(rbac_collection.find(q))

    #Raccolta tutti i service_id che compaiono nelle permissions
    service_ids = set()
    for d in docs:
        for p in (d.get("permissions") or []):
            sid = (p.get("service") or "").strip()
            if sid:
                service_ids.add(sid)

    # Short-circuit: se non ci sono service id, ritorno subito
    if not service_ids:
        return Response({"count": len(docs), "results": _stringify_ids(docs)}, status=200)

    #Costruisco una mappa ID -> name risolvendo prima da RBAC (atomic, cpps),
    #    poi dalle collection funzionali come fallback.
    name_map: dict[str, str] = {}

    #Risoluzione nomi da RBAC ATOMIC (atomic_id -> service_name)
    atomic_cursor = rbac_collection.find(
        {"diagram_id": diagram_id, "service_type": "atomic", "atomic_id": {"$in": list(service_ids)}},
        {"atomic_id": 1, "service_name": 1, "_id": 0}
    )
    for a in atomic_cursor:
        name_map[a["atomic_id"]] = a.get("service_name") or a["atomic_id"]

    #Risoluzione nomi da RBAC CPPS (cpps_id -> service_name), per i Group_*
    cpps_cursor = rbac_collection.find(
        {"diagram_id": diagram_id, "service_type": "cpps", "cpps_id": {"$in": list(service_ids)}},
        {"cpps_id": 1, "service_name": 1, "_id": 0}
    )
    for c in cpps_cursor:
        name_map[c["cpps_id"]] = c.get("service_name") or c["cpps_id"]

    #Fallback: collezioni funzionali se qualche ID non è ancora risolto
    missing = service_ids - set(name_map.keys())
    if missing:
        from utilities.mongodb_handler import atomic_services_collection, cpps_collection
        cur_a = atomic_services_collection.find(
            {"diagram_id": diagram_id, "task_id": {"$in": list(missing)}},
            {"task_id": 1, "name": 1, "_id": 0}
        )
        for a in cur_a:
            name_map[a["task_id"]] = a.get("name") or a["task_id"]

        # cpps collection (group_id -> name)
        still = missing - set(name_map.keys())
        if still:
            cur_c = cpps_collection.find(
                {"diagram_id": diagram_id, "group_id": {"$in": list(still)}},
                {"group_id": 1, "name": 1, "_id": 0}
            )
            for c in cur_c:
                name_map[c["group_id"]] = c.get("name") or c["group_id"]

    enriched = []
    for d in docs:
        dd = _stringify_ids(d)
        for p in (dd.get("permissions") or []):
            sid = (p.get("service") or "").strip()
            if sid:
                p["service_name"] = name_map.get(sid, sid)  # fallback all'ID
        enriched.append(dd)

    return Response({"count": len(enriched), "results": enriched}, status=200)


@api_view(["GET"])
def get_cpps_one(request):
    diagram_id = request.query_params.get("diagram_id")
    cpps_id    = request.query_params.get("cpps_id")
    if not diagram_id or not cpps_id:
        return Response({"detail": "diagram_id e cpps_id sono obbligatori."}, status=400)

    q = {"diagram_id": diagram_id, "cpps_id": cpps_id, "service_type": "cpps"}
    doc = rbac_collection.find_one(q)
    if not doc:
        return Response({"detail": "Policy non trovata."}, status=404)

    # --- lookup nome diagramma ---
    diagram_name = None
    try:
        d = bpmn_collection.find_one({"_id": ObjectId(diagram_id)}, {"name": 1})
    except bson_errors.InvalidId:
        d = bpmn_collection.find_one({"_id": diagram_id}, {"name": 1})
    if d:
        diagram_name = d.get("name")

    payload = _stringify_ids(doc)
    try:
        payload["diagram_id"] = str(ObjectId(diagram_id))
    except bson_errors.InvalidId:
        payload["diagram_id"] = str(diagram_id)
    if diagram_name:
        payload["diagram_name"] = diagram_name
    if payload.get("service_name"):
        payload["cpps_name"] = payload["service_name"]

    # ---risolti i nomi delle attività/servizi del CPPS (atomic + cpps annidati) ---
    services_ids = sorted({(p.get("service") or "").strip()
                           for p in (doc.get("permissions") or [])
                           if (p.get("service") or "").strip()})
    services_resolved = []
    if services_ids:
        name_map = {}

        # Atomic da RBAC
        cursor_a = rbac_collection.find(
            {"diagram_id": diagram_id, "service_type": "atomic", "atomic_id": {"$in": services_ids}},
            {"atomic_id": 1, "service_name": 1, "_id": 0}
        )
        for d in cursor_a:
            name_map[d["atomic_id"]] = d.get("service_name") or d["atomic_id"]

        # CPPS annidati da RBAC
        cursor_c = rbac_collection.find(
            {"diagram_id": diagram_id, "service_type": "cpps", "cpps_id": {"$in": services_ids}},
            {"cpps_id": 1, "service_name": 1, "_id": 0}
        )
        for d in cursor_c:
            name_map[d["cpps_id"]] = d.get("service_name") or d["cpps_id"]

        # Fallback: collezioni funzionali
        from utilities.mongodb_handler import atomic_services_collection, cpps_collection
        missing = set(services_ids) - set(name_map.keys())

        if missing:
            cur_a = atomic_services_collection.find(
                {"diagram_id": diagram_id, "task_id": {"$in": list(missing)}},
                {"task_id": 1, "name": 1, "_id": 0}
            )
            for a in cur_a:
                name_map[a["task_id"]] = a.get("name") or a["task_id"]

        still = set(services_ids) - set(name_map.keys())
        if still:
            cur_c = cpps_collection.find(
                {"diagram_id": diagram_id, "group_id": {"$in": list(still)}},
                {"group_id": 1, "name": 1, "_id": 0}
            )
            for c in cur_c:
                name_map[c["group_id"]] = c.get("name") or c["group_id"]

        for sid in services_ids:
            services_resolved.append({
                "service_id": sid,
                "service_name": name_map.get(sid, sid)
            })

    payload["services_resolved"] = services_resolved
    return Response(payload, status=200)


@api_view(["PUT"])
def update_cpps_permissions(request):
    """
    PUT /editor/api/rbac/policies/cpps/permissions
    Body JSON:
    {
      "diagram_id": "...",             # obbligatorio
      "cpps_id": "...",                # obbligatorio
      "permission_actors": ["A1","A2"] # attori extra (≠ owner) a cui dare invoke
    }

    Logica:
    - Carica il doc RBAC del CPPS. Se non esiste -> 404.
    - Ricava l'insieme delle activities del CPPS: unione dei campi 'service'
      presenti nelle permissions esistenti (tipicamente quelle dell'owner).
    - Ricostruisce completamente 'permissions' del CPPS come:
        owner → invoke su TUTTE le service
        per ogni actor in permission_actors → invoke su TUTTE le service
    - Propaga l'aggiornamento ai documenti CPPN del DIAGRAM che referenziano questo CPPS:
        (actor, service=cpps_id, 'invoke') solo per gli attori correnti (owner + extra).
      (overlay pulito: nessuna tupla 'none')
    """
    body = request.data if isinstance(request.data, dict) else {}
    diagram_id = (body.get("diagram_id") or "").strip()
    cpps_id    = (body.get("cpps_id") or "").strip()
    if not diagram_id or not cpps_id:
        return Response({"detail": "diagram_id e cpps_id sono obbligatori."}, status=status.HTTP_400_BAD_REQUEST)

    q = {"diagram_id": diagram_id, "cpps_id": cpps_id, "service_type": "cpps"}
    doc = rbac_collection.find_one(q, {"_id": 0})
    if not doc:
        return Response({"detail": "Policy not found."}, status=status.HTTP_404_NOT_FOUND)

    owner = (doc.get("owner") or "").strip()
    perms = doc.get("permissions") or []
    # ricava l’insieme delle activities del CPPS
    services = sorted({(p.get("service") or "").strip() for p in perms if (p.get("service") or "").strip()})

    # normalizza attori extra
    raw_extra = body.get("permission_actors") or []
    if not isinstance(raw_extra, list):
        return Response({"detail": "permission_actors deve essere una lista."}, status=status.HTTP_400_BAD_REQUEST)

    seen = set()
    extra = []
    for a in raw_extra:
        a = (a or "").strip()
        if not a or a.lower() == owner.lower():
            continue
        k = a.lower()
        if k in seen:
            continue
        seen.add(k)
        extra.append(a)

    new_permissions = []
    if services:
        for s in services:
            new_permissions.append({"actor": owner, "service": s, "permission": "invoke"})
            for a in extra:
                new_permissions.append({"actor": a, "service": s, "permission": "invoke"})
    else:
        new_permissions = []

    rbac_collection.update_one(q, {"$set": {"permissions": new_permissions, "updated_at": datetime.utcnow()}})
    out = rbac_collection.find_one(q)

    # lista finale attori con invoke sul CPPS (owner + extra)
    actors_invoke = sorted({owner, *extra} - {""})
    cppn_sync = sync_cppn_on_service_change(
        diagram_id=diagram_id,
        service_id=cpps_id,
        actors_invoke=actors_invoke
    )

    return Response({
        "status": "permissions_updated",
        "result": _stringify_ids(out),
        "cppn_sync": cppn_sync
    }, status=status.HTTP_200_OK)

def rbac_cpps_view(request):
    return render(request, "editor/rbac_cpps.html")

def rbac_cppn_view(request):
    """
    Landing/lista CPPN Policies per un dato diagram_id (passato in querystring ?id=...).
    """
    return render(request, "editor/rbac_cppn.html")

@api_view(["GET"])
def get_cppn_by_diagram(request):
    diagram_id = request.query_params.get("id")
    if not diagram_id:
        return Response({"detail": "diagram_id is mandatory."}, status=400)

    q = {"diagram_id": diagram_id, "service_type": "cppn"}
    docs = list(rbac_collection.find(q))

    service_ids = set()
    for d in docs:
        for p in d.get("permissions", []):
            sid = (p.get("service") or "").strip()
            if sid:
                service_ids.add(sid)

    name_map = {}
    # atomic
    cur_a = rbac_collection.find(
        {"diagram_id": diagram_id, "service_type": "atomic", "atomic_id": {"$in": list(service_ids)}},
        {"atomic_id": 1, "service_name": 1, "_id": 0}
    )
    for a in cur_a:
        name_map[a["atomic_id"]] = a.get("service_name") or a["atomic_id"]

    # cpps
    cur_c = rbac_collection.find(
        {"diagram_id": diagram_id, "service_type": "cpps", "cpps_id": {"$in": list(service_ids)}},
        {"cpps_id": 1, "service_name": 1, "_id": 0}
    )
    for c in cur_c:
        name_map[c["cpps_id"]] = c.get("service_name") or c["cpps_id"]

    # fallback (se vuoi, atomic_services_collection e cpps_collection come in get_cpps_by_diagram)

    enriched = []
    for d in docs:
        dd = _stringify_ids(d)
        for p in dd.get("permissions", []):
            sid = (p.get("service") or "").strip()
            if sid:
                p["service_name"] = name_map.get(sid, sid)
        enriched.append(dd)

    return Response({"count": len(enriched), "results": enriched}, status=200)



def rbac_cppn_edit(request, cppn_id):
    return render(request, "editor/rbac_cppn_edit.html", {
        "cppn_id": cppn_id,
        "diagram_id": request.GET.get("id"),
    })

@api_view(["GET"])
def get_cppn_one(request):
    """
    GET /editor/api/rbac/policies/cppn/one?diagram_id=...&cppn_id=...
    Restituisce il doc CPPN con nomi servizi risolti e metadati per l'edit.
    """
    diagram_id = request.query_params.get("diagram_id")
    cppn_id    = request.query_params.get("cppn_id")
    if not diagram_id or not cppn_id:
        return Response({"detail": "diagram_id e cppn_id sono obbligatori."}, status=400)

    q = {"diagram_id": diagram_id, "cppn_id": cppn_id, "service_type": "cppn"}
    doc = rbac_collection.find_one(q)
    if not doc:
        return Response({"detail": "Policy CPPN non trovata."}, status=404)

    # Nome diagramma
    diagram_name = None
    try:
        d = bpmn_collection.find_one({"_id": ObjectId(diagram_id)}, {"name": 1})
    except bson_errors.InvalidId:
        d = bpmn_collection.find_one({"_id": diagram_id}, {"name": 1})
    if d:
        diagram_name = d.get("name")

    payload = _stringify_ids(doc)
    if diagram_name:
        payload["diagram_name"] = diagram_name
    if payload.get("service_name"):
        payload["cppn_name"] = payload["service_name"]

    # Servizi membri del CPPN (da members, se c'è; altrimenti dalle permissions)
    svc_ids = set(payload.get("members") or [])
    if not svc_ids:
        for p in (doc.get("permissions") or []):
            sid = (p.get("service") or "").strip()
            if sid: svc_ids.add(sid)

    # Risoluzione nomi (atomic + cpps)
    services_resolved = []
    if svc_ids:
        name_map = {}

        # atomic in RBAC
        cur_a = rbac_collection.find(
            {"diagram_id": diagram_id, "service_type":"atomic", "atomic_id": {"$in": list(svc_ids)}},
            {"atomic_id": 1, "service_name": 1, "_id": 0}
        )
        for a in cur_a:
            name_map[a["atomic_id"]] = a.get("service_name") or a["atomic_id"]

        # cpps in RBAC
        cur_c = rbac_collection.find(
            {"diagram_id": diagram_id, "service_type":"cpps", "cpps_id": {"$in": list(svc_ids)}},
            {"cpps_id": 1, "service_name": 1, "_id": 0}
        )
        for c in cur_c:
            name_map[c["cpps_id"]] = c.get("service_name") or c["cpps_id"]

        # fallback (opzionale) su collezioni funzionali come fatto per i CPPS

        for sid in sorted(svc_ids):
            services_resolved.append({
                "service_id": sid,
                "service_name": name_map.get(sid, sid)
            })

    payload["services_resolved"] = services_resolved
    return Response(payload, status=200)

@api_view(["GET"])
def get_cppn_one(request):
    """
    GET /editor/api/rbac/policies/cppn/one?diagram_id=...&cppn_id=...
    Restituisce il doc CPPN con nomi servizi risolti e metadati per l'edit.
    """
    diagram_id = request.query_params.get("diagram_id")
    cppn_id    = request.query_params.get("cppn_id")
    if not diagram_id or not cppn_id:
        return Response({"detail": "diagram_id e cppn_id sono obbligatori."}, status=400)

    q = {"diagram_id": diagram_id, "cppn_id": cppn_id, "service_type": "cppn"}
    doc = rbac_collection.find_one(q)
    if not doc:
        return Response({"detail": "Policy CPPN non trovata."}, status=404)

    # Nome diagramma
    diagram_name = None
    try:
        d = bpmn_collection.find_one({"_id": ObjectId(diagram_id)}, {"name": 1})
    except bson_errors.InvalidId:
        d = bpmn_collection.find_one({"_id": diagram_id}, {"name": 1})
    if d:
        diagram_name = d.get("name")

    payload = _stringify_ids(doc)
    if diagram_name:
        payload["diagram_name"] = diagram_name
    if payload.get("service_name"):
        payload["cppn_name"] = payload["service_name"]

    # Servizi membri del CPPN (da members, se c'è; altrimenti dalle permissions)
    svc_ids = set(payload.get("members") or [])
    if not svc_ids:
        for p in (doc.get("permissions") or []):
            sid = (p.get("service") or "").strip()
            if sid: svc_ids.add(sid)

    # Risoluzione nomi (atomic + cpps)
    services_resolved = []
    if svc_ids:
        name_map = {}

        # atomic in RBAC
        cur_a = rbac_collection.find(
            {"diagram_id": diagram_id, "service_type":"atomic", "atomic_id": {"$in": list(svc_ids)}},
            {"atomic_id": 1, "service_name": 1, "_id": 0}
        )
        for a in cur_a:
            name_map[a["atomic_id"]] = a.get("service_name") or a["atomic_id"]

        # cpps in RBAC
        cur_c = rbac_collection.find(
            {"diagram_id": diagram_id, "service_type":"cpps", "cpps_id": {"$in": list(svc_ids)}},
            {"cpps_id": 1, "service_name": 1, "_id": 0}
        )
        for c in cur_c:
            name_map[c["cpps_id"]] = c.get("service_name") or c["cpps_id"]

        # fallback (opzionale) su collezioni funzionali come fatto per i CPPS

        for sid in sorted(svc_ids):
            services_resolved.append({
                "service_id": sid,
                "service_name": name_map.get(sid, sid)
            })

    payload["services_resolved"] = services_resolved
    return Response(payload, status=200)


def _S(x):
    if isinstance(x, list):  return [_S(v) for v in x]
    if isinstance(x, dict):  return {k: _S(v) for k,v in x.items()}
    if isinstance(x, ObjectId): return str(x)
    return x

def _unique(seq):
    seen=set()
    out=[]
    for v in seq:
        if v not in seen:
            seen.add(v); out.append(v)
    return out

def _service_name(doc, sid):
    # preferisci il campo service_name se c'è; fallback all'id
    return (doc or {}).get("service_name") or sid

@api_view(["GET"])
def get_cppn_services(request):
    """
    GET /editor/api/rbac/policies/cppn/services?diagram_id=...&cppn_id=...

    Ritorna:
    {
      "count": N,
      "results": [
        {
          "service_id": "Activity_...",
          "service_type": "atomic" | "cpps",
          "service_name": "Human readable name",
          "actors_invoke": ["Actor A","Actor B"]
        }, ...
      ]
    }
    """
    diagram_id = (request.query_params.get("diagram_id") or request.query_params.get("id") or "").strip()
    cppn_id    = (request.query_params.get("cppn_id") or "").strip()
    if not diagram_id or not cppn_id:
        return Response({"detail": "diagram_id e cppn_id obbligatori."}, status=status.HTTP_400_BAD_REQUEST)

    cppn = rbac_collection.find_one({"diagram_id": diagram_id, "service_type": "cppn", "cppn_id": cppn_id})
    if not cppn:
        return Response({"detail": "Policy CPPN non trovata."}, status=status.HTTP_404_NOT_FOUND)

    # membri: se hai un campo 'members' usalo; altrimenti derivali dalle permissions del CPPN
    members = set()
    if isinstance(cppn.get("members"), list) and cppn["members"]:
        members = set(cppn["members"])
    else:
        for p in (cppn.get("permissions") or []):
            sid = (p.get("service") or "").strip()
            if sid: members.add(sid)

    results = []
    for sid in sorted(members):
        # prova atomic
        atomic = rbac_collection.find_one({"diagram_id": diagram_id, "service_type":"atomic", "atomic_id": sid})
        cpps   = None
        stype  = "atomic" if atomic else "cpps"
        if not atomic:
            cpps = rbac_collection.find_one({"diagram_id": diagram_id, "service_type":"cpps", "cpps_id": sid})

        base_doc = atomic or cpps or {}
        sname    = _service_name(base_doc, sid)

        # Attori con invoke a livello servizio (policy canonica del servizio)
        base_invoke = []
        for p in (base_doc.get("permissions") or []):
            if p.get("permission") == "invoke":
                a = (p.get("actor") or "").strip()
                if a: base_invoke.append(a)

        # Overlay CPPN (se presenti tuple invoke per questo service)
        overlay = []
        for p in (cppn.get("permissions") or []):
            if p.get("service") == sid and p.get("permission") == "invoke":
                a = (p.get("actor") or "").strip()
                if a: overlay.append(a)

        actors_invoke = _unique(base_invoke + overlay)

        results.append({
            "service_id": sid,
            "service_type": stype,
            "service_name": sname,
            "actors_invoke": actors_invoke,
        })

    return Response(_S({"count": len(results), "results": results}), status=status.HTTP_200_OK)

def rbac_cppn_services_view(request, cppn_id: str):
    # passa diagram_id (dalla query string) e il cppn_id al template
    return render(request, "editor/rbac_cppn_services.html", {
        "diagram_id": request.GET.get("id", ""),
        "cppn_id": cppn_id
    })


def sync_cppn_on_service_change(diagram_id: str, service_id: str, actors_invoke: list[str]) -> dict:
    """
    Propaga la modifica di permissions di un service (atomic/cpps) a TUTTI i doc CPPN del diagram:
    - rimuove dal CPPN tutte le tuple del service_id
    - reinserisce SOLO (actor, service_id, 'invoke') per gli attori passati
    - garantisce che members contenga service_id
    - aggiorna 'actors' (unione)
    Ritorna un piccolo summary.
    """
    # normalizza attori
    actors_invoke = sorted({(a or "").strip() for a in (actors_invoke or []) if a and a.strip()})

    # trova i CPPN del diagram che referenziano il service
    q = {
        "diagram_id": diagram_id,
        "service_type": "cppn",
        "$or": [
            {"members": service_id},
            {"permissions.service": service_id},
        ],
    }

    matched = 0
    modified = 0
    for doc in rbac_collection.find(q):
        matched += 1
        _id = doc["_id"]
        perms = doc.get("permissions") or []

        # 1) rimuovi tutte le tuple del service_id
        kept = [p for p in perms if p.get("service") != service_id]

        # 2) aggiungi le nuove tuple 'invoke'
        kept.extend({
            "actor": a,
            "service": service_id,
            "permission": "invoke"
        } for a in actors_invoke)

        # 3) assicura presence in 'members'
        members = set(doc.get("members") or [])
        members.add(service_id)

        # 4) aggiorna elenco actors = unione
        actors = set(doc.get("actors") or [])
        actors.update(actors_invoke)

        res = rbac_collection.update_one(
            {"_id": _id},
            {"$set": {
                "permissions": kept,
                "members": sorted(members),
                "actors": sorted(actors),
                "updated_at": datetime.utcnow()
            }}
        )
        modified += res.modified_count

    return {"matched_cppn": matched, "modified_cppn": modified}


@api_view(["PUT"])
def update_cppn_permissions(request):
    """
    PUT /editor/api/rbac/policies/cppn/permissions
    Body JSON:
    {
      "diagram_id": "...",             # obbligatorio
      "cppn_id": "...",                # obbligatorio
      "permission_actors": ["A1","A2"] # attori extra (≠ owner)
    }

    Ricostruisce le tuple (actor, service -> 'invoke') per TUTTI i servizi membri del CPPN.
    """
    body = request.data if isinstance(request.data, dict) else {}
    diagram_id = (body.get("diagram_id") or "").strip()
    cppn_id    = (body.get("cppn_id") or "").strip()
    if not diagram_id or not cppn_id:
        return Response({"detail": "diagram_id e cppn_id sono obbligatori."}, status=status.HTTP_400_BAD_REQUEST)

    q = {"diagram_id": diagram_id, "cppn_id": cppn_id, "service_type": "cppn"}
    doc = rbac_collection.find_one(q, {"_id": 0})
    if not doc:
        return Response({"detail": "Policy CPPN non trovata."}, status=status.HTTP_404_NOT_FOUND)

    owner = (doc.get("owner") or "").strip()

    # Membri: usa 'members' se presente, altrimenti derivali dalle permissions
    members = set(doc.get("members") or [])
    if not members:
        for p in (doc.get("permissions") or []):
            sid = (p.get("service") or "").strip()
            if sid: members.add(sid)
    members = sorted(members)

    # normalizza attori extra
    raw_extra = body.get("permission_actors") or []
    if not isinstance(raw_extra, list):
        return Response({"detail": "permission_actors deve essere una lista."}, status=status.HTTP_400_BAD_REQUEST)

    seen = set()
    extra = []
    for a in raw_extra:
        a = (a or "").strip()
        if not a or a.lower() == (owner or "").lower():
            continue
        k = a.lower()
        if k in seen:  # unici case-insensitive
            continue
        seen.add(k)
        extra.append(a)

    # ricostruisci permissions CPPN: owner + extras, su TUTTI i members
    new_permissions = []
    for s in members:
        if owner:
            new_permissions.append({"actor": owner, "service": s, "permission": "invoke"})
        for a in extra:
            new_permissions.append({"actor": a, "service": s, "permission": "invoke"})

    # aggiorna anche 'actors' (partecipanti)
    new_actors = sorted({*(doc.get("actors") or []), *(x for x in [owner, *extra] if x)})

    rbac_collection.update_one(
        q,
        {"$set": {
            "permissions": new_permissions,
            "actors": new_actors,
            "members": members,
            "updated_at": datetime.utcnow()
        }}
    )
    out = rbac_collection.find_one(q)

    return Response({"status": "permissions_updated", "result": _stringify_ids(out)}, status=status.HTTP_200_OK)
