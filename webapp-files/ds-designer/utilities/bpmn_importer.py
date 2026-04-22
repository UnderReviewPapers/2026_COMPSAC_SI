import os
import xml.etree.ElementTree as ET
from datetime import datetime
import json

from .mongodb_handler import (
    MongoDBHandler,
    atomic_services_collection,
    bpmn_collection,
    cpps_collection
)
from openapi_docs.services import publish_atomic_spec, publish_cpps_spec, publish_cppn_spec
from .helpers import detect_type
from collections import OrderedDict
from .rbac import rbac


class BPMNImporterXmlBased:

    def __init__(self, bpmn_path, name=None, servers=None):
        self.bpmn_path = bpmn_path
        self.diagram_id = None
        self.xml_root = None
        self.namespaces = {}
        self.provided_name = name
        self.servers = servers or []   # es. [{"url":"http://localhost:8000"}]

    def parse_bpmn(self):
        tree = ET.parse(self.bpmn_path)
        self.xml_root = tree.getroot()
        self.namespaces = self._get_namespaces()

    def save_diagram(self):
        with open(self.bpmn_path, "r", encoding="utf-8") as f:
            xml_content = f.read()

        filename = os.path.basename(self.bpmn_path)
        name = self.provided_name or os.path.splitext(filename)[0]

        doc = {
            "name": name,
            "filename": filename,
            "xml_content": xml_content,
            "created_at": datetime.utcnow()
        }

        result = bpmn_collection.insert_one(doc)
        self.diagram_id = result.inserted_id
        print(f"ID Diagram saved: {self.diagram_id}")


    def _extract_workflow_cpps(self, group_id, members):
        ns = self.namespaces
        workflow = {}

        for seq in self.xml_root.findall(".//bpmn:sequenceFlow", ns):
            source_ref = seq.attrib.get("sourceRef")
            target_ref = seq.attrib.get("targetRef")

            if source_ref in members and target_ref in members:
                if source_ref not in workflow:
                    workflow[source_ref] = []
                workflow[source_ref].append(target_ref)

        return workflow
    
    def _detect_nested_cpps(self, outer_group_id):
        ns = self.namespaces
        # bounds del group esterno
        outer = self.xml_root.find(f".//bpmndi:BPMNShape[@bpmnElement='{outer_group_id}']", ns)
        if outer is None:
            return []
        ob = outer.find("dc:Bounds", ns)
        gx, gy, gw, gh = map(float, (ob.attrib["x"], ob.attrib["y"], ob.attrib["width"], ob.attrib["height"]))

        nested = []
        for shp in self.xml_root.findall(".//bpmndi:BPMNShape", ns):
            gid = shp.attrib.get("bpmnElement", "")
            if not gid.startswith("Group_") or gid == outer_group_id:
                continue
            b = shp.find("dc:Bounds", ns)
            if b is None:
                continue
            x, y = float(b.attrib["x"]), float(b.attrib["y"])
            # dentro al rettangolo dell’outer?
            if not (gx <= x <= gx+gw and gy <= y <= gy+gh):
                continue

            # è davvero un CPPS? check l’estensione custom
            ext = self.xml_root.find(f".//bpmn:group[@id='{gid}']/bpmn:extensionElements/custom:groupExtension", ns)
            gtype = ext.find("custom:groupType", ns).text.strip() if ext is not None and ext.find("custom:groupType", ns) is not None else ""
            if gtype == "CPPS":
                nested.append(gid)

        return nested

    def _collapse_cppn_to_groups(self, components, workflow, cpps_map):
        """
        Collassa i nodi interni (Atomic + Gateway) dei CPPS annidati al rispettivo group_id.
        Mantiene gateway ESTERNI, rimuove archi interni->interni allo stesso CPPS.
        """
        # indice: nodo interno -> suo CPPS
        node_to_group = {}
        group_inner = {}

        for gid, cpps_doc in cpps_map.items():
            inner_ids = {c["id"] for c in cpps_doc.get("components", [])}
            group_inner[gid] = inner_ids
            for nid in inner_ids:
                node_to_group[nid] = gid

        nested_internal = set(node_to_group.keys())  # atomic + gateway interni

        # filtra i componenti del CPPN: niente leak di nodi interni
        filtered_components = []
        for c in components:
            cid, ctype = c["id"], c["type"]
            if cid in nested_internal and ctype != "CPPS":
                continue
            filtered_components.append(c)

        # mappa gli archi
        collapsed = OrderedDict()
        def add(s, t):
            if s == t: return
            collapsed.setdefault(s, [])
            if t not in collapsed[s]:
                collapsed[s].append(t)

        for s, tgts in workflow.items():
            s2 = node_to_group.get(s, s)
            inner_s = group_inner.get(s2, set()) if s2 in group_inner else set()
            for t in tgts:
                t2 = node_to_group.get(t, t)
                # se entrambi mappano allo stesso CPPS, è un arco interno: scarta
                if s2 == t2 and s2 in group_inner:
                    continue
                # se la sorgente era interna e il target interno allo stesso CPPS: scarta
                if s in nested_internal and t in inner_s:
                    continue
                add(s2, t2)

        # pulizia
        for k in list(collapsed.keys()):
            collapsed[k] = [t for t in collapsed[k] if t != k]
            if not collapsed[k]:
                del collapsed[k]

        return filtered_components, collapsed


    def _extract_workflow_cppn(self, group_id, members):
        """
        CPPN 'grezzo' in linea col frontend:
        - SequenceFlow: source e target interni al group, escludendo Event
        - MessageFlow: se almeno uno è interno; registriamo solo se la *sorgente* è interna (no chiavi esterne)
        - dedup, no self-loop
        """
        ns = self.namespaces
        wf = {}

        # ---- helpers -----------------------------------------------------------
        # raccogli tutti gli Event BPMN e crea un set di id
        event_tags = [
            "bpmn:startEvent",
            "bpmn:endEvent",
            "bpmn:intermediateCatchEvent",
            "bpmn:intermediateThrowEvent",
            "bpmn:boundaryEvent",
        ]
        event_ids = {
            el.attrib.get("id")
            for tag in event_tags
            for el in self.xml_root.findall(f".//{tag}", ns)
            if el.attrib.get("id")
        }

        allowed = set(members) - event_ids  # membri del group NON-evento

        def add(s, t):
            if not s or not t or s == t:
                return
            if s not in wf:
                wf[s] = []
            if t not in wf[s]:
                wf[s].append(t)

        # ---- SequenceFlow interni al group (no Event) ----------------------
        for seq in self.xml_root.findall(".//bpmn:sequenceFlow", ns):
            s = seq.attrib.get("sourceRef")
            t = seq.attrib.get("targetRef")
            if s in allowed and t in allowed:
                add(s, t)

        # ---- MessageFlow: almeno un endpoint interno; escludi Event --------
        for mf in self.xml_root.findall(".//bpmn:messageFlow", ns):
            s = mf.attrib.get("sourceRef")
            t = mf.attrib.get("targetRef")

            # almeno uno interno
            if not ((s in members) or (t in members)):
                continue

            # escludi se uno dei due è un Event
            if s in event_ids or t in event_ids:
                continue

            # registra l’arco solo se la sorgente è interna e non-evento
            if s in allowed:
                add(s, t)

        return wf

    def _extract_gateways(self, members):
        ns = self.namespaces
        gateway_tags = {
            "bpmn:parallelGateway": "ParallelGateway",
            "bpmn:exclusiveGateway": "ExclusiveGateway",
            "bpmn:inclusiveGateway": "InclusiveGateway"
        }

        gateway_components = []

        for gw_tag, gw_type in gateway_tags.items():
            for gw in self.xml_root.findall(f".//{gw_tag}", ns):
                gw_id = gw.attrib.get("id")
                if not gw_id or gw_id not in members:
                    continue

                targets = []
                for seq in self.xml_root.findall(".//bpmn:sequenceFlow", ns):
                    if seq.attrib.get("sourceRef") == gw_id and seq.attrib.get("targetRef") in members:
                        targets.append(seq.attrib["targetRef"])

                gateway_components.append({
                    "id": gw_id,
                    "type": gw_type,
                    "targets": targets
                })

        return gateway_components

    def import_all(self):
        self.parse_bpmn()
        self.save_diagram()

        atomic_count = 0
        cpps_count = 0
        cppn_count = 0
        ns = self.namespaces

        # ------------------------ ATOMIC ------------------------
        for elem in self.xml_root.iter():
            tag = self._strip_ns(elem.tag)

            if tag == "task":
                task_id = elem.attrib["id"]
                task_name = elem.attrib.get("name", f"Task {task_id}")
                ext = elem.find(".//custom:atomicExtension", ns)

                if ext is not None:
                    atomic_type = ext.find("custom:atomicType", ns)
                    input_tag = ext.find("custom:inputParams", ns)
                    output_tag = ext.find("custom:outputParams", ns)
                    method_tag = ext.find("custom:method", ns)
                    url_tag = ext.find("custom:url", ns)
                    owner_tag = ext.find("custom:owner", ns)

                    input_params = input_tag.text.strip().split(",") if input_tag is not None else []
                    output_params = output_tag.text.strip().split(",") if output_tag is not None else []

                    input_dict = {p.strip(): detect_type(p.strip()) for p in input_params if p.strip()}
                    output_dict = {p.strip(): detect_type(p.strip()) for p in output_params if p.strip()}

                    atomic_doc = {
                        "diagram_id": str(self.diagram_id),
                        "task_id": task_id,
                        "name": task_name,
                        "atomic_type": atomic_type.text.strip() if atomic_type is not None else "unspecified",
                        "input_params": input_params,
                        "output_params": output_params,
                        "method": method_tag.text.strip() if method_tag is not None else "POST",
                        "url": url_tag.text.strip() if url_tag is not None else f"/{task_id.lower()}",
                        "owner": owner_tag.text.strip() if owner_tag is not None else "AutoImport",
                        "input": input_dict,
                        "output": output_dict
                    }

                    MongoDBHandler.save_atomic(atomic_doc)
                    rbac.atomic_policy(atomic_doc)

                    try:
                        pub = publish_atomic_spec(service_id=task_id, servers=self.servers)
                    except Exception as e:
                        pub = {"status": "error", "errors": [f"{type(e).__name__}: {e}"]}

                    atomic_count += 1
                    print(f"Atomic saved: {task_name}")
                else:
                    print(f"No <atomicExtension> for: {task_name}")

        # ------------------------ PARTIZIONA GROUP ------------------------
        group_to_elements = self._extract_group_members()
        actor_map = self._map_task_to_actor()

        cpps_groups = []
        cppn_groups = []

        # Qui NON salvo nulla: decido solo il tipo del group
        for group_id, members in group_to_elements.items():
            involved_actors = set(actor_map.get(mid) for mid in members if mid in actor_map)

            valid_tasks = [
                {"id": mid, "type": "Atomic"}
                for mid in members
                if atomic_services_collection.find_one({"task_id": mid})
            ]

            #controllo se cpps ha dentro altri cpps o gateway
            has_nested = bool(self._detect_nested_cpps(group_id))
            has_gateways = bool(self._extract_gateways(members))

           # skippa solo se davvero vuoto
            if not (valid_tasks or has_nested or has_gateways):
                print(f"[IMPORT] Skip {group_id}: no atomic/cpps/gateways")
                continue

            if len(involved_actors) == 1:
                cpps_groups.append((group_id, members, involved_actors, valid_tasks))
            else:
                cppn_groups.append((group_id, members, involved_actors, valid_tasks))

        # ------------------------ PASSO 1: SALVA TUTTI I CPPS ------------------------
        for group_id, members, involved_actors, valid_tasks in cpps_groups:
            actor = list(involved_actors)[0] if involved_actors else "UnknownActor"

            group_ext = self.xml_root.find(f".//bpmn:group[@id='{group_id}']/bpmn:extensionElements/custom:groupExtension", ns)
            group_name = group_ext.find("custom:name", ns).text.strip() if group_ext is not None and group_ext.find("custom:name", ns) is not None else f"Composite {group_id}"
            group_description = group_ext.find("custom:description", ns).text.strip() if group_ext is not None and group_ext.find("custom:description", ns) is not None else "Imported composite service"
            workflow_type = group_ext.find("custom:workflowType", ns).text.strip() if group_ext is not None and group_ext.find("custom:workflowType", ns) is not None else "sequence"
            gdpr_tag = group_ext.find("custom:gdprMap", ns) if group_ext is not None else None
            try:
                gdpr_map = json.loads(gdpr_tag.text.strip()) if gdpr_tag is not None else {}
            except json.JSONDecodeError:
                print(f"JSON invalido per gdprMap nel gruppo {group_id}")
                gdpr_map = {}

            workflow = self._extract_workflow_cpps(group_id, members)
            gateway_components = self._extract_gateways(members)
            valid_task_ids = [c['id'] for c in valid_tasks]

            components = valid_tasks + gateway_components

            cpps_doc = {
                "diagram_id": str(self.diagram_id),
                "group_id": group_id,
                "name": group_name,
                "description": group_description,
                "workflow_type": workflow_type,
                "owner": actor,
                "components": components,
                "endpoints": [],
                "group_type": "CPPS",
                "workflow": workflow,
                "gdpr_map": gdpr_map
            }

            MongoDBHandler.save_cpps(cpps_doc)
            rbac.cpps_policy_from_import(cpps_doc, components)
            try:
                pub = publish_cpps_spec(group_id=group_id, servers=self.servers)
                print(f"CPPS published {group_id}: {pub}")
            except Exception as e:
                print(f"CPPS publish failed {group_id}: {type(e).__name__}: {e}")

            # (eventuale) mappa atomic se serve in seguito
            # atomic_map = {a["task_id"]: a for a in atomic_services_collection.find({"task_id": {"$in": valid_task_ids}})}

            cpps_count += 1
            print(f"CPPS salvato: {group_id}")

        # ------------------------ PASSO 2: SALVA TUTTI I CPPN ------------------------
        cppn_docs_to_rbac = []  # (cppn_doc, components_norm) per RBAC posticipato

        for group_id, members, involved_actors, valid_tasks in cppn_groups:
            group_ext = self.xml_root.find(f".//bpmn:group[@id='{group_id}']/bpmn:extensionElements/custom:groupExtension", ns)
            group_name = group_ext.find("custom:name", ns).text.strip() if group_ext is not None and group_ext.find("custom:name", ns) is not None else f"Composite {group_id}"
            group_description = group_ext.find("custom:description", ns).text.strip() if group_ext is not None and group_ext.find("custom:description", ns) is not None else "Imported composite service"
            workflow_type = group_ext.find("custom:workflowType", ns).text.strip() if group_ext is not None and group_ext.find("custom:workflowType", ns) is not None else "sequence"
            business_goal_tag = group_ext.find("custom:businessGoal", ns) if group_ext is not None else None
            business_goal = business_goal_tag.text.strip() if business_goal_tag is not None else ""

            gdpr_tag = group_ext.find("custom:gdprMap", ns) if group_ext is not None else None
            try:
                gdpr_map = json.loads(gdpr_tag.text.strip()) if gdpr_tag is not None else {}
            except json.JSONDecodeError:
                print(f"JSON invalido per gdprMap nel gruppo {group_id}")
                gdpr_map = {}

            gateway_components = self._extract_gateways(members)

            # CPPS annidati dentro al CPPN
            nested_cpps_ids = self._detect_nested_cpps(group_id)
            nested_cpps_components = [{"id": gid, "type": "CPPS"} for gid in nested_cpps_ids]

            # componenti COMPLETI del CPPN
            components_cppn = valid_tasks + gateway_components + nested_cpps_components

            # workflow “grezzo” (sequence interni + message flow, senza eventi)
            workflow_raw = self._extract_workflow_cppn(group_id, members)

            # mappa dei CPPS annidati presa dal DB (serve per collassare)
            cpps_map = {c["group_id"]: c for c in cpps_collection.find({"group_id": {"$in": nested_cpps_ids}})}

            # collassa interni -> group_id
            components_norm, workflow_norm = self._collapse_cppn_to_groups(components_cppn, workflow_raw, cpps_map)

            cppn_doc = {
                "diagram_id": str(self.diagram_id),
                "group_id": group_id,
                "name": group_name,
                "description": group_description,
                "workflow_type": workflow_type,
                "actors": list(involved_actors),
                "gdpr_map": gdpr_map,
                "components": components_norm,
                "group_type": "CPPN",
                "workflow": workflow_norm,
                "business_goal" : business_goal
            }
            MongoDBHandler.save_cppn(cppn_doc)

            try:
                pubn = publish_cppn_spec(group_id=group_id, servers=self.servers)
                print(f"CPPN published {group_id}: {pubn}")
            except Exception as e:
                print(f"CPPN publish failed {group_id}: {type(e).__name__}: {e}")

            cppn_count += 1
            print(f"CPPN saved: {group_id}")

            # Posticipa RBAC: ora accodiamo e lo eseguiremo alla fine
            cppn_docs_to_rbac.append((cppn_doc, components_norm))

        # ------------------------ PASSO 3: RBAC sui CPPN ------------------------
        for cppn_doc, components_norm in cppn_docs_to_rbac:
            try:
                rbac.cppn_policy(cppn_doc, components_norm)
            except Exception as e:
                # Non blocca l’intero import in caso di errore di policy
                print(f"[RBAC] cppn_policy fallita per {cppn_doc.get('group_id')}: {type(e).__name__}: {e}")

        print(f"\nImportazione completata: {atomic_count} atomic, {cpps_count} cpps, {cppn_count} cppn")

        return {
            "diagram_id": str(self.diagram_id),
            "atomic": atomic_count,
            "cpps": cpps_count,
            "cppn": cppn_count
        }

    def _extract_group_members(self):
        ns = self.namespaces
        group_members = {}

        for g in self.xml_root.findall(".//bpmndi:BPMNShape", ns):
            bpmn_element = g.attrib.get("bpmnElement", "")
            if not bpmn_element.startswith("Group_"):
                continue

            group_id = bpmn_element
            bounds = g.find("dc:Bounds", ns)
            if bounds is None:
                continue

            gx = float(bounds.attrib["x"])
            gy = float(bounds.attrib["y"])
            gw = float(bounds.attrib["width"])
            gh = float(bounds.attrib["height"])

            members = []
            for shape in self.xml_root.findall(".//bpmndi:BPMNShape", ns):
                target_elem = shape.attrib.get("bpmnElement", "")
                if target_elem.startswith("Group_"):
                    continue
                b = shape.find("dc:Bounds", ns)
                if b is None:
                    continue

                x = float(b.attrib["x"])
                y = float(b.attrib["y"])

                if gx <= x <= gx + gw and gy <= y <= gy + gh:
                    members.append(target_elem)

            group_members[group_id] = members

        return group_members

    def _map_task_to_actor(self):
        ns = self.namespaces
        task_to_actor = {}

        process_to_actor = {
            p.attrib.get("processRef"): p.attrib.get("name", p.attrib["id"])
            for p in self.xml_root.findall(".//bpmn:participant", ns)
            if p.attrib.get("processRef")
        }

        for proc in self.xml_root.findall(".//bpmn:process", ns):
            process_id = proc.attrib.get("id")
            actor = process_to_actor.get(process_id, "UnknownActor")

            for task in proc.findall(".//bpmn:task", ns):
                tid = task.attrib.get("id")
                if tid:
                    task_to_actor[tid] = actor

        return task_to_actor

    def _get_namespaces(self):
        events = ("start", "start-ns")
        ns = {}
        for event, elem in ET.iterparse(self.bpmn_path, events):
            if event == "start-ns":
                prefix, uri = elem
                ns[prefix] = uri
        return ns

    def _strip_ns(self, tag):
        return tag.split('}')[-1] if '}' in tag else tag