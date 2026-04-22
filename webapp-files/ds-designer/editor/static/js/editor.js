export function getCookie(name) {
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

import CustomContextPadProvider from './CustomContextPadProvider.js';

//registro i miei tipi personalizzati definiti in custom-moddle.js
const bpmnModeler = new BpmnJS({
  container: '#canvas',
  moddleExtensions: {
    custom: customModdle
  },
  additionalModules: [
    CustomContextPadProvider
  ]
});

window.bpmnModeler = bpmnModeler;

document.addEventListener('DOMContentLoaded', async () => {
  loadAvailableServices();
  const params = new URLSearchParams(window.location.search);
  const id = params.get('id');

  if (id) {
    try {
      const res = await fetch(`/viewer/api/${id}/`);
      if (!res.ok) throw new Error("Diagram not found.");

      const data = await res.json();
      await openDiagram(data.xml_content);
      localStorage.setItem('diagramId', data.id);
      window.diagramId = data.id;
      localStorage.setItem('diagramId', data.id);
      window.diagramHasFinalName = true;
      
      console.log("Edit mode activated for:", data.name);
    } catch (err) {
      console.error("Error loading diagram:", err);
      alert("Impossible loading diagram to edit it.");
    }
  } else {
    console.log("New diagram (no id in URL)");
    resetDiagram(); // chiamato solo in modalità creazione da zero
  }
});



const emptyDiagram = `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                  xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                  xmlns:custom="http://example.com/custom"
                  id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_1" isExecutable="false"/>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_1"/>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>`;

async function openDiagram(xml) {
  try {
    await bpmnModeler.importXML(xml);
    bpmnModeler.get('canvas').zoom('fit-viewport');
  } catch (err) {
    console.error('Error opening diagram', err);
  }
}


async function saveDiagram() {
    try {
        const { xml } = await bpmnModeler.saveXML({ format: true });
        const csrftoken = getCookie('csrftoken');

        // Assicura che abbiamo già un diagramId (draft se necessario)
        const diagramId = await ensureDiagramSaved();

        let url = `/editor/api/save-diagram/${diagramId}/`;
        let method = 'PUT';
        let body = { xml_content: xml };

        if (!window.diagramHasFinalName) {
            const newName = prompt("Insert a name for the diagram:");
            if (!newName) return; // utente ha annullato
            body.name = newName;
            window.diagramHasFinalName = true;
            console.log(`Renaming diagram ${diagramId} to '${newName}'`);
        }

        const response = await fetch(url, {
            method,
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            },
            body: JSON.stringify(body)
        });

        const data = await response.json();
        if (response.ok) {
            alert("Diagram saved successfully!");
            window.diagramId = data.id;
            localStorage.setItem('diagramId', data.id);
        } else {
            alert("Error saving:\n" + JSON.stringify(data));
        }
    } catch (err) {
        console.error("Error saving diagram", err);
        alert("Error saving diagram.");
    }
}


let selectedElement = null;
const editButton = document.getElementById('edit-details-button');

bpmnModeler.get('eventBus').on('element.click', function (e) {
  const el = e.element;

  console.log("Selected element " + el.type);  

  if (el && (el.type === 'bpmn:Task' || el.type === 'bpmn:Group')) {
    selectedElement = el;
    editButton.classList.remove('d-none');  // Mostra bottone
  } else {
    selectedElement = null;
    editButton.classList.add('d-none');  // Nasconde bottone
  }

  loadDetailsFromMongo(el);
});


document.getElementById('edit-details-button').addEventListener('click', function() {
  if (!selectedElement) {
    alert('No item selected!');
    return;
  }

  if (selectedElement.type === 'bpmn:Task') {
    openAtomicServiceForm(selectedElement);
  } else if (selectedElement.type === 'bpmn:Group') {
  openGroupClassificationForm(
    selectedElement,
    selectedElement.businessObject.loadedData || null
  );
  } else {
    alert('Not editable doc!');
  }
});



function resetDiagram() {
  localStorage.removeItem('diagramId');
  delete window.diagramId;
  openDiagram(emptyDiagram);
}

let isGenerating = false;
let generationAbortController = null;
let originalGenerateLabel = null;

async function generateWorkflow() {
  const button = document.getElementById('generate-button');
  const spinner = document.getElementById('generate-spinner');

  if (!button) {
    return;
  }

  // Se sta già generando, tratta il click come annulla
  if (isGenerating) {
    console.log('Cancel requested');
    if (generationAbortController) {
      generationAbortController.abort();
    }
    return;
  }

  console.log('Generate button clicked');

  isGenerating = true;
  if (originalGenerateLabel === null) {
    originalGenerateLabel = button.innerHTML;
  }
  button.textContent = 'Cancel';
  if (spinner) {
    spinner.classList.remove('d-none');
  }

  const controller = new AbortController();
  generationAbortController = controller;

  try {
    const diagramId = await ensureDiagramSaved();
    const csrftoken = getCookie('csrftoken');

    console.log('Sending request to generate projects for diagram ID:', diagramId);
    const response = await fetch('/editor/api/generate-projects/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrftoken
      },
      body: JSON.stringify({ diagram_id: diagramId }),
      signal: controller.signal,
    });

    if (!response.ok) {
      let message = 'Error generating projects.';
      try {
        const errData = await response.json();
        if (errData && errData.error) {
          message = errData.error;
        }
      } catch (e) {}
      alert(message);
      return;
    }

    console.log('Receiving generated projects...');
    const blob = await response.blob();

    let filename = 'projects.zip';
    const disposition = response.headers.get('Content-Disposition');
    if (disposition) {
      const match = disposition.match(/filename="?([^";]+)"?/i);
      if (match && match[1]) {
        filename = match[1];
      }
    }

    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  } catch (err) {
    if (err.name === 'AbortError') {
      console.log('Project generation aborted by user.');
    } else {
      console.error('Unexpected error during project generation:', err);
      alert('Unexpected error during project generation.');
    }
  } finally {
    isGenerating = false;
    generationAbortController = null;
    if (spinner) {
      spinner.classList.add('d-none');
    }
    if (button && originalGenerateLabel !== null) {
      button.innerHTML = originalGenerateLabel;
    }
  }
}


$(document).ready(function () {
  $('#save-button1').click(saveDiagram);
  $('#reset-button').click(resetDiagram);
  $('#generate-button').click(generateWorkflow);
});


resetDiagram();


async function loadDetailsFromMongo(element) {
  const bo = element.businessObject;
  const type = element.type;
  const id = bo.id;

  if (type === 'bpmn:Task') {
    const endpoint = `/editor/api/atomic_service/${id}/`;
    try {
      const res = await fetch(endpoint);
      if (!res.ok) throw new Error("Atomic service not found");
      const data = await res.json();
      renderDetails(data, 'Atomic');
    } catch (err) {
      console.warn(`Atomic not found for ${id}`);
      renderNotFound(id);
    }
    return;
  }

  if (type === 'bpmn:Group') {
    try {
      // Prova CPPN per primo
      const cppnRes = await fetch(`/editor/api/cppn_service/${id}/`);
      if (cppnRes.ok) {
        const cppnData = await cppnRes.json();
        element.businessObject.loadedData = cppnData;
        renderDetails(cppnData, 'CPPN');
        //openGroupClassificationForm(element, cppnData);
        return;
      }
    } catch (err) {
      console.warn(`Erro fetching CPPN: ${id}`, err);
    }

    try {
      // Poi prova CPPS
      const cppsRes = await fetch(`/editor/api/cpps_service/${id}/`);
      if (cppsRes.ok) {
        const cppsData = await cppsRes.json();
        element.businessObject.loadedData = cppsData;
        renderDetails(cppsData, 'CPPS');
        //openGroupClassificationForm(element, cppsData);
        return;
      }
    } catch (err) {
      console.warn(`Error fetching CPPS: ${id}`, err);
    }

    // Nessun servizio trovato
    renderNotFound(id);
    return;
  }
}



function renderDetails(data, type) {
  const section = document.querySelector('.details-section');
  section.innerHTML = ''; // reset

  if (type === 'Atomic') {
    renderAtomicDetails(section, data);
  } else if (type === 'CPPN') {
    renderCPPNDetails(section, data);
  } else if (type === 'CPPS') {
    renderCPPSDetails(section, data);
  } else {
    section.innerHTML = '<p class="text-muted">Unknown service type.</p>';
  }
}

function renderAtomicDetails(section, data) {
  const wrapper = document.createElement('div');
  wrapper.className = 'atomic-details-wrapper';

  // Titolo
  const title = document.createElement('h5');
  title.className = 'mb-3 fw-bold';
  title.textContent = 'Details: Atomic Service';
  wrapper.appendChild(title);

  // Informazioni di base
  const nameP = document.createElement('p');
  nameP.innerHTML = `<strong>Atomic service name:</strong> ${data.name || '-'}`;
  wrapper.appendChild(nameP);

  const ownerP = document.createElement('p');
  ownerP.innerHTML = `<strong>Owner:</strong> ${data.owner || '-'}`;
  wrapper.appendChild(ownerP);

  // Griglia input / output / metadata
  const row = document.createElement('div');
  row.className = 'd-flex justify-content-between gap-5 flex-wrap';

  // Input
  const inputCol = document.createElement('div');
  const inputTitle = document.createElement('h6');
  inputTitle.textContent = 'Input:';
  inputCol.appendChild(inputTitle);
  const inputList = document.createElement('ul');
  const inputs = data.input || {};
  for (const [param, type] of Object.entries(inputs)) {
    const li = document.createElement('li');
    li.textContent = `${param}: ${type}`;
    inputList.appendChild(li);
  }
  inputCol.appendChild(inputList);

  // Output
  const outputCol = document.createElement('div');
  const outputTitle = document.createElement('h6');
  outputTitle.textContent = 'Output:';
  outputCol.appendChild(outputTitle);
  const outputList = document.createElement('ul');
  const outputs = data.output || {};
  for (const [param, type] of Object.entries(outputs)) {
    const li = document.createElement('li');
    li.textContent = `${param}: ${type}`;
    outputList.appendChild(li);
  }
  outputCol.appendChild(outputList);

  // Meta
  const metaCol = document.createElement('div');
  const metaList = document.createElement('ul');
  ['atomic_type', 'url', 'method'].forEach(k => {
    if (data[k]) {
      const li = document.createElement('li');
      li.innerHTML = `<strong>${k}:</strong> ${data[k]}`;
      metaList.appendChild(li);
    }
  });
  metaCol.appendChild(metaList);

  // Monta tutto
  row.appendChild(inputCol);
  row.appendChild(outputCol);
  row.appendChild(metaCol);
  wrapper.appendChild(row);

  section.innerHTML = '';  // Svuota la sezione
  section.appendChild(wrapper);
}

function renderCPPNDetails(section, data) {
  const title = document.createElement('h6');
  title.className = 'text-muted';
  title.textContent = 'CPPN Service';
  section.appendChild(title);

  const fields = ['name', 'business_goal' ,'description', 'workflow_type'];
  const labels = {
  name: "Name",
  business_goal: "Business Goal",
  description: "Description",
  workflow_type: "Workflow Type"
};

fields.forEach(k => {
  if (data[k]) {
    const p = document.createElement('p');
    p.innerHTML = `<strong>${labels[k]}:</strong> ${data[k]}`;
    section.appendChild(p);
  }
});

  // Actors
  if (Array.isArray(data.actors)) {
    const actorsTitle = document.createElement('h6');
    actorsTitle.textContent = 'Actors';
    section.appendChild(actorsTitle);
    const ul = document.createElement('ul');
    data.actors.forEach(actor => {
      const li = document.createElement('li');
      li.textContent = actor;
      ul.appendChild(li);
    });
    section.appendChild(ul);
  }

  // GDPR Map
  if (data.gdpr_map && typeof data.gdpr_map === 'object') {
    const gdprTitle = document.createElement('h6');
    gdprTitle.textContent = 'GDPR Map';
    section.appendChild(gdprTitle);
    const dl = document.createElement('dl');
    for (const [actor, role] of Object.entries(data.gdpr_map)) {
      const dt = document.createElement('dt');
      dt.textContent = actor;
      const dd = document.createElement('dd');
      dd.textContent = role;
      dl.appendChild(dt);
      dl.appendChild(dd);
    }
    section.appendChild(dl);
  }
}

function renderCPPSDetails(section, data) {
  const title = document.createElement('h6');
  title.className = 'text-muted';
  title.textContent = 'CPPS Service';
  section.appendChild(title);

  const fields = ['name', 'description', 'workflow_type', 'actor'];
  fields.forEach(k => {
    if (data[k]) {
      const p = document.createElement('p');
      p.innerHTML = `<strong>${k}:</strong> ${data[k]}`;
      section.appendChild(p);
    }
  });

  // Endpoints
  if (Array.isArray(data.endpoints)) {
    const endpointsTitle = document.createElement('h6');
    endpointsTitle.textContent = 'Endpoints';
    section.appendChild(endpointsTitle);
    const ul = document.createElement('ul');
    data.endpoints.forEach(ep => {
      const li = document.createElement('li');
      li.textContent = `${ep.method || 'GET'} ${ep.url || ''}`;
      ul.appendChild(li);
    });
    section.appendChild(ul);
  }
}



function renderNotFound(id) {
  const section = document.querySelector('.details-section');
  section.innerHTML = `<p class="text-muted">No service found for <code>${id}</code>.</p>`;
}

export async function loadAvailableServices() {
  try {
    const res = await fetch('/editor/api/all-services/');
    
    const data = await res.json();
    console.log(data);
    const atomicList = document.getElementById('atomicServiceList');
    const cppsList = document.getElementById('cppsServiceList');
    const cppnList = document.getElementById('cppnServiceList');

    // Pulisce prima
    atomicList.innerHTML = '';
    cppsList.innerHTML = '';
    cppnList.innerHTML = '';

    data.atomic.forEach(service => {
      const li = document.createElement('li');
      li.className = 'list-group-item list-group-item-action';
      li.textContent = service.name;
      li.onclick = () => renderDetails(service, 'Atomic');
      atomicList.appendChild(li);
    });

    data.cpps.forEach(service => {
      const li = document.createElement('li');
      li.className = 'list-group-item list-group-item-action';
      li.textContent = service.name;
      li.onclick = () => renderDetails(service, 'CPPS');
      cppsList.appendChild(li);
    });

    data.cppn.forEach(service => {
      const li = document.createElement('li');
      li.className = 'list-group-item list-group-item-action';
      li.textContent = service.name;
      li.onclick = () => renderDetails(service, 'CPPN');
      cppnList.appendChild(li);
    });
  } catch (err) {
    console.error('Error loading services:', err);
  }
}

export async function ensureDiagramSaved() {
    let diagramId = window.diagramId || localStorage.getItem('diagramId');

    if (!diagramId) {
        const { xml } = await bpmnModeler.saveXML({ format: true });
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
        const diagramName = `Draft Diagram ${timestamp}`;

        const csrftoken = getCookie('csrftoken');

        const response = await fetch('/editor/api/save-diagram/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            },
            body: JSON.stringify({
                name: diagramName,
                xml_content: xml
            })
        });

        const result = await response.json();
        diagramId = result.id;

        // 💥 Qui memorizzi l'id e segni come draft
        window.diagramId = diagramId;
        localStorage.setItem('diagramId', diagramId);
        window.diagramHasFinalName = false;

        console.log(`✅ Auto-saved new diagram: ${diagramName} (ID: ${diagramId})`);
    }

    return diagramId;
}