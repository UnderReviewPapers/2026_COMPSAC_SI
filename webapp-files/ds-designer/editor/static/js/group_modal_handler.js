function openGroupClassificationForm(element, existingData = null) {
  if (!element || !element.businessObject) return;

  currentElement = element;
  const bo = element.businessObject;

  let groupType = '';
  let name = '';
  let description = '';
  let workflowType = '';
  let singleActor = '';
  let actors = '';
  let gdprMap = {};
  let endpoints = [];
  let businessGoal = '';
  console.log('GDPR MAP detected:', gdprMap);


  //dati da MongoDB (API get_cppn_service o get_cpps_service)
  if (existingData) {
    groupType = existingData.group_type || 'CPPS';
    name = existingData.name || '';
    description = existingData.description || '';
    workflowType = existingData.workflow_type || '';
    singleActor = existingData.actor || existingData.owner || '';
    actors = (existingData.actors || []).join(', ');
    gdprMap = existingData.gdpr_map || {};
    endpoints = existingData.endpoints || [];
    businessGoal = existingData.business_goal || '';

  }

  // estensioni già salvate nel diagramma
  else if (bo.extensionElements?.values?.length) {
    const ext = bo.extensionElements.values.find(e => e.$type === 'custom:GroupExtension');
    if (ext) {
      groupType = ext.groupType || 'CPPS';
      name = ext.name || '';
      description = ext.description || '';
      workflowType = ext.workflowType || '';
      singleActor = ext.actor || '';
      actors = ext.actors || '';
      businessGoal = ext.businessGoal || '';
      try {
        gdprMap = typeof ext.gdprMap === 'string' ? JSON.parse(ext.gdprMap) : ext.gdprMap || {};
      } catch {
        gdprMap = {};
      }
      try {
        endpoints = typeof ext.endpoints === 'string' ? JSON.parse(ext.endpoints) : ext.endpoints || [];
      } catch {
        endpoints = [];
      }
    }
  }

  //fallback automatico basato su partecipanti
  if (!existingData && !bo.extensionElements?.values?.length) {
    const detectedParticipants = detectGroupParticipants(element);
    groupType = detectedParticipants.length === 1 ? 'CPPS' : 'CPPN';

    if (groupType === 'CPPN') {
      actors = detectedParticipants.join(', ');
      gdprMap = {};
      detectedParticipants.forEach(actor => {
        gdprMap[actor] = '';
      });
      workflowType = 'sequence';
    }

    if (groupType === 'CPPS' && detectedParticipants.length === 1) {
      singleActor = detectedParticipants[0];
    }
  }

  //Popola i campi della modale
  document.getElementById('groupTypeSelect').value = groupType;
  toggleCPPNFields();
  document.getElementById('workflowTypeSelect').value = workflowType || 'sequence';
  document.getElementById('groupDescription').value = description || '';
  document.getElementById('groupName').value = name || '';
  document.getElementById('singleActor').value = singleActor || '';
  document.getElementById('actorsInvolved').value = actors || '';

  document.getElementById('singleActor').readOnly = true;
  document.getElementById('actorsInvolved').readOnly = true;
  document.getElementById('businessGoal').value = businessGoal || '';


  //GDPR Map
  const gdprContainer = document.getElementById('gdprMapContainer');
  gdprContainer.innerHTML = '';
  if (groupType === 'CPPN') {
    if (gdprMap && typeof gdprMap === 'object') {
      for (const [actor, role] of Object.entries(gdprMap)) {
        addGdprRow(actor, role);
      }
    } else {
      populateGdprMappingFromActorsInvolved();
    }
  }

  const gdprNote = document.getElementById('gdprNote');
  if (groupType === 'CPPN' && gdprNote) {
    gdprNote.style.display = 'inline';
  } else if (gdprNote) {
    gdprNote.style.display = 'none';
  }

  // Endpoints (solo CPPS)
  const epContainer = document.getElementById('endpointsContainer');
  epContainer.innerHTML = '';
  if (groupType === 'CPPS' && Array.isArray(endpoints)) {
    endpoints.forEach(ep => addEndpointRow(ep.method, ep.url));
  }

  // Mostra la modale
  const modalEl = document.getElementById('groupTypeModal');

// Recupera l'istanza esistente se presente
let modalInstance = bootstrap.Modal.getInstance(modalEl);

// Se non esiste ancora, la crea e imposta listener una sola volta
if (!modalInstance) {
  modalInstance = new bootstrap.Modal(modalEl);

  // Aggiunge una sola volta il listener di "cleanup"
  modalEl.addEventListener('hidden.bs.modal', function () {
    // Rimuove eventuale overlay rimasto
    document.querySelector('.modal-backdrop')?.remove();
    // Rimuove la classe che blocca l'interazione
    document.body.classList.remove('modal-open');
    // Reset dei campi eventualmente necessario (opzionale)
  });
}

modalInstance.show();

}

function addEndpointRow(method = '', url = '') {
  const container = document.getElementById('endpointsContainer');
  const div = document.createElement('div');
  div.classList.add('d-flex', 'mb-2', 'gap-2');

  div.innerHTML = `
    <select class="form-select form-select-sm" style="width: 100px;">
      <option value="GET" ${method === 'GET' ? 'selected' : ''}>GET</option>
      <option value="POST" ${method === 'POST' ? 'selected' : ''}>POST</option>
      <option value="PUT" ${method === 'PUT' ? 'selected' : ''}>PUT</option>
      <option value="DELETE" ${method === 'DELETE' ? 'selected' : ''}>DELETE</option>
    </select>
    <input type="text" class="form-control form-control-sm" placeholder="Endpoint URL" value="${url}">
    <button class="btn btn-sm btn-outline-danger" onclick="this.parentElement.remove()">×</button>
  `;

  container.appendChild(div);
}

function addGdprRow(actor = '', role = '') {
  const container = document.getElementById('gdprMapContainer');
  const row = document.createElement('div');
  row.classList.add('d-flex', 'mb-2', 'gap-2');

  console.log('Adding GDPR row for:', actor, role);


  row.innerHTML = `
    <input type="text" class="form-control form-control-sm bg-light text-muted" value="${actor}" readonly>
    <select class="form-select form-select-sm" data-actor="${actor}">
      <option value="Data Controller" ${role === 'Data Controller' ? 'selected' : ''}>Data Controller</option>
      <option value="Data Processor" ${role === 'Data Processor' ? 'selected' : ''}>Data Processor</option>
      <option value="Data Subject" ${role === 'Data Subject' ? 'selected' : ''}>Data Subject</option>
      <option value="Supervisory Authority" ${role === 'Supervisory Authority' ? 'selected' : ''}>Supervisory Authority</option>
    </select>
  `;

  container.appendChild(row);
}

function toggleCPPNFields() {
  const type = document.getElementById('groupTypeSelect').value;

  const cppnFields = document.getElementById('cppnFields');
  const cppsActorField = document.getElementById('cppsActorField');
  const cppsEndpoints = document.getElementById('cppsEndpoints'); // aggiunto
  const businessGoalField = document.getElementById('cppnBusinessGoalField');

  if (cppnFields && cppsActorField && cppsEndpoints) {
    if (type === 'CPPN') {
      cppnFields.style.display = 'block';
      cppsActorField.style.display = 'none';
      cppsEndpoints.style.display = 'none'; // nasconde se non CPPS
      if (businessGoalField) businessGoalField.style.display = 'block';
    } else {
      cppnFields.style.display = 'none';
      cppsActorField.style.display = 'block';
      cppsEndpoints.style.display = 'block'; // mostra se CPPS
      if (businessGoalField) businessGoalField.style.display = 'none';
    }
  }
}



function detectGroupParticipants(groupElement) {
  const elementRegistry = bpmnModeler.get('elementRegistry');
  const canvas = bpmnModeler.get('canvas');
  const groupBBox = canvas.getAbsoluteBBox(groupElement);

  const participants = elementRegistry.filter(el => el.type === 'bpmn:Participant');

  const intersecting = participants.filter(part => {
    const partBBox = canvas.getAbsoluteBBox(part);
    return (
      groupBBox.x < partBBox.x + partBBox.width &&
      groupBBox.x + groupBBox.width > partBBox.x &&
      groupBBox.y < partBBox.y + partBBox.height &&
      groupBBox.y + groupBBox.height > partBBox.y
    );
  });

  
  console.log('Detected participants:', intersecting.map(getParticipantName));

  return intersecting.map(getParticipantName);
}


function getParticipantName(element) {
  return element.businessObject.name || '(no name)';
}


function populateGdprMappingFromActorsInvolved() {
  const gdprContainer = document.getElementById('gdprMapContainer');
  gdprContainer.innerHTML = '';
  console.log('ActorsInvolved value:', raw);


  const raw = document.getElementById('actorsInvolved').value;
  const actors = raw.split(',').map(a => a.trim()).filter(a => a.length > 0);

  actors.forEach(actor => addGdprRow(actor, ''));
}