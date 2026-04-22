import tempfile
import os
import json
import base64
from pathlib import Path
import io
import os
import zipfile
import tempfile
import shutil
import re
import prompt as prompt_module
from django.shortcuts import render
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from utilities.mongodb_handler import rbac_collection, atomic_services_collection, cpps_collection, cppn_collection, bpmn_collection, MongoDBHandler
from utilities.rbac import rbac
from django.utils.timezone import now
from rest_framework.response import Response
from django.http import JsonResponse, HttpResponse
from bson import ObjectId, json_util
from bson.errors import InvalidId
from utilities.helpers import detect_type
from openapi_docs.services import publish_atomic_spec, publish_cpps_spec, publish_cppn_spec
from openapi_docs.serializers import AtomicUpsertSerializer
from django.urls import reverse
from collections import OrderedDict
from utilities.mongodb_handler import openapi_collection
from .analysis import parser, gamma_algorithm
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from bpmn_to_laravel import (
    parse_bpmn,
    call_llm,
    clone_template_for_actors,
    write_actor_files,
    OUTPUT_ROOT,
)

def data_view_editor(request):
    return render(request, 'editor/view.html')

def rbac_policies_view(request):
    service_id = request.GET.get("id")
    return render(request, "editor/rbac.html", {"service_id": service_id})

def analyze_bpmn_view(request):
    if request.method == 'POST':
        try:
            # 1. Parsing Input JSON
            data = json.loads(request.body)
            bpmn_xml = data.get('bpmn_xml')
            if not bpmn_xml:
                return JsonResponse({'success': False, 'error': 'No BPMN data provided'})

            # 2. Creazione File Temporanei
            # bpmn_path: file XML originale
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xml', mode='w+', encoding='utf-8') as bpmn_file:
                bpmn_file.write(bpmn_xml)
                bpmn_path = bpmn_file.name
            
            txt_output_path = bpmn_path + ".txt"
            img1_path = bpmn_path + "_dendrogram.png"
            img2_path = bpmn_path + "_gamma.png"

            try:
                # 3. Esecuzione Parser (XML -> TXT)
                success_parser = parser.run_parser(bpmn_path, txt_output_path)
                if not success_parser:
                    raise Exception("Parser failed to generate text file.")

                # 4. Parsing tasks per passarli alla funzione
                with open(txt_output_path, "r", encoding="utf-8") as f:
                    text = f.read()
                as_entries = gamma_algorithm.parse_atomic_services(text)
                tasks_obj_list = gamma_algorithm.build_tasks(as_entries)

                # 5. Esecuzione Gamma Algorithm per generare le immagini (dendrogram e gamma trend)
                gamma_algorithm.generate_images(
                    txt_output_path, 
                    img1_path, 
                    img2_path,
                    original_bpmn_path=bpmn_path,
                    output_bpmn_path=None  # Non generiamo più un singolo XML ottimale
                )

                # 6. Genera TUTTI i variants (uno per ogni iterazione)
                variants, gamma_vals = gamma_algorithm.generate_all_bpmn_variants(
                    txt_output_path,
                    bpmn_path,
                    tasks_obj_list
                )

                if not variants:
                    raise Exception("No variants were generated.")

                def file_to_base64(path):
                    if not os.path.exists(path): return ""
                    with open(path, "rb") as f:
                        return base64.b64encode(f.read()).decode('utf-8')

                img1_b64 = file_to_base64(img1_path)
                img2_b64 = file_to_base64(img2_path)

                if not img1_b64 or not img2_b64:
                     raise Exception("Images were not generated successfully.")

                # Trova l'iterazione con gamma minimo
                min_gamma = min(gamma_vals)
                best_iteration = gamma_vals.index(min_gamma)

                return JsonResponse({
                    'success': True,
                    'image1': img1_b64,
                    'image2': img2_b64,
                    'variants': variants,  # Lista completa di tutti i variants
                    'best_iteration': best_iteration
                })

            finally:
                # 7. Pulizia File Temporanei
                files_to_clean = [bpmn_path, txt_output_path, img1_path, img2_path]
                for f in files_to_clean:
                    if os.path.exists(f):
                        try: os.remove(f)
                        except: pass

        except Exception as e:
            print(f"Error in analyze_bpmn_view: {e}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request method'})

def check_diagram_name(request):
    name = request.GET.get('name')
    if not name:
        return JsonResponse({'error': 'Missing name'}, status=400)

    # Confronto case-insensitive
    exists = bpmn_collection.find_one({ 'name': { '$regex': f'^{name}$', '$options': 'i' } }) is not None
    return JsonResponse({'exists': exists})

@api_view(['POST'])
def generate_laravel_projects(request):
    """Generate Laravel projects for the current diagram and return them as a ZIP.

    Steps (as in bpmn_to_laravel):
      1) parse_bpmn on the BPMN XML of the diagram
      2) prompt_module.build_best_prompt(parsed)
      3) call_llm(prompt)
      4) clone_template_for_actors(actors, session_dir)
      5) write_actor_files(actor_paths, actors)
    """
    diagram_id = request.data.get('diagram_id')
    if not diagram_id:
        return Response({'error': 'diagram_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        obj_id = ObjectId(diagram_id)
    except InvalidId:
        return Response({'error': 'Invalid diagram_id'}, status=status.HTTP_400_BAD_REQUEST)

    doc = bpmn_collection.find_one({'_id': obj_id})
    if not doc:
        return Response({'error': 'Diagram not found'}, status=status.HTTP_404_NOT_FOUND)

    xml_content = doc.get('xml_content')
    if not xml_content:
        return Response({'error': 'Diagram has no xml_content'}, status=status.HTTP_400_BAD_REQUEST)

    raw_name = doc.get('name') or f'diagram_{diagram_id}'
    safe_name = re.sub(r'[^a-zA-Z0-9_-]+', '_', raw_name).strip('_') or f'diagram_{diagram_id}'

    try:
        with tempfile.TemporaryDirectory() as tmpdir: 
            bpmn_path = Path(tmpdir) / 'diagram.bpmn'
            bpmn_path.write_text(xml_content, encoding='utf-8')
            print("=== PARSING BPMN ===")
            parsed = parse_bpmn(str(bpmn_path))

        prompt = prompt_module.build_best_prompt(parsed)

        print("=== CHIAMATA LLM ===")
        llm_result = call_llm(prompt)
        actors = llm_result.get('actors')
        if not isinstance(actors, list) or not actors:
            return Response({'error': 'LLM result does not contain a valid "actors" list'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        session_dir = OUTPUT_ROOT / safe_name
        actor_paths = clone_template_for_actors(actors, session_dir)

        write_actor_files(actor_paths, actors)


        print("=== CREAZIONE ZIP DEI PROGETTI ===")
        print("SESSION DIR:", session_dir)
        print("ESISTE?", session_dir.exists())
        memfile = io.BytesIO()

        EXCLUDE_DIRS = {"vendor","node_modules", ".git", "__pycache__"}

        with zipfile.ZipFile(memfile, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in session_dir.rglob("*"):
                if file.is_file() and not file.name.endswith(".zip"):
                    if any(part in EXCLUDE_DIRS for part in file.parts):
                        continue
                    arcname = file.relative_to(session_dir).as_posix()
                    print("ZIPPANDO:", file, "->", arcname)
                    zf.write(file, arcname)

        memfile.seek(0)
        response = HttpResponse(memfile.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{safe_name}.zip"'
        return response

    except Exception as exc:
        return Response({'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST', 'PUT', 'GET'])
def save_diagram(request, diagram_id=None):
    data = request.data

    if request.method == 'GET':
        try:
            object_id = ObjectId(diagram_id)
        except InvalidId:
            return Response({'error': 'Invalid ID'}, status=400)

        exists = bpmn_collection.find_one({'_id': object_id})
        if exists:
            return Response({'status': 'exists'})
        else:
            return Response({'error': 'Not found'}, status=404)

    if request.method == 'POST':
        diagram = {
            "name": data['name'],
            "xml_content": data['xml_content'],
            "created_at": now()
        }
        result = bpmn_collection.insert_one(diagram)
        return Response({'id': str(result.inserted_id), 'status': 'saved'})

    elif request.method == 'PUT':
        if not diagram_id:
            return Response({'error': 'Diagram ID is required'}, status=400)

        update_fields = {
            "xml_content": data['xml_content'],
            "updated_at": now()
        }

        if 'name' in data:
            update_fields['name'] = data['name']

        result = bpmn_collection.update_one(
            {"_id": ObjectId(diagram_id)},
            {"$set": update_fields}
        )

        if result.matched_count == 0:
            return Response({'error': 'Diagram not found'}, status=404)

        return Response({'id': diagram_id, 'status': 'updated'})

def parse_param_list(param_list):
    parsed = []
    for item in param_list:
        item = item.strip()
        if item == "":
            continue
        if item.isdigit():
            type_ = 'Int'
        else:
            try:
                float(item)
                type_ = 'Float'
            except ValueError:
                type_ = 'String'
        parsed.append({'name': item, 'type': type_})
    return parsed

@api_view(['POST'])
def save_atomic_service(request):
    data = request.data

    # Genera input/output tipizzati a partire da input_params/output_params
    data = dict(data)  # copiamo per sicurezza
    data['input'] = { str(v): detect_type(v) for v in data.get('input_params', []) }
    data['output'] = { str(v): detect_type(v) for v in data.get('output_params', []) }

    # Validazione schema (DRF) per evitare payload incompleti
    ser = AtomicUpsertSerializer(data={
        "diagram_id": data.get("diagram_id"),
        "task_id": data.get("task_id"),
        "name": data.get("name"),
        "atomic_type": data.get("atomic_type"),
        "method": data.get("method"),
        "url": data.get("url"),
        "owner": data.get("owner"),
        "input": data.get("input"),
        "output": data.get("output"),
    })
    ser.is_valid(raise_exception=True)

    # Salvataggio atomic nel DB
    result, status_code = MongoDBHandler.save_atomic({
        "diagram_id": data["diagram_id"],
        "task_id": data["task_id"],
        "name": data["name"],
        "atomic_type": data["atomic_type"],
        "method": data["method"],
        "url": data["url"],
        "owner": data["owner"],
        "input": data["input"],
        "output": data["output"],
    })

    # Se ok, pubblica la OpenAPI
    if status_code in (200, 201):
        servers = [{"url": request.build_absolute_uri("/").rstrip("/")}]
        pub_res = publish_atomic_spec(service_id=data["task_id"], servers=servers)

        json_url = reverse("openapi_docs:atomic-oas-latest", args=[data["task_id"]])
        swagger_url = reverse("openapi_docs:atomic-docs-latest", args=[data["task_id"]])
        
        rbac.atomic_policy(data)

        return Response({
            "status": "ok",
            "atomic_service": result,
            "openapi_publish": pub_res,
            "links": {"json": json_url, "swagger": swagger_url}
        }, status=status.HTTP_201_CREATED if status_code == 201 else status.HTTP_200_OK)

    return Response({
        "status": "error",
        "detail": "Atomic not saved, OpenAPI skipped",
        "atomic_service": result
    }, status=status_code)

@api_view(['POST'])
def save_cpps_service(request):
    data = request.data
    print("===CPPS Payload received:", data)

    # Estraggo componenti
    components = data.get('components', [])
    component_ids = [c['id'] for c in components if c['type'] == 'Atomic']
    cpps_ids = [c['id'] for c in components if c['type'] == 'CPPS']

    # Recupero documenti atomic e cpps annidati
    atomic_map = {
        a["task_id"]: a
        for a in atomic_services_collection.find({"task_id": {"$in": component_ids}})
    }

    cpps_map = {
        c["group_id"]: c
        for c in cpps_collection.find({"group_id": {"$in": cpps_ids}})
    }

    # Normalizza components e workflow
    data["components"], data["workflow"] = normalize_components_and_workflow(data, cpps_map)
    
    # Salva nel DB
    result, status_code = MongoDBHandler.save_cpps(data)

    if status_code in [200, 201]:
        # Genera e pubblica OpenAPI
        servers = [{"url": request.build_absolute_uri("/").rstrip("/")}]
        pub_res = publish_cpps_spec(group_id=data["group_id"], servers=servers)

        if pub_res.get("status") == "ok":
            doc_result, doc_status = pub_res, 201
            print("===OpenAPI doc published:", pub_res)
        else:
            doc_result, doc_status = {
                "message": "OpenAPI publish failed",
                "errors": pub_res.get("errors")
            }, 400
        #scrivo policy
        rbac.cpps_policy(data, component_ids, cpps_ids)

    else:
        doc_result, doc_status = {"message": "CPPS not saved, skipping OpenAPI"}, 400

    return Response({
        "cpps_service": result,
        "openapi_documentation": doc_result
    }, status=status_code)

def normalize_components_and_workflow(data, cpps_map):
    """
    Normalizza il CPPS esterno per avere un workflow del tipo:
      - Activity_esterna -> Group_interno
      - Group_interno   -> Activity_esterna
    Collassa qualsiasi nodo interno (Atomic o Gateway) al relativo group_id.
    NON risale oltre 1 livello di annidamento (voluto).
    """
    components = data.get('components', [])
    workflow = data.get('workflow', {})

    # id -> type (per riconoscere gateway/cpps)
    comp_type = {c["id"]: c["type"] for c in components}

    # ---- Indici 1-livello sui CPPS annidati ----
    # atomic interno -> group che lo contiene
    atomic_to_group = {}
    # nodo interno (atomic o gateway) -> group che lo contiene
    node_to_group = {}
    # per ogni group, insieme dei suoi id interni (atomic+gateway)
    group_inner = {}

    for comp in components:
        if comp.get("type") == "CPPS":
            gid = comp["id"]
            inner = set()
            nested = cpps_map.get(gid, {}).get("components", [])
            for c in nested:
                cid, ctype = c.get("id"), c.get("type")
                inner.add(cid)
                node_to_group[cid] = gid
                if ctype == "Atomic":
                    atomic_to_group[cid] = gid
            group_inner[gid] = inner

    nested_atomic_ids = set(atomic_to_group.keys())
    nested_internal_ids = set(node_to_group.keys())  # atomic + gateway interni

    # ---- Filtro componenti del CPPS esterno: rimuovi nodi interni (atomic/gateway) ----
    filtered_components = []
    for c in components:
        cid, ctype = c["id"], c["type"]
        # escludo tutto ciò che è interno a un CPPS annidato (tranne il CPPS stesso)
        if cid in nested_internal_ids and ctype != "CPPS":
            continue
        # escludo atomic duplicati interni
        if ctype == "Atomic" and cid in nested_atomic_ids:
            continue
        filtered_components.append(c)

    # ---- Costruisco workflow esterno con soli Activity->Group e Group->Activity ----
    mapped = OrderedDict()

    def add_edge(src, tgt, store=mapped):
        if src == tgt:
            return  # evita self-loop
        if src not in store:
            store[src] = []
        if tgt not in store[src]:
            store[src].append(tgt)

    for source, targets in workflow.items():
        if source in nested_internal_ids:
            # Sorgente interna (atomic/gateway di un CPPS): alza a group_id (uscita del CPPS)
            gid = node_to_group[source]
            inner = group_inner.get(gid, set())
            for t in targets:
                if t in inner:
                    continue  # interno->interno: non esce dal group
                # mappa target che è nodo interno di altri CPPS al relativo group
                t_mapped = node_to_group.get(t, atomic_to_group.get(t, t))
                if t_mapped == gid:
                    continue  # evita group -> group sullo stesso group
                add_edge(gid, t_mapped)
        else:
            # Sorgente esterna: ingresso nel CPPS (collassa target interni - atomic o gateway - al loro group)
            dedup = []
            for t in targets:
                t_mapped = node_to_group.get(t, atomic_to_group.get(t, t))
                if t_mapped != source and t_mapped not in dedup:
                    dedup.append(t_mapped)
            for t in dedup:
                add_edge(source, t)

    # ---- Compressione leggera di gateway ESTERNI lineari (pred -> gw -> unico tgt) ----
    predecessors = {}
    for s, tgts in mapped.items():
        for t in tgts:
            predecessors.setdefault(t, set()).add(s)

    compressed = OrderedDict()
    compressed_gateways = set()

    def add_c(src, tgt):
        add_edge(src, tgt, store=compressed)

    for src, tgts in mapped.items():
        is_gateway = comp_type.get(src, '').endswith('Gateway')
        if is_gateway:
            preds = list(predecessors.get(src, []))
            # uniq targets preservando l'ordine
            uniq_tgts = []
            for t in tgts:
                if t not in uniq_tgts:
                    uniq_tgts.append(t)
            # comprimi se c'è un solo predecessore e (dopo mapping) un solo target effettivo
            if len(preds) == 1 and len(set(uniq_tgts)) == 1:
                add_c(preds[0], uniq_tgts[0])
                compressed_gateways.add(src)
                continue
        # caso standard
        for t in tgts:
            add_c(src, t)

    # Rimuove i gateway compressi dai target
    if compressed_gateways:
        for s, tgts in list(compressed.items()):
            new_tgts = [t for t in tgts if t not in compressed_gateways]
            if new_tgts:
                compressed[s] = new_tgts
            else:
                del compressed[s]

    # ---------- FLATTEN: Group -> Atomic_interna_finale -> X  ==>  Group -> X ----------
    # Applica finché non ci sono più casi; copre fuga di un'Atomic finale marcata come sorgente.
    changed = True
    while changed:
        changed = False

        # ricalcola i predecessori sul grafo corrente
        predecessors = {}
        for s, tgts in compressed.items():
            for t in tgts:
                predecessors.setdefault(t, set()).add(s)

        to_delete_sources = set()
        updates = []  # (group, old_atomic_target, new_targets_list)

        for g, tgts in compressed.items():
            # considera solo sorgenti che sono group (CPPS)
            if g not in cpps_map:
                continue
            for a in list(tgts):
                # a) 'a' è un'Atomic
                # b) 'a' compare come sorgente
                # c) l'unico predecessore di 'a' è proprio 'g'
                if comp_type.get(a) == "Atomic" and a in compressed and predecessors.get(a, {None}) == {g}:
                    # sposta g->a->T su g->T (dedup, no self-loop)
                    new_targets = []
                    for t in compressed[a]:
                        if t != g and t not in tgts:
                            new_targets.append(t)
                    if new_targets:
                        updates.append((g, a, new_targets))
                        to_delete_sources.add(a)
                        changed = True

        # applica gli aggiornamenti raccolti
        for g, a, new_targets in updates:
            compressed[g] = [t for t in compressed[g] if t != a]
            for t in new_targets:
                if t not in compressed[g]:
                    compressed[g].append(t)

        # cancella le sorgenti appiattite
        for a in to_delete_sources:
            compressed.pop(a, None)

    # Purge finale: niente self-loop e niente entry vuote
    for s in list(compressed.keys()):
        compressed[s] = [t for t in compressed[s] if t != s]
        if not compressed[s]:
            del compressed[s]

    # ---- Risultato: Activity->Group e Group->Activity, senza leak di nodi interni ----
    return filtered_components, compressed

def normalize_cppn_components_and_workflow(
    data,
    cpps_map,
    *,
    compress_trivial_gateways: bool = False,
    boundary_only: bool = False,
):
    """
    CPPN normalize:
    - Mantiene i GATEWAY *esterni* (non interni a CPPS annidati).
    - Collassa qualsiasi nodo *interno* ai CPPS (Atomic o Gateway) al relativo group_id.
    - Opzioni:
        compress_trivial_gateways: comprime solo gateway esterni banali (1 pred -> gw -> 1 tgt)
        boundary_only: se True, tiene solo archi che toccano almeno un CPPS (group)
    """
    components = data.get("components", [])
    workflow   = data.get("workflow", {})

    # id -> type, set dei group (CPPS referenziati nel CPPN)
    comp_type = {c["id"]: c["type"] for c in components}
    groups    = {c["id"] for c in components if c.get("type") == "CPPS"}

    # ---- Indici 1-livello per i CPPS annidati ----
    # nodo interno (atomic o gateway) -> group che lo contiene
    node_to_group = {}
    # per ogni group, insieme dei suoi id interni
    group_inner = {}
    # atomic interni (utile per chiarezza; non indispensabile separatamente)
    nested_atomic_ids = set()

    for c in components:
        if c.get("type") == "CPPS":
            gid = c["id"]
            inner = set()
            nested = cpps_map.get(gid, {}).get("components", [])
            for n in nested:
                nid, ntype = n.get("id"), n.get("type")
                inner.add(nid)
                node_to_group[nid] = gid
                if ntype == "Atomic":
                    nested_atomic_ids.add(nid)
            group_inner[gid] = inner

    nested_internal_ids = set(node_to_group.keys())  # atomic + gateway interni

    # ---- Filtra i componenti del CPPN: rimuove solo i nodi interni ai CPPS ----
    filtered_components = []
    for c in components:
        cid, ctype = c["id"], c["type"]
        if cid in nested_internal_ids and ctype != "CPPS":
            continue  # non far trapelare i nodi interni ai CPPS
        filtered_components.append(c)

    # ---- Costruisco il workflow tenendo i gateway ESTERNI ----
    mapped = OrderedDict()

    def add_edge(store, s, t):
        if s == t:
            return
        if s not in store:
            store[s] = []
        if t not in store[s]:
            store[s].append(t)

    for source, targets in workflow.items():
        if source in nested_internal_ids:
            # Sorgente interna a un CPPS: alza al relativo group (uscita del CPPS)
            gid = node_to_group[source]
            inner = group_inner.get(gid, set())
            for t in targets:
                if t in inner:
                    continue  # interno->interno: resta nel CPPS, non trapela
                # se il target è interno a QUALCHE CPPS, collassa a quel group
                t_mapped = node_to_group.get(t, t)
                if t_mapped == gid:
                    continue  # evita self-loop group->group sullo stesso CPPS
                add_edge(mapped, gid, t_mapped)
        else:
            # Sorgente esterna (Activity, Gateway, Group esterno): mantenura
            dedup = []
            for t in targets:
                # target interno? collassa al relativo group
                t_mapped = node_to_group.get(t, t)
                if t_mapped != source and t_mapped not in dedup:
                    dedup.append(t_mapped)
            for t in dedup:
                add_edge(mapped, source, t)

    # ---- (opzionale) comprimo solo gateway ESTERNI banali ----
    if compress_trivial_gateways:
        # calcola predecessori
        preds = {}
        for s, tgts in mapped.items():
            for t in tgts:
                preds.setdefault(t, set()).add(s)

        compressed = OrderedDict()
        removed_gw = set()

        def add_c(s, t):
            add_edge(compressed, s, t)

        for src, tgts in mapped.items():
            is_external_gw = comp_type.get(src, "").endswith("Gateway") and (src not in nested_internal_ids)
            uniq_tgts = []
            for t in tgts:
                if t not in uniq_tgts:
                    uniq_tgts.append(t)

            if is_external_gw:
                src_preds = list(preds.get(src, []))
                if len(src_preds) == 1 and len(uniq_tgts) == 1:
                    add_c(src_preds[0], uniq_tgts[0])
                    removed_gw.add(src)
                    continue
            for t in uniq_tgts:
                add_c(src, t)

        # purge target = gateway compresso
        if removed_gw:
            for s, tgts in list(compressed.items()):
                new_t = [t for t in tgts if t not in removed_gw]
                if new_t:
                    compressed[s] = new_t
                else:
                    del compressed[s]
        mapped = compressed

    # ---- boundary-only: tieni solo archi che toccano almeno un CPPS ----
    if boundary_only:
        boundary = {}
        for s, tgts in mapped.items():
            keep = [t for t in tgts if (s in groups) or (t in groups)]
            if keep:
                boundary[s] = keep
        mapped = boundary

    # ---- pulizia finale: no self-loop, no entry vuote ----
    for s in list(mapped.keys()):
        mapped[s] = [t for t in mapped[s] if t != s]
        if not mapped[s]:
            del mapped[s]

    return filtered_components, mapped

@api_view(['POST'])
def save_cppn_service(request):
    data = request.data
    print("===CPPN Payload received:", data)

    # Prepara mappe CPPS (servono per normalizzare)
    components = data.get('components', [])
    cpps_ids = [c['id'] for c in components if c['type'] == 'CPPS']
    cpps_map = { c["group_id"]: c for c in cpps_collection.find({"group_id": {"$in": cpps_ids}}) }

    data["components"], data["workflow"] = normalize_cppn_components_and_workflow(data, cpps_map)

   # Salva CPPN nel database
    result, status_code = MongoDBHandler.save_cppn(data)

    if status_code in [200, 201]:
        # servers per self-link corretti
        servers = [{"url": request.build_absolute_uri("/").rstrip("/")}]
        pub_res = publish_cppn_spec(group_id=data["group_id"], servers=servers)

        if pub_res.get("status") == "ok":
            # link per la UI 
            json_url = reverse("openapi_docs:cppn-oas-latest", args=[data["group_id"]])
            swagger_url = reverse("openapi_docs:swagger-viewer-cppn", args=[data["group_id"]])
            doc_result, doc_status = {
                **pub_res,
                "links": {"json": json_url, "swagger": swagger_url}
            }, 201
            print("===OpenAPI CPPN published:", pub_res)

            rbac.cppn_policy(data, data["components"])
        else:
            doc_result, doc_status = {
                "message": "OpenAPI publish failed",
                "errors": pub_res.get("errors")
            }, 400
    else:
        doc_result, doc_status = {"message": "CPPN not saved, skipping OpenAPI"}, 400

    return Response({
        "cppn_service": result,
        "openapi_documentation": doc_result
    }, status=status_code)


@api_view(['GET'])
def get_cppn_service(request, group_id):
    service = cppn_collection.find_one({'group_id': group_id})
    if not service:
        return JsonResponse({'error': 'CPPN not found'}, status=404)

    return JsonResponse(service, safe=False, json_dumps_params={'default': json_util.default})

@api_view(['GET'])
def get_cpps_service(request, group_id):
    service = cpps_collection.find_one({'group_id': group_id})
    if not service:
        return Response({'error': 'CPPS not found'}, status=404)

    return JsonResponse(service, safe=False, json_dumps_params={'default': json_util.default})


@api_view(['GET'])
def get_atomic_service(request, task_id):
    service = atomic_services_collection.find_one({'task_id': task_id})
    if not service:
        return JsonResponse({'error': 'Atomic service not found'}, status=404)
    return JsonResponse(service, safe=False, json_dumps_params={'default': json_util.default})


@api_view(['GET'])
def get_all_services(request):
    atomic = list(atomic_services_collection.find(
        {},
        {
            '_id': 0,
            'task_id': 1,
            'name': 1,
            'description': 1,
            'input': 1,
            'output': 1,
            'input_params': 1,
            'output_params': 1,
            'owner' : 1,
            'atomic_type' : 1,
            'url' : 1,
            'method' : 1
        }
    ))

    # normalizzazione server-side
    for a in atomic:
        a['input']  = a.get('input')  or a.get('input_params')  or {}
        a['output'] = a.get('output') or a.get('output_params') or {}
        a.pop('input_params', None)
        a.pop('output_params', None)

    cpps = list(cpps_collection.find(
        {},
        {
            '_id': 0,
            'group_id': 1,
            'name': 1,
            'description': 1,
            'components': 1,
            'owner': 1
        }
    ))

    cppn = list(cppn_collection.find(
        {},
        {
            '_id': 0,
            'group_id': 1,
            'name': 1,
            'description': 1,
            'components': 1,
            'actors': 1,
            'gdpr_map': 1,
            'business_goal': 1
        }
    ))

    return Response({
        'atomic': atomic,
        'cpps': cpps,
        'cppn': cppn
    })

from datetime import datetime
from pymongo import UpdateOne
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

@api_view(['DELETE'])
def delete_group(request, group_id):
    try:
        # 1) Prova cancellare CPPS e/o CPPN con lo stesso group_id
        
        deleted_cpps = cpps_collection.find_one_and_delete({'group_id': group_id})
        if deleted_cpps:
            rbac_collection.find_one_and_delete({'cpps_id': group_id})

        deleted_cppn = cppn_collection.find_one_and_delete({'group_id': group_id})
        if deleted_cppn:
            rbac_collection.find_one_and_delete({'cppn_id': group_id})
            
        deleted_any = bool(deleted_cpps or deleted_cppn)


        # 2) Pulizia riferimenti in altri documenti (components, workflow, nested_cpps)
        pipeline = [
            { "$set": {
                "components": {
                    "$filter": {
                        "input": "$components",
                        "as": "c",
                        "cond": { "$ne": ["$$c.id", group_id] }
                    }
                }
            }},
            { "$set": {
                "workflow": {
                    "$cond": [
                        { "$and": [
                            { "$ne": ["$workflow", None] },
                            { "$eq": [ { "$type": "$workflow" }, "object" ] }
                        ]},
                        {
                            "$arrayToObject": {
                                "$map": {
                                    "input": {
                                        "$filter": {
                                            "input": { "$objectToArray": "$workflow" },
                                            "as": "w",
                                            "cond": { "$ne": ["$$w.k", group_id] }
                                        }
                                    },
                                    "as": "w",
                                    "in": {
                                        "k": "$$w.k",
                                        "v": {
                                            "$cond": [
                                                { "$isArray": "$$w.v" },
                                                {
                                                    "$filter": {
                                                        "input": "$$w.v",
                                                        "as": "t",
                                                        "cond": { "$ne": ["$$t", group_id] }
                                                    }
                                                },
                                                "$$w.v"
                                            ]
                                        }
                                    }
                                }
                            }
                        },
                        "$workflow"
                    ]
                }
            }},
            { "$set": {
                "nested_cpps": {
                    "$cond": [
                        { "$isArray": "$nested_cpps" },
                        {
                            "$filter": {
                                "input": "$nested_cpps",
                                "as": "n",
                                "cond": { "$ne": ["$$n", group_id] }
                            }
                        },
                        "$nested_cpps"
                    ]
                }
            }}
        ]

        match = {
            "$or": [
                {"components.id": group_id},
                {f"workflow.{group_id}": {"$exists": True}},
                {"nested_cpps": group_id}
            ]
        }

        cpps_update = cpps_collection.update_many(match, pipeline)
        cppn_update = cppn_collection.update_many(match, pipeline)

        pull_nested = {"$pull": {"nested_cpps": group_id}}
        cpps_pull = cpps_collection.update_many({"nested_cpps": group_id}, pull_nested)
        cppn_pull = cppn_collection.update_many({"nested_cpps": group_id}, pull_nested)

        # 3) Pulizia RBAC COMPOSITE (cpps/cppn) — iterativa
        rbac_filter = {
            "service_type": {"$in": ["cpps", "cppn"]},
            "$or": [
                {"permissions.service": group_id},
                {"members": group_id},
            ]
        }

        ops = []
        docs_scanned = 0
        perms_removed_total = 0
        members_removed_total = 0

        for doc in rbac_collection.find(rbac_filter):
            docs_scanned += 1

            perms = doc.get("permissions", []) or []
            new_perms = [p for p in perms if p.get("service") != group_id]
            perms_removed = len(perms) - len(new_perms)

            members = doc.get("members", []) or []
            new_members = [m for m in members if m != group_id]
            members_removed = len(members) - len(new_members)

            if perms_removed or members_removed:
                update = {
                    "permissions": new_perms,
                    "members": new_members,
                    "updated_at": datetime.utcnow(),
                }
                # ricalcola actors se presente la chiave
                if "actors" in doc:
                    update["actors"] = sorted({p.get("actor") for p in new_perms if p.get("actor")})

                ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": update}))

                perms_removed_total += perms_removed
                members_removed_total += members_removed

        rbac_modified = 0
        if ops:
            bw_res = rbac_collection.bulk_write(ops, ordered=False)
            rbac_modified = bw_res.modified_count

        payload = {
            "message": f"Gruppo {group_id} deleted!" if deleted_any else f"Gruppo {group_id} not found",
            "deleted_from_cpps": bool(deleted_cpps),
            "deleted_from_cppn": bool(deleted_cppn),
            "updated_cpps_docs": cpps_update.modified_count,
            "updated_cppn_docs": cppn_update.modified_count,
            "pulled_cpps_nested": cpps_pull.modified_count,
            "pulled_cppn_nested": cppn_pull.modified_count,
            "rbac_docs_scanned": docs_scanned,
            "rbac_docs_modified": rbac_modified,
            "rbac_permissions_removed": perms_removed_total,
            "rbac_members_removed": members_removed_total,
        }

        return Response(payload, status=status.HTTP_200_OK if deleted_any else status.HTTP_404_NOT_FOUND)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



@api_view(['POST'])
def add_nested_cpps(request, group_id):
    nested_id = request.data.get('nested_id')
    if not nested_id:
        return Response({'error': 'Missing nested_id'}, status=400)

    result = cpps_collection.update_one(
        {'group_id': group_id},
        {'$addToSet': {'nested_cpps': nested_id}}
    )

    if result.matched_count == 0:
        return Response({'error': 'Parent CPPS not found'}, status=404)

    return Response({'status': 'nested_cpps updated'})


from datetime import datetime
from pymongo import UpdateOne

@api_view(['DELETE'])
def delete_atomic(request, atomic_id):
    try:
        # 1) Cancello l'atomic e la sua RBAC specifica (se presente)
        deleted = atomic_services_collection.find_one_and_delete({'task_id': atomic_id})
        rbac_deleted = rbac_collection.find_one_and_delete({'atomic_id': atomic_id})
        if not deleted:
            return Response({'error': 'Atomic service not found'}, status=404)

        # 2) Pulizia CPPS/CPPN (components + workflow) — tua pipeline originale
        pipeline_cpps_cppn = [
            {"$set": {
                "components": {
                    "$filter": {
                        "input": "$components",
                        "as": "c",
                        "cond": {"$ne": ["$$c.id", atomic_id]}
                    }
                }
            }},
            {"$set": {
                "workflow": {
                    "$arrayToObject": {
                        "$map": {
                            "input": {
                                "$filter": {
                                    "input": {"$objectToArray": "$workflow"},
                                    "as": "w",
                                    "cond": {"$ne": ["$$w.k", atomic_id]}
                                }
                            },
                            "as": "w",
                            "in": {
                                "k": "$$w.k",
                                "v": {
                                    "$filter": {
                                        "input": "$$w.v",
                                        "as": "t",
                                        "cond": {"$ne": ["$$t", atomic_id]}
                                    }
                                }
                            }
                        }
                    }
                }
            }}
        ]
        cpps_result = cpps_collection.update_many({}, pipeline_cpps_cppn)
        cppn_result = cppn_collection.update_many({}, pipeline_cpps_cppn)

        # 3) Pulizia RBAC (cpps/cppn) ITERATIVA: rimuovi tutte le triple con service == atomic_id
        #    e l'atomic_id da members[]; ricalcola actors dalle permission rimaste.
        rbac_filter = {
            "service_type": {"$in": ["cpps", "cppn"]},
            "$or": [
                {"permissions.service": atomic_id},
                {"members": atomic_id},
            ]
        }

        ops = []
        docs_scanned = 0
        docs_modified = 0
        perms_removed_total = 0
        members_removed_total = 0

        for doc in rbac_collection.find(rbac_filter):
            docs_scanned += 1

            perms = doc.get("permissions", []) or []
            new_perms = [p for p in perms if p.get("service") != atomic_id]
            perms_removed = len(perms) - len(new_perms)

            members = doc.get("members", []) or []
            new_members = [m for m in members if m != atomic_id]
            members_removed = len(members) - len(new_members)

            if perms_removed or members_removed:
                update = {
                    "permissions": new_perms,
                    "members": new_members,
                    "updated_at": datetime.utcnow(),
                }

                # Se il documento ha la chiave actors, ricalcolala dalle permission rimaste
                if "actors" in doc:
                    new_actors = sorted({p.get("actor") for p in new_perms if p.get("actor")})
                    update["actors"] = new_actors

                ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": update}))
                perms_removed_total += perms_removed
                members_removed_total += members_removed

        if ops:
            bw_res = rbac_collection.bulk_write(ops, ordered=False)
            docs_modified = bw_res.modified_count

        return Response({
            "status": "deleted",
            "removed_from_cpps": cpps_result.modified_count,
            "removed_from_cppn": cppn_result.modified_count,
            "rbac_docs_scanned": docs_scanned,
            "rbac_docs_modified": docs_modified,
            "rbac_permissions_removed": perms_removed_total,
            "rbac_members_removed": members_removed_total,
        }, status=200)

    except Exception as e:
        print(f"Error during atomic delete: {e}")
        return Response({"error": str(e)}, status=500)

@api_view(['DELETE'])
def delete_diagram_and_services(request, diagram_id):
    try:
        obj_id = ObjectId(diagram_id)

        # Elimina il diagramma
        result = bpmn_collection.delete_one({"_id": obj_id})
        if result.deleted_count == 0:
            return Response({"error": "Diagram not found"}, status=404)

        # Elimina atomic services collegati
        atomic_deleted = atomic_services_collection.delete_many({"diagram_id": diagram_id})

        # Elimina CPPS collegati
        cpps_deleted = cpps_collection.delete_many({"diagram_id": diagram_id})

        # Elimina CPPN collegati
        cppn_deleted = cppn_collection.delete_many({"diagram_id": diagram_id})

        # Elimina documentazione OpenAPI associata
        openapi_deleted = openapi_collection.delete_many({"info.x-diagram_id": diagram_id})

        # Elimina rbac dei servizi del diagramma
        rbac_delted = rbac_collection.delete_many({"diagram_id": diagram_id})


        return Response({
            "status": "deleted",
            "diagram_id": diagram_id,
            "atomic_deleted": atomic_deleted.deleted_count,
            "cpps_deleted": cpps_deleted.deleted_count,
            "cppn_deleted": cppn_deleted.deleted_count,
            "openapi_deleted": openapi_deleted.deleted_count
        }, status=200)

    except InvalidId:
        return Response({"error": "Invalid diagram ID"}, status=400)
    except Exception as e:
        return Response({"error": str(e)}, status=500)
