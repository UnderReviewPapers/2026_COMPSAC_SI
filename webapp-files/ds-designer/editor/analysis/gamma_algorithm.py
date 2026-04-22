import re
import string
import matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
from dataclasses import dataclass
from typing import List, Set, Dict
import pandas as pd
import numpy as np
from scipy.cluster import hierarchy
import sys
import itertools
import xml.etree.ElementTree as ET
from matplotlib.ticker import MultipleLocator
import tempfile
import os

# -----------------------------
# Dataclass Task
# -----------------------------
@dataclass
class Task:
    id: str         
    original_id: str 
    name: str       
    d_terms: List[str]
    IN: Set[str]
    OUT: Set[str]
    r: str
    A: Set[str]

# -----------------------------
# Parsing e Utility (Base)
# -----------------------------
def infer_crud(method: str, tags: str) -> Set[str]:
    method = (method or "").upper()
    tags = (tags or "").lower()
    actions = set()
    if method == "GET": actions.add("R")
    if method == "POST": actions.add("C")
    if "process" in tags or "update" in tags: actions.add("U")
    if "delete" in tags or "del" in tags: actions.add("D")
    if "collect" in tags: actions.add("R")
    if "dispatch" in tags or "send" in tags: actions.add("C")
    if "monitor" in tags: actions.add("R")
    return actions

def expand_crud_actions(task: Task) -> Set[str]:
    expanded = set()
    if "C" in task.A:
        for o in task.OUT: expanded.add(f"C({o})")
    if "R" in task.A:
        for i in task.IN: expanded.add(f"R({i})")
    if "U" in task.A:
        targets = task.IN.intersection(task.OUT) or task.OUT
        for o in targets: expanded.add(f"U({o})")
    if "D" in task.A:
        for i in task.IN: expanded.add(f"D({i})")
    return expanded

def extract_terms(name: str, url: str) -> List[str]:
    tokens = re.findall(r"[A-Za-z0-9]+", (name or ""))
    url_tokens = [seg for seg in re.split(r"[\/_\-]+", (url or "")) if seg]
    tokens = [t.lower() for t in tokens + url_tokens]
    tokens = [t for t in tokens if len(t) > 1]
    seen = set()
    out = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out

def split_items(s) -> set:
    if s is None: return set()
    if isinstance(s, list): s = ','.join(s)
    parts = [p.strip().lower() for p in re.split(r"[,;\/]| and |&|\|", s) if p.strip()]
    return set(parts)

def parse_atomic_services(text: str) -> List[Dict]:
    pattern = re.compile(
        r"(AS_Activity_[\w\d]+)\s*=\s*<\s*P_AS\d*\s*=\s*\{"
        r"name='([^']+)',\s*method='([^']*)',\s*URL='([^']*)'(?:,\s*owner='([^']*)')?"
        r"\s*\}\s*,\s*IN_AS\d+=\[([^\]]*)\]\s*,\s*OUT_AS\d+=\[([^\]]*)\]\s*,\s*T_AS\d+='([^']*)'\s*>",
        re.IGNORECASE
    )
    results = []
    for m in pattern.finditer(text):
        in_raw = [item.strip().strip("'") for item in m.group(6).split(',') if item.strip()]
        out_raw = [item.strip().strip("'") for item in m.group(7).split(',') if item.strip()]
        results.append({
            "id": m.group(1).strip(),
            "name": m.group(2).strip(),
            "method": m.group(3).strip(),
            "url": m.group(4).strip(),
            "owner": (m.group(5) or "").strip(),
            "IN_raw": in_raw,
            "OUT_raw": out_raw,
            "tag": m.group(8).strip()
        })
    return results

def build_tasks(as_entries: List[Dict]) -> List[Task]:
    tasks: List[Task] = []
    for i, e in enumerate(as_entries, start=1):
        aid = f"t_{i}"
        d_terms = extract_terms(e["name"], e["url"])
        IN_set = split_items(e["IN_raw"])
        OUT_set = split_items(e["OUT_raw"])
        crud = infer_crud(e["method"], e["tag"])
        role = e.get("owner") or "unknown"
        clean_id = e["id"].replace("AS_", "")
        task = Task(aid, clean_id, e["name"], d_terms, IN_set, OUT_set, role, crud)
        task.A = expand_crud_actions(task)
        tasks.append(task)
    return tasks

def parse_workflow_graph_from_txt(text: str, tasks: List[Task]):
    adj = {}
    lines = text.splitlines()
    start_reading = False
    for line in lines:
        if "--- FLUSSO DELLE ATTIVITÀ" in line:
            start_reading = True
            continue
        if not start_reading or not line.strip(): continue
        separator = "-->"
        if "==(MESSAGE)==>" in line: separator = "==(MESSAGE)==>"
        if separator not in line: continue
        
        parts = line.split(separator)
        
        def extract_id(raw_str):
            match = re.search(r"\(([\w\d_]+)\)", raw_str)
            return match.group(1) if match else None

        src_id = extract_id(parts[0].strip())
        tgt_id = extract_id(parts[1].strip())
        if src_id and tgt_id:
            if src_id not in adj: adj[src_id] = []
            adj[src_id].append(tgt_id)
    return adj

def simplify_workflow(adj: Dict, tasks: List[Task]):
    simplified = {}
    xml_to_task = {t.original_id.replace("AS_", ""): t.id for t in tasks}
    sorted_tasks = sorted(tasks, key=lambda x: int(x.id.split('_')[1]))

    for t in sorted_tasks:
        start_node = t.original_id.replace("AS_", "")
        if start_node not in adj: continue
        targets = set()
        visited = set()
        queue = list(adj[start_node])
        while queue:
            curr = queue.pop(0)
            if curr in visited: continue
            visited.add(curr)
            if curr in xml_to_task:
                found_t_id = xml_to_task[curr]
                if found_t_id != t.id: targets.add(found_t_id)
            else:
                if curr in adj: queue.extend(adj[curr])
        if targets: simplified[t.id] = targets
    return simplified

# -----------------------------
# Math & Logic (Dependency, Value, Gamma)
# -----------------------------
def value_analysis(tasks: List[Task]):
    V = []
    for t_creator in tasks:
        out_lower = {bo.lower() for bo in t_creator.OUT}
        for bo in out_lower:
            receivers = set()
            for t_consumer in tasks:
                if t_consumer.id == t_creator.id: continue
                in_lower = {i.lower() for i in t_consumer.IN}
                if bo in in_lower and any(a[0] in {"R", "U", "D"} for a in t_consumer.A):
                    receivers.add(t_consumer.r)
            if receivers:
                V.append({"bo": bo, "creator_task": t_creator.id, "creator_role": t_creator.r, "receiver_roles": receivers})
    
    V_grouped = {}
    for v in V:
        bo = v["bo"]
        if bo not in V_grouped:
            V_grouped[bo] = {"bo": bo, "creator_tasks": set(), "creator_roles": set(), "receiver_roles": set()}
        V_grouped[bo]["creator_tasks"].add(v["creator_task"])
        V_grouped[bo]["creator_roles"].add(v["creator_role"])
        V_grouped[bo]["receiver_roles"].update(v["receiver_roles"])
    return list(V_grouped.values())

def task_dependency_matrix(tasks: List[Task]) -> pd.DataFrame:
    ids = [t.id for t in tasks]
    matrix = pd.DataFrame(0.0, index=ids, columns=ids)
    for ti in tasks:
        for tj in tasks:
            if ti.id == tj.id: continue
            shared_bo = ti.OUT.intersection(tj.IN)
            denom = len(ti.OUT) + len(tj.IN)
            tau_val = (2 * len(shared_bo) / denom) if denom > 0 else 0.0
            matrix.loc[ti.id, tj.id] = round(tau_val, 3)
    return matrix

def candidate_service_population_flow_aware(S_i_tasks, tau_matrix, χ, task_map, flow_map):
    added = True
    while added:
        added = False
        all_task_ids = sorted(task_map.keys(), key=lambda x: int(x.split('_')[1]) if '_' in x else 0)
        for t_id in all_task_ids:
            if t_id in χ: continue
            has_data_dependency = any(tau_matrix.loc[tj, t_id] > 0 for tj in S_i_tasks)
            if not has_data_dependency: continue
            
            is_flow_connected = False
            for existing_t in S_i_tasks:
                if t_id in flow_map.get(existing_t, set()):
                    is_flow_connected = True; break
                if existing_t in flow_map.get(t_id, set()):
                    is_flow_connected = True; break
            
            if is_flow_connected:
                S_i_tasks.add(t_id); χ.add(t_id); added = True
    return S_i_tasks

def value_based_service_identification_flow_aware(tasks, tau_matrix, V, flow_map):
    Σ = []; χ = set(); T = set(t.id for t in tasks)
    task_map = {t.id: t for t in tasks}
    
    def service_name_gen():
        letters = string.ascii_uppercase
        n = 1
        while True:
            for comb in itertools.product(letters, repeat=n): yield "S_" + "".join(comb)
            n += 1
    name_gen = service_name_gen()

    bo_to_creators = {}
    if V:
        for v in V:
            bo = v.get("bo", "")
            creators = set(v.get("creator_tasks", []) or [])
            if creators: bo_to_creators.setdefault(bo, set()).update(creators)
    if not bo_to_creators:
        for t in tasks:
            for o in t.OUT: bo_to_creators.setdefault(o.lower(), set()).add(t.id)

    for bo, creators in bo_to_creators.items():
        S_i = set()
        for creator in sorted(creators):
            if creator in χ: continue
            S_i.add(creator); χ.add(creator)
            if creator in T: T.remove(creator)
        if S_i: Σ.append({"service_id": next(name_gen), "tasks": S_i})

    for S_i in Σ:
        S_i["tasks"] = candidate_service_population_flow_aware(set(S_i["tasks"]), tau_matrix, χ, task_map, flow_map)

    sorted_remaining = sorted(T - χ, key=lambda x: int(x.split('_')[1]) if '_' in x else 0)
    for t_id in sorted_remaining:
        Σ.append({"service_id": next(name_gen), "tasks": {t_id}})
    
    return [s for s in Σ if s["tasks"]]

def internal_cohesion(service_tasks: set, tau_matrix: pd.DataFrame) -> float:
    n = len(service_tasks)
    if n <= 1: return 1.0
    pairs = itertools.permutations(service_tasks, 2)
    total = sum(tau_matrix.loc[ti, tj] for ti, tj in pairs if ti in tau_matrix.index and tj in tau_matrix.columns)
    return round(total / (n * (n - 1) / 2), 3)

def service_coupling(Sa: set, Sb: set, tau_matrix: pd.DataFrame) -> float:
    if not Sa or not Sb: return 0.0
    pairs = itertools.product(Sa, Sb)
    total = sum(tau_matrix.loc[ti, tj] for ti, tj in pairs if ti in tau_matrix.index and tj in tau_matrix.columns)
    return round(total / (len(Sa) * len(Sb)), 3)

def process_cohesion(services: list, tau_matrix: pd.DataFrame) -> float:
    if not services: return 0.0
    values = [internal_cohesion(s["tasks"], tau_matrix) for s in services]
    return round(sum(values) / len(values), 3)

def process_coupling(services: list, tau_matrix: pd.DataFrame) -> float:
    n = len(services)
    if n <= 1: return 0.0 if n < 1 else 1.0
    total = sum(service_coupling(Sa["tasks"], Sb["tasks"], tau_matrix) for Sa, Sb in itertools.permutations(services, 2))
    return round(total / (n * (n - 1) / 2), 3)

def compute_gamma(services: list, tau_matrix: pd.DataFrame) -> Dict[str, float]:
    pcoh_val = process_cohesion(services, tau_matrix)
    pcoup_val = process_coupling(services, tau_matrix)
    gamma = round(pcoup_val / pcoh_val, 3) if pcoh_val > 0 else 0.0
    return {"pcoh": pcoh_val, "pcoup": pcoup_val, "gamma": gamma}

def are_services_connected(service_A_tasks: set, service_B_tasks: set, flow_map: dict) -> bool:
    for t_a in service_A_tasks:
        if not flow_map.get(t_a, set()).isdisjoint(service_B_tasks): return True
    for t_b in service_B_tasks:
        if not flow_map.get(t_b, set()).isdisjoint(service_A_tasks): return True
    return False

def aggregate_services_flow_aware(candidate_services: list, tau_matrix: pd.DataFrame, flow_map: dict, penalty_weight: float = 1000.0):
    sigma = [ {"service_id": s["service_id"], "tasks": set(s["tasks"])} for s in candidate_services ]
    gamma_values = []
    merge_history = []
    
    metrics = compute_gamma(sigma, tau_matrix)
    gamma_values.append(metrics["gamma"])
    
    iteration = 1
    while len(sigma) > 1:
        best_score = None
        best_real_gamma = None
        best_pair_indices = None
        best_new_service = None
        
        for i in range(len(sigma)):
            for j in range(i + 1, len(sigma)):
                Si, Sj = sigma[i], sigma[j]
                merged_tasks = Si["tasks"].union(Sj["tasks"])
                temp_sigma = [s for k, s in enumerate(sigma) if k not in (i, j)]
                temp_sigma.append({"service_id": "TEMP", "tasks": merged_tasks})
                
                metrics = compute_gamma(temp_sigma, tau_matrix)
                connected = are_services_connected(Si["tasks"], Sj["tasks"], flow_map)
                current_score = metrics["gamma"] + (0.0 if connected else penalty_weight)
                
                if best_score is None or current_score < best_score:
                    best_score = current_score
                    best_real_gamma = metrics["gamma"]
                    best_pair_indices = (i, j)
                    new_id = f"S_{Si['service_id'][2:]}_{Sj['service_id'][2:]}"
                    best_new_service = {"service_id": new_id, "tasks": merged_tasks}
        
        if best_pair_indices is None: break
        
        idx_i, idx_j = best_pair_indices
        left_srv, right_srv = sigma[idx_i], sigma[idx_j]
        sigma.pop(max(idx_i, idx_j)); sigma.pop(min(idx_i, idx_j))
        sigma.append(best_new_service)
        
        gamma_values.append(best_real_gamma)
        
        merge_history.append({
            "iteration": iteration,
            "left_id": left_srv["service_id"], 
            "right_id": right_srv["service_id"],
            "new_service_id": best_new_service["service_id"], 
            "new_tasks": set(best_new_service["tasks"]),
            "gamma": best_real_gamma
        })
        iteration += 1
        
    return sigma, gamma_values, merge_history

# -----------------------------
# Reconstruction & BPMN Generation
# -----------------------------

def reconstruct_best_topology(initial_candidates, merge_history, best_iteration_index):
    """
    Ricostruisce la topologia applicando i merge uno alla volta e stampando cosa succede.
    """
    
    # 1. Stato Iniziale (Iterazione 0)
    current_services = [
        {"service_id": s["service_id"], "tasks": set(s["tasks"])} 
        for s in initial_candidates
    ]

    # Se l'ottimo è 0, finiamo qui
    if best_iteration_index == 0:
        return current_services

    # 2. Applica i merge passo dopo passo
    steps_to_apply = merge_history[:best_iteration_index]
    
    for i, m in enumerate(steps_to_apply, 1):
        left_id = m["left_id"]
        right_id = m["right_id"]
        new_srv_id = m["new_service_id"]
        new_tasks = m["new_tasks"]
        
        # Rimuovi i vecchi
        before_count = len(current_services)
        current_services = [s for s in current_services if s["service_id"] not in (left_id, right_id)]
        
        # Aggiungi il nuovo
        current_services.append({"service_id": new_srv_id, "tasks": new_tasks})
        
    return current_services


def add_groups_to_bpmn(original_xml_path, output_xml_path, services, tasks_obj_list):
    try:
        tree = ET.parse(original_xml_path)
        root = tree.getroot()
        
        namespaces = {
            'bpmn': 'http://www.omg.org/spec/BPMN/20100524/MODEL',
            'bpmndi': 'http://www.omg.org/spec/BPMN/20100524/DI',
            'dc': 'http://www.omg.org/spec/DD/20100524/DC',
            'di': 'http://www.omg.org/spec/DD/20100524/DI',
            'custom': 'http://example.com/custom'
        }
        for prefix, uri in namespaces.items():
            ET.register_namespace(prefix, uri)

        # 1. Trova collaboration o process (padre dei group)
        collaboration = root.find('.//bpmn:collaboration', namespaces)
        process = root.find('.//bpmn:process', namespaces)
        target_element = collaboration if collaboration is not None else process

        if target_element is None:
            print("ERRORE: Impossibile trovare 'collaboration' o 'process'.")
            return False

        # 2. Rimuovi TUTTI i group logici
        for g in list(target_element.findall('bpmn:group', namespaces)):
            target_element.remove(g)

        # 3. Trova il piano grafico
        plane = root.find('.//bpmndi:BPMNPlane', namespaces)
        if plane is None:
            print("ERRORE: Impossibile trovare 'BPMNPlane'.")
            return False

        # 4. Rimuovi TUTTE le shape associate ai group
        for shape in list(plane.findall('bpmndi:BPMNShape', namespaces)):
            bpmn_el = shape.get("bpmnElement", "")
            if bpmn_el.startswith("Group_"):
                plane.remove(shape)

        # 5. Rimuovi anche le category dei group
        for cat in list(root.findall('.//bpmn:category', namespaces)):
            root.remove(cat)

        logic_to_xml_id = {}
        for t in tasks_obj_list:
            clean = t.original_id
            if clean.startswith("AS_"): clean = clean[3:]
            logic_to_xml_id[t.id] = clean

        definitions = root
        
        collaboration = root.find('.//bpmn:collaboration', namespaces)
        process = root.find('.//bpmn:process', namespaces)
        
        if collaboration is not None:
            target_element = collaboration
        elif process is not None:
            target_element = process
        else:
            print("ERRORE: Impossibile trovare 'collaboration' o 'process' nel BPMN.")
            return False

        plane = root.find('.//bpmndi:BPMNPlane', namespaces)
        if plane is None:
            print("ERRORE: Impossibile trovare 'BPMNPlane'.")
            return False

        groups_created = 0

        for srv in services:
            srv_id = srv["service_id"]
            tasks = srv["tasks"]
            
            min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')
            found_any = False
            
            for t_logic_id in tasks:
                xml_id = logic_to_xml_id.get(t_logic_id)
                if not xml_id: continue
                
                shape = plane.find(f".//bpmndi:BPMNShape[@bpmnElement='{xml_id}']", namespaces)
                if shape is not None:
                    bounds = shape.find('dc:Bounds', namespaces)
                    if bounds is not None:
                        x = float(bounds.get('x'))
                        y = float(bounds.get('y'))
                        w = float(bounds.get('width'))
                        h = float(bounds.get('height'))
                        min_x = min(min_x, x)
                        min_y = min(min_y, y)
                        max_x = max(max_x, x + w)
                        max_y = max(max_y, y + h)
                        found_any = True
            
            if not found_any:
                continue

            padding = 30
            g_x = min_x - padding
            g_y = min_y - padding
            g_w = (max_x - min_x) + (padding * 2)
            g_h = (max_y - min_y) + (padding * 2)

            cat_id = f"Category_{srv_id}"
            cat_val_id = f"CategoryValue_{srv_id}"
            
            existing_cat = definitions.find(f".//bpmn:category[@id='{cat_id}']", namespaces)
            if existing_cat is None:
                category = ET.SubElement(definitions, f"{{{namespaces['bpmn']}}}category")
                category.set("id", cat_id)
                cat_val = ET.SubElement(category, f"{{{namespaces['bpmn']}}}categoryValue")
                cat_val.set("id", cat_val_id)
                cat_val.set("value", srv_id)
            else:
                cat_val = existing_cat.find(f"{{{namespaces['bpmn']}}}categoryValue", namespaces)
                cat_val_id = cat_val.get("id")

            group_id = f"Group_{srv_id}"
            group = ET.SubElement(target_element, f"{{{namespaces['bpmn']}}}group")
            group.set("id", group_id)
            group.set("categoryValueRef", cat_val_id)

            group_shape = ET.SubElement(plane, f"{{{namespaces['bpmndi']}}}BPMNShape")
            group_shape.set("id", f"Shape_{group_id}")
            group_shape.set("bpmnElement", group_id)
            
            bounds_el = ET.SubElement(group_shape, f"{{{namespaces['dc']}}}Bounds")
            bounds_el.set("x", str(g_x))
            bounds_el.set("y", str(g_y))
            bounds_el.set("width", str(g_w))
            bounds_el.set("height", str(g_h))
            

            groups_created += 1

        tree.write(output_xml_path, encoding='utf-8', xml_declaration=True)
        return True

    except Exception as e:
        print(f"Errore generazione XML: {e}")
        import traceback
        traceback.print_exc()
        return False

# -----------------------------
# NEW: Generate All BPMN Variants
# -----------------------------
def generate_all_bpmn_variants(input_txt_path, original_bpmn_path, tasks_obj_list):
    """
    Genera tutti i possibili BPMN variants (uno per ogni iterazione).
    Ritorna una lista di dict con {iteration, gamma, xml, num_services}.
    """
    try:
        with open(input_txt_path, "r", encoding="utf-8") as f:
            text = f.read()
        
        # Parsing
        as_entries = parse_atomic_services(text)
        tasks = build_tasks(as_entries)
        adj = parse_workflow_graph_from_txt(text, tasks)
        flow = simplify_workflow(adj, tasks)
        V = value_analysis(tasks)
        tau = task_dependency_matrix(tasks)
        
        # Identificazione Iniziale
        candidates_0 = value_based_service_identification_flow_aware(tasks, tau, V, flow)
        
        # Aggregazione
        _, gamma_vals, history = aggregate_services_flow_aware(candidates_0, tau, flow)
        
        # Genera un BPMN per ogni iterazione
        variants = []
        for i in range(len(gamma_vals)):
            optimal_services = reconstruct_best_topology(candidates_0, history, i)
            
            # Crea file temporaneo per questo variant
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.xml', mode='w', encoding='utf-8')
            temp_path = temp_file.name
            temp_file.close()
            
            # Genera il BPMN
            success = add_groups_to_bpmn(original_bpmn_path, temp_path, optimal_services, tasks_obj_list)
            
            if success:
                with open(temp_path, 'r', encoding='utf-8') as f:
                    xml_content = f.read()
                
                variants.append({
                    'iteration': i,
                    'gamma': gamma_vals[i],
                    'xml': xml_content,
                    'num_services': len(optimal_services)
                })
            
            # Rimuovi file temporaneo
            try:
                os.remove(temp_path)
            except:
                pass
        
        return variants, gamma_vals
        
    except Exception as e:
        print(f"Error in generate_all_bpmn_variants: {e}")
        import traceback
        traceback.print_exc()
        return [], []

# -----------------------------
# Plotting Helpers
# -----------------------------
def build_linkage_from_history(tasks, initial_candidate_services, merge_history):
    task_ids = sorted([t.id for t in tasks])
    n_leaves = len(task_ids)
    leaf_index = {tid: idx for idx, tid in enumerate(task_ids)}
    linkage_rows = []
    current_cluster_idx = n_leaves
    cluster_sizes = {i: 1 for i in range(n_leaves)}
    service_cluster_idx = {}

    for s in initial_candidate_services:
        sid = s["service_id"]
        tasks_in_service = sorted(list(s["tasks"]))
        if not tasks_in_service: continue
        
        if len(tasks_in_service) == 1:
            service_cluster_idx[sid] = leaf_index[tasks_in_service[0]]
        else:
            rep_idx = leaf_index[tasks_in_service[0]]
            for k in range(1, len(tasks_in_service)):
                other_idx = leaf_index[tasks_in_service[k]]
                new_count = cluster_sizes.get(rep_idx, 1) + cluster_sizes.get(other_idx, 1)
                linkage_rows.append([float(rep_idx), float(other_idx), 0.1, float(new_count)])
                cluster_sizes[current_cluster_idx] = new_count
                rep_idx = current_cluster_idx
                current_cluster_idx += 1
            service_cluster_idx[sid] = rep_idx

    assigned = set()
    for s in initial_candidate_services: assigned.update(s["tasks"])
    for tid in task_ids:
        if tid not in assigned:
            service_cluster_idx[f"S_{tid}"] = leaf_index[tid]

    for m in merge_history:
        left_id, right_id = m["left_id"], m["right_id"]
        if left_id in service_cluster_idx and right_id in service_cluster_idx:
            l_idx, r_idx = service_cluster_idx[left_id], service_cluster_idx[right_id]
            height = float(m["iteration"])
            new_cnt = cluster_sizes.get(l_idx,1) + cluster_sizes.get(r_idx,1)
            linkage_rows.append([float(l_idx), float(r_idx), height, float(new_cnt)])
            service_cluster_idx[m["new_service_id"]] = current_cluster_idx
            cluster_sizes[current_cluster_idx] = new_cnt
            current_cluster_idx += 1
            
    return np.array(linkage_rows, dtype=float), task_ids

def plot_single_dendrogram(tasks, initial_services, history, filename, cut_height=None):
    plt.figure(figsize=(16, 14)) 

    task_name_map = {t.id: t.name for t in tasks}
    Z, labels = build_linkage_from_history(tasks, initial_services, history)
    pretty_labels = [task_name_map.get(tid, tid) for tid in labels]

    Z = np.nan_to_num(Z, nan=0.0)
    
    hierarchy.dendrogram(
        Z,
        labels=pretty_labels,
        leaf_rotation=90,
        leaf_font_size=9
    )

    if cut_height is not None:
        plt.axhline(y=cut_height + 0.5, c='r', ls='--', label=f'Best Cut (Iter {cut_height})')
        plt.legend()

    plt.title("Service Identification Dendrogram")

    ax = plt.gca()
    ax.yaxis.set_major_locator(MultipleLocator(1))

    plt.tight_layout()
    
    plt.subplots_adjust(bottom=0.4) 

    if filename:
        plt.savefig(filename, dpi=300, bbox_inches='tight')

    plt.close()

def plot_gamma_trend(gamma_values, filename):
    plt.figure(figsize=(10, 6))
    plt.plot(range(len(gamma_values)), gamma_values, marker='o')
    if gamma_values:
        min_g = min(gamma_values)
        min_idx = gamma_values.index(min_g)
        plt.scatter(min_idx, min_g, c='r', s=100, zorder=5, label='Min Gamma')
        plt.legend()
    plt.yscale("log")
    plt.title("Gamma Trend")
    plt.xlabel("Iteration")
    plt.tight_layout()
    if filename: plt.savefig(filename)
    plt.close()

# -----------------------------
# MAIN ENTRY POINT
# -----------------------------
def generate_images(input_txt_path, output_dendrogram_path, output_gamma_path, 
                    original_bpmn_path=None, output_bpmn_path=None):
    try:
        # 1. Parsing
        with open(input_txt_path, "r", encoding="utf-8") as f: text = f.read()
        as_entries = parse_atomic_services(text)
        tasks = build_tasks(as_entries)
        adj = parse_workflow_graph_from_txt(text, tasks)
        flow = simplify_workflow(adj, tasks)
        V = value_analysis(tasks)
        tau = task_dependency_matrix(tasks)
        
        # 2. Identificazione Iniziale
        candidates_0 = value_based_service_identification_flow_aware(tasks, tau, V, flow)

        # 3. Aggregazione
        _, gamma_vals, history = aggregate_services_flow_aware(candidates_0, tau, flow)
        
        # 4. Scelta Ottimo
        min_gamma = min(gamma_vals)
        best_iter_index = gamma_vals.index(min_gamma)
        
        # 5. Generazione Immagini
        plot_single_dendrogram(tasks, candidates_0, history, output_dendrogram_path, cut_height=best_iter_index)
        plot_gamma_trend(gamma_vals, output_gamma_path)
        
        # 6. BPMN Finale
        if original_bpmn_path and output_bpmn_path:
            # Qui ricostruiamo esattamente la situazione all'iterazione scelta
            optimal_services = reconstruct_best_topology(candidates_0, history, best_iter_index)
            
            add_groups_to_bpmn(original_bpmn_path, output_bpmn_path, optimal_services, tasks)

        return True

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

# Esempio di utilizzo da riga di comando
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <input_txt> [bpmn_in] [bpmn_out]")
    else:
        txt = sys.argv[1]
        bpmn_in = sys.argv[2] if len(sys.argv) > 2 else None
        bpmn_out = sys.argv[3] if len(sys.argv) > 3 else "output_grouped.bpmn"
        
        generate_images(txt, "dendrogram.png", "gamma.png", bpmn_in, bpmn_out)