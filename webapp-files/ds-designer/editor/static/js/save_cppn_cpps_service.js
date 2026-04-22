import { loadAvailableServices , ensureDiagramSaved} from './editor.js';

function addGroupExtension(groupElement, values) {
  const modeling = bpmnModeler.get('modeling');
  const moddle = bpmnModeler.get('moddle');

  const extensionProps = {
    groupType: values.groupType,
    name: values.name,
    description: values.description,
    workflowType: values.workflowType,
    members: values.components.map(c => c.id).join(','),
    gdprMap: JSON.stringify(values.gdprMap)
  };

  if (values.groupType === 'CPPN' && Array.isArray(values.actors)) {
    extensionProps.actors = values.actors.join(',');
  }
  
  if (values.groupType === 'CPPN' && values.businessGoal) {
    extensionProps.businessGoal = values.businessGoal;
  }

  if (values.groupType === 'CPPS' && typeof values.actor === 'string') {
    extensionProps.actor = values.actor;
  }

  const extension = moddle.create('custom:GroupExtension', extensionProps);

  const extensionElements = moddle.create('bpmn:ExtensionElements', {
    values: [extension]
  });

  modeling.updateProperties(groupElement, {
    extensionElements: extensionElements
  });
}


async function saveCompositeService() {

  if (!currentElement || currentElement.type !== 'bpmn:Group') {
    alert("No group selected.");
    return;
  }

  const name = document.getElementById('groupName').value.trim();
  const description = document.getElementById('groupDescription').value.trim();
  const groupType = document.getElementById('groupTypeSelect').value;
  const workflowType = document.getElementById('workflowTypeSelect').value;
  const actor = document.getElementById('singleActor')?.value.trim() || '';
  const actors = document.getElementById('actorsInvolved')?.value.trim() || '';
  const businessGoal = document.getElementById('businessGoal')?.value.trim() || '';

  const gdprMap = {};
  const gdprMapContainer = document.getElementById('gdprMapContainer');
  [...gdprMapContainer.children].forEach(row => {
    const actorInput = row.querySelector('input');
    const roleSelect = row.querySelector('select');
    const actorName = actorInput?.value.trim();
    const role = roleSelect?.value.trim();
    if (actorName && role) {
      gdprMap[actorName] = role;
    }
  });

  const endpointRows = document.querySelectorAll('#endpointsContainer > div');
  const endpoints = Array.from(endpointRows).map(row => {
    const method = row.querySelector('select')?.value || '';
    const url = row.querySelector('input')?.value.trim() || '';
    return { method, url };
  });

  const { components, workflow } = detectGroupMembers(currentElement);
  console.log(" Detected components:", components);

  if (!name) {
    alert("Composite service's name is mandatory!");
    return;
  }

  // Salvo il diagramma (se non già fatto)
  const diagramId = await ensureDiagramSaved();
  if (!diagramId) {
    alert("Diagram not saved.");
    return;
  }
  window.diagramId = diagramId;

  // Aggiungi extension custom al BPMN
  console.log(" Before extension:", currentElement.businessObject.extensionElements);
  addGroupExtension(currentElement, {
    groupType,
    name,
    description,
    workflowType,
    components,
    actors: groupType === 'CPPN' ? actors.split(',').map(a => a.trim()) : [],
    actor: groupType === 'CPPS' ? actor : '',
    gdprMap,
    businessGoal
  });
  console.log("✅ After extension:", currentElement.businessObject.extensionElements);

  const { xml } = await bpmnModeler.saveXML({ format: true });
  console.log("📝 Current BPMN XML:\n", xml);

  const payload = {
    diagram_id: diagramId,
    group_id: currentElement.id,
    name,
    description,
    workflow_type: workflowType,
    components
  };
  payload.workflow = workflow; 

  try {
    let result;
    const csrftoken = getCookie('csrftoken');

    if (groupType === 'CPPN') {
      payload.group_type = 'CPPN';
      payload.actors = actors.split(',').map(s => s.trim());
      payload.gdpr_map = gdprMap;
      payload.business_goal = businessGoal;
      
      console.log('WF nodes:', Object.keys(workflow));
      console.log('Payload CPPN:', payload);

      result = await fetch('/editor/api/save-cppn-service/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrftoken
        },
        body: JSON.stringify(payload)
      });
    } else {
      payload.group_type = 'CPPS';
      payload.owner = actor;
      payload.endpoints = endpoints;
      payload.workflow = workflow;

      console.log("Workflow detected:", workflow);

      result = await fetch('/editor/api/save-cpps-service/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrftoken
        },
        body: JSON.stringify(payload)
      });
    }

    const resData = await result.json();

    if (!result.ok) throw new Error(resData.error || "Server error");

    console.log(`✅ ${groupType} saved successfully:`, resData);
    bootstrap.Modal.getInstance(document.getElementById('groupTypeModal')).hide();
    await loadAvailableServices();

  } catch (err) {
    console.error(`❌ Error saving ${groupType}:`, err);
    alert(`Error saving ${groupType}: ${err.message}`);
  }
}

function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
      const trimmed = cookie.trim();
      if (trimmed.startsWith(name + '=')) {
        cookieValue = decodeURIComponent(trimmed.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}


async function saveCPPNService(payload) {
  const csrftoken = getCookie('csrftoken');

  const response = await fetch('/editor/api/save-cppn-service/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrftoken
    },
    body: JSON.stringify(payload)
  });

  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Error saving CPPN');
  return result;
}

async function saveCPPSService(payload) {
  const csrftoken = getCookie('csrftoken');

  const response = await fetch('/editor/api/save-cpps-service/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrftoken
    },
    body: JSON.stringify(payload)
  });

  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Error saving CPPS');
  return result;
}

function detectGroupMembers(groupElement) {
  const elementRegistry = bpmnModeler.get('elementRegistry');
  const canvas = bpmnModeler.get('canvas');

  const groupBBox = canvas.getAbsoluteBBox(groupElement);

  const isInside = (el) => {
    const b = canvas.getAbsoluteBBox(el);
    return (
      b.x >= groupBBox.x &&
      b.y >= groupBBox.y &&
      b.x + b.width  <= groupBBox.x + groupBBox.width &&
      b.y + b.height <= groupBBox.y + groupBBox.height
    );
  };

  const isEventType = (t = '') =>
    t.startsWith('bpmn:StartEvent') ||
    t.startsWith('bpmn:EndEvent') ||
    t.startsWith('bpmn:Intermediate');

  // --- COMPONENTS -----------------------------------------------------------

  const componentsMap = new Map(); // id -> {id,type[,targets]}
  const addComponent = (c) => { if (!componentsMap.has(c.id)) componentsMap.set(c.id, c); };

  // 1) Atomic (Task-like)
  elementRegistry
    .filter(el => ['bpmn:Task','bpmn:CallActivity','bpmn:SubProcess'].includes(el.type))
    .forEach(el => {
      if (isInside(el)) addComponent({ id: el.id, type: 'Atomic' });
    });

  // 2) Gateways
  const gwTypes = ['bpmn:ParallelGateway', 'bpmn:ExclusiveGateway', 'bpmn:InclusiveGateway'];
  elementRegistry
    .filter(el => gwTypes.includes(el.type))
    .forEach(gw => {
      if (!isInside(gw)) return;

      const outgoingTargets = (gw.outgoing || [])
        .map(f => f.target?.id)
        .filter(Boolean);

      // tieni solo target interni e non-evento
      const filteredTargets = (gw.outgoing || [])
        .filter(f => !!f.target && isInside(f.target) && !isEventType(f.target.type))
        .map(f => f.target.id);

      addComponent({
        id: gw.id,
        type: gw.type.replace('bpmn:', ''),
        targets: filteredTargets.length ? filteredTargets : outgoingTargets
      });
    });

  // 3) CPPS annidati (altri Group dentro il Group selezionato)
  const nestedGroups = elementRegistry
    .filter(el => el.type === 'bpmn:Group' && el.id !== groupElement.id && isInside(el));

  nestedGroups.forEach(g => {
    // consideralo CPPS solo se l’estensione lo dichiara tale
    const bo = g.businessObject;
    const ext = bo?.extensionElements?.values?.find(v => v.$type === 'custom:GroupExtension');
    const gType = ext?.groupType || ext?.group_type || null;
    if (gType === 'CPPS') addComponent({ id: g.id, type: 'CPPS' });
  });

  // --- WORKFLOW (edges) -----------------------------------------------------

  const workflow = {};
  const pushEdge = (srcId, tgtId) => {
    if (!srcId || !tgtId || srcId === tgtId) return; // no self-loop
    if (!workflow[srcId]) workflow[srcId] = [];
    if (!workflow[srcId].includes(tgtId)) workflow[srcId].push(tgtId);
  };

  // A) SequenceFlow interni al group
  elementRegistry
    .filter(el => el.type === 'bpmn:SequenceFlow')
    .forEach(flow => {
      const s = flow.source, t = flow.target;
      if (!s || !t) return;

      // consideriamo solo archi con sorgente dentro il group
      if (!isInside(s)) return;

      // escludi eventi come source/target
      if (isEventType(s.type) || isEventType(t.type)) return;

      // target deve essere dentro il group (per CPPN non vogliamo uscire)
      if (!isInside(t)) return;

      pushEdge(s.id, t.id);
    });

  // B) MessageFlow: includi flussi tra attori (anche fuori→dentro)
  elementRegistry
    .filter(el => el.type === 'bpmn:MessageFlow')
    .forEach(flow => {
      const s = flow.sourceRef || flow.source; // bpmn-js a volte usa sourceRef
      const t = flow.targetRef || flow.target;
      if (!s || !t) return;

      // includi se almeno il target è dentro il group (il tuo caso Customer → Production Leader)
      const targetInside = elementRegistry.get(t.id) ? isInside(elementRegistry.get(t.id)) : false;
      const sourceInside = elementRegistry.get(s.id) ? isInside(elementRegistry.get(s.id)) : false;

      if (!targetInside && !sourceInside) return; // irrilevante per il group

      // ignora eventi
      const sType = elementRegistry.get(s.id)?.type || '';
      const tType = elementRegistry.get(t.id)?.type || '';
      if (isEventType(sType) || isEventType(tType)) return;

      pushEdge(s.id, t.id);

      // se sia sorgente che target sono dentro, manteniamo solo l’edge normale;
      // se è fuori→dentro, l’edge sarà solo message-flow (src fuori, tgt dentro)
    });

  // --- OUTPUT ---------------------------------------------------------------

  const components = Array.from(componentsMap.values());

  return { components, workflow };
}

function findParentGroup(innerGroup) {
  const elementRegistry = bpmnModeler.get('elementRegistry');
  const canvas = bpmnModeler.get('canvas');
  const innerBBox = canvas.getAbsoluteBBox(innerGroup);

  const groups = elementRegistry.filter(el =>
    el.type === 'bpmn:Group' && el.id !== innerGroup.id
  );

  return groups.find(g => {
    const outerBBox = canvas.getAbsoluteBBox(g);
    return (
      innerBBox.x >= outerBBox.x &&
      innerBBox.y >= outerBBox.y &&
      innerBBox.x + innerBBox.width <= outerBBox.x + outerBBox.width &&
      innerBBox.y + innerBBox.height <= outerBBox.y + outerBBox.height
    );
  });
}

document.getElementById('save-composite-button')
  .addEventListener('click', saveCompositeService);