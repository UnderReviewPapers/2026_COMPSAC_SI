import xml.etree.ElementTree as ET
import json
import os
import sys 

NAMESPACES = {
    'bpmn': 'http://www.omg.org/spec/BPMN/20100524/MODEL',
    'custom': 'http://example.com/custom',
    'xsi': 'http://www.w3.org/2001/XMLSchema-instance'
}

def get_tag_name(element):
    return element.tag.split('}')[-1] if '}' in element.tag else element.tag

def parse_bpmn_flow(root):
    elements_map = {} 
    flow_nodes = root.findall('.//*[@id]')
    
    for node in flow_nodes:
        node_id = node.get('id')
        node_type = get_tag_name(node)
        
        if node_type in ['definitions', 'collaboration', 'process', 'participant', 'messageFlow', 'sequenceFlow']:
            continue

        name = node.get('name')
        owner = "Unknown"
        extension = node.find('bpmn:extensionElements/custom:atomicExtension/custom:owner', NAMESPACES)
        if extension is not None and extension.text:
            owner = extension.text
        
        if not name:
            if 'Gateway' in node_type: name = "Decision/Gateway"
            elif 'StartEvent' in node_type: name = "Start"
            elif 'EndEvent' in node_type: name = "End"
            else: name = f"Node"
        
        elements_map[node_id] = {'name': name.replace('\n', ' '), 'type': node_type, 'owner': owner}

    flows = []
    for seq in root.findall('.//bpmn:sequenceFlow', NAMESPACES):
        source_id = seq.get('sourceRef')
        target_id = seq.get('targetRef')
        flow_name = seq.get('name', '') 
        
        if source_id in elements_map and target_id in elements_map:
            src = elements_map[source_id]
            tgt = elements_map[target_id]
            src_lbl = f"{src['name']} ({source_id})" + (f" ({src['owner']})" if src['owner'] != 'Unknown' else "")
            tgt_lbl = f"{tgt['name']} ({target_id})" + (f" ({tgt['owner']})" if tgt['owner'] != 'Unknown' else "")
            label = f" --[{flow_name}]--> " if flow_name else " --> "
            flows.append(f"[{src['type']}] {src_lbl}{label}[{tgt['type']}] {tgt_lbl}")

    for msg in root.findall('.//bpmn:messageFlow', NAMESPACES):
        source_id = msg.get('sourceRef')
        target_id = msg.get('targetRef')
        if source_id in elements_map and target_id in elements_map:
            src = elements_map[source_id]
            tgt = elements_map[target_id]
            src_lbl = f"{src['name']} ({source_id})" + (f" ({src['owner']})" if src['owner'] != 'Unknown' else "")
            tgt_lbl = f"{tgt['name']} ({target_id})" + (f" ({tgt['owner']})" if tgt['owner'] != 'Unknown' else "")
            flows.append(f"[{src['type']}] {src_lbl} ==(MESSAGE)==> [{tgt['type']}] {tgt_lbl}")

    return flows

def parse_bpmn_elements(file_content):
    atomic_services = []
    cpps_services = []
    cppn_services = []
    workflow_lines = []

    try:
        root = ET.fromstring(file_content)
        # PARSING SERVIZI ATOMICI
        for task in root.findall('.//bpmn:task', NAMESPACES):
            task_id = task.get('id')
            task_name = task.get('name')
            atomic_extension = task.find('bpmn:extensionElements/custom:atomicExtension', NAMESPACES)
            if atomic_extension is not None:
                atomic_type = atomic_extension.find('custom:atomicType', NAMESPACES)
                input_params = atomic_extension.find('custom:inputParams', NAMESPACES)
                output_params = atomic_extension.find('custom:outputParams', NAMESPACES)
                method = atomic_extension.find('custom:method', NAMESPACES)
                url = atomic_extension.find('custom:url', NAMESPACES)
                owner = atomic_extension.find('custom:owner', NAMESPACES)
                
                p_asi_name = task_name if task_name else 'N/A'
                p_asi_method = method.text if method is not None else 'N/A'
                p_asi_url = url.text if url is not None else 'N/A'
                p_asi_owner = owner.text if owner is not None else 'N/A'
                in_asi = [param.strip() for param in input_params.text.split(',')] if (input_params is not None and input_params.text) else ['N/A']
                out_asi = [param.strip() for param in output_params.text.split(',')] if (output_params is not None and output_params.text) else ['N/A']
                t_asi = atomic_type.text if atomic_type is not None else 'N/A'

                atomic_services.append({
                    'id': task_id,
                    'P_ASi': {'name': p_asi_name, 'method': p_asi_method, 'URL': p_asi_url, 'owner': p_asi_owner},
                    'IN_ASi': in_asi, 'OUT_ASi': out_asi, 'T_ASi': t_asi
                })
        
        # PARSING CPPS e CPPN
        for group in root.findall('.//bpmn:group', NAMESPACES):
            group_extension = group.find('bpmn:extensionElements/custom:groupExtension', NAMESPACES)
            if group_extension is not None:
                group_type = group_extension.find('custom:groupType', NAMESPACES)
                if group_type is None: continue
                group_id = group.get('id')
                name = group_extension.find('custom:name', NAMESPACES)
                description = group_extension.find('custom:description', NAMESPACES)
                workflow_type = group_extension.find('custom:workflowType', NAMESPACES)
                members = group_extension.find('custom:members', NAMESPACES)
                actor_or_owner = group_extension.find('custom:actor', NAMESPACES)
                actors = group_extension.find('custom:actors', NAMESPACES)
                gdpr_map = group_extension.find('custom:gdprMap', NAMESPACES)
                business_goal = group_extension.find('custom:businessGoal', NAMESPACES)
                current_group_type = group_type.text
                members_list = [m.strip() for m in members.text.split(',')] if (members is not None and members.text) else []
                actors_list = [a.strip() for a in actors.text.split(',')] if (actors is not None and actors.text) else []
                gdpr_responsibilities = {}
                if gdpr_map is not None and gdpr_map.text:
                    try: gdpr_responsibilities = json.loads(gdpr_map.text)
                    except: gdpr_responsibilities = {}

                if current_group_type == 'CPPS':
                    cpps_services.append({
                        'id': group_id, 'S_j': members_list,
                        'W_CSj': workflow_type.text if workflow_type is not None else 'N/A',
                        'O_CSj': actor_or_owner.text if actor_or_owner is not None else 'N/A',
                        'P_CSj': {'name': name.text if name else 'N/A', 'description': description.text if description else 'N/A', 'gdprMap': gdpr_responsibilities}
                    })
                elif current_group_type == 'CPPN':
                    cppn_services.append({
                        'id': group_id, 'S_k': members_list,
                        'W_NSk': workflow_type.text if workflow_type is not None else 'N/A',
                        'A_NSk': actors_list, 'G_NSk': gdpr_responsibilities,
                        'P_NSk': {'name': name.text if name else 'N/A', 'description': description.text if description else 'N/A', 'businessGoal': business_goal.text if business_goal else 'N/A'}
                    })
        
        workflow_lines = parse_bpmn_flow(root)
    except Exception as e:
        print(f"Errore durante il parsing: {e}")
        return None, None, None, None
        
    return atomic_services, cpps_services, cppn_services, workflow_lines

def run_parser(input_path, output_path):
    """
    Legge il file BPMN da input_path e scrive il risultato parsato in output_path.
    Restituisce True se ha successo, False altrimenti.
    """
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            bpmn_content = f.read()
    except Exception as e:
        print(f"Errore lettura file: {e}")
        return False

    atomic_services, cpps_services, cppn_services, workflows = parse_bpmn_elements(bpmn_content)
    
    if atomic_services is None:
        return False

    try:
        with open(output_path, 'w', encoding='utf-8') as outfile:
            outfile.write("--- SERVIZI ATOMICI (AS) ---\n")
            for idx, s in enumerate(atomic_services):
                outfile.write(f"AS_{s['id']} = <P_AS{idx}={{name='{s['P_ASi']['name']}', method='{s['P_ASi']['method']}', URL='{s['P_ASi']['URL']}', owner='{s['P_ASi']['owner']}' }}, IN_AS{idx}={s['IN_ASi']}, OUT_AS{idx}={s['OUT_ASi']}, T_AS{idx}='{s['T_ASi']}'>\n")

            outfile.write("\n--- CPPS (CS) ---\n")
            if not cpps_services: outfile.write("(Nessun CPPS trovato)\n")
            for idx, s in enumerate(cpps_services):
                members_str = '{' + ','.join(f"'{m}'" for m in s['S_j']) + '}'
                gdpr_map_str = json.dumps(s['P_CSj'].get('gdprMap', {}))
                outfile.write(f"CS_{s['id']} = <{members_str}, W_CS{idx}='{s['W_CSj']}', O_CS{idx}='{s['O_CSj']}', P_CS{idx}={{name='{s['P_CSj']['name']}', description='{s['P_CSj']['description']}', gdprMap='{gdpr_map_str}'}}>\n")

            outfile.write("\n--- CPPN (NS) ---\n")
            if not cppn_services: outfile.write("(Nessun CPPN trovato)\n")
            for idx, s in enumerate(cppn_services):
                members_str = '{' + ','.join(f"'{m}'" for m in s['S_k']) + '}'
                actors_str = '{' + ','.join(f"'{a}'" for a in s['A_NSk']) + '}'
                gdpr_map_str = json.dumps(s['G_NSk'])
                outfile.write(f"NS_{s['id']} = <{members_str}, W_NS{idx}='{s['W_NSk']}', A_NS{idx}={actors_str}, G_NS{idx}='{gdpr_map_str}', P_NS{idx}={{name='{s['P_NSk']['name']}', description='{s['P_NSk']['description']}', businessGoal='{s['P_NSk']['businessGoal']}'}}>\n")

            outfile.write("\n--- FLUSSO DELLE ATTIVITÀ (WORKFLOW) ---\n")
            for line in workflows:
                outfile.write(f"{line}\n")
        return True
    except Exception as e:
        print(f"Errore scrittura file: {e}")
        return False

# --- MAIN (Per esecuzione standalone) ---
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python parser.py <nome_file_bpmn>")
        sys.exit(1)
    
    bpmn_in = sys.argv[1]
    txt_out = f"{os.path.splitext(bpmn_in)[0]}_parsed.txt"
    if run_parser(bpmn_in, txt_out):
        print(f"Parsing completato: {txt_out}")
    else:
        print("Errore nel parsing.")