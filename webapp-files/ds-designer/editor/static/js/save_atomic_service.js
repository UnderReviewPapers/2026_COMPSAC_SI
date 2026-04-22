import {getCookie, ensureDiagramSaved, loadAvailableServices } from './editor.js';

async function saveAtomicService() {
    console.log('Called function saveAtomicService.');

    if (!currentElement) {
        console.log('currentElement is null');
        return;
    }

    let diagramId = await ensureDiagramSaved();

    const owner = document.getElementById('owner').value;
    const name = document.getElementById('serviceName').value;
    const atomicType = document.getElementById('atomicType').value;
    const inputParams = document.getElementById('inputParams').value.split(',').map(s => s.trim());
    const outputParams = document.getElementById('outputParams').value.split(',').map(s => s.trim());
    const method = document.getElementById('httpMethod').value;
    const url = document.getElementById('serviceUrl').value;

    if (!validateAtomicServiceFields({ name, atomicType, inputParams, outputParams, method, url })) {
        return;
    }

    const csrftoken = getCookie('csrftoken');

    // Aggiunta estensione custom all’elemento BPMN selezionato
    const moddle = bpmnModeler.get('moddle');
    const modeling = bpmnModeler.get('modeling');

    const extensionElement = moddle.create('custom:AtomicExtension', {
        atomicType,
        inputParams: inputParams.join(', '),
        outputParams: outputParams.join(', '),
        method,
        url,
        owner
    });

    const extensionElements = moddle.create('bpmn:ExtensionElements', {
        values: [extensionElement]
    });

    modeling.updateProperties(currentElement, {
        name,
        extensionElements
    });

    // Salvataggio atomic service sul backend
    try {
        const response = await fetch('/editor/api/save-atomic-service/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            },
            body: JSON.stringify({
                diagram_id: diagramId,
                task_id: currentElement.id,
                name,
                atomic_type: atomicType,
                input_params: inputParams,
                output_params: outputParams,
                method,
                url,
                owner
            })
        });

        const result = await response.json();

        if (response.ok) {
            console.log("✅ Atomic service saved successfully!", result);
            await loadAvailableServices();
        } else {
            console.error("❌ Error saving:", result);
            alert("Error saving atomic service.");
        }
    } catch (err) {
        console.error("❌ Network error/api:", err);
        alert("Comunication server error.");
    }

    // Chiudi il modal
    bootstrap.Modal.getInstance(document.getElementById('atomicServiceModal')).hide();

    // Memorizza dati dell’atomic service per uso futuro
    window.saveAtomicServiceData = {
        name,
        atomic_type: atomicType,
        input_params: inputParams,
        output_params: outputParams,
        method,
        url,
        owner
    };
    window.saveAtomicService = saveAtomicService;
}


function validateAtomicServiceFields({ name, atomicType, inputParams, outputParams, method, url }) {
    if (name.trim() === '') {
        alert("Service's name is mandatory.");
        return false;
    }

    if (!atomicType.trim()) {
        alert("Type's name is mandatory.");
        return false;
    }

    if (inputParams.length === 0 || inputParams.every(p => p === '')) {
        alert("Insert at least one input parameter.");
        return false;
    }

    if (outputParams.length === 0 || outputParams.every(p => p === '')) {
        alert("Insert at least one output parameter.");
        return false;
    }

    if (!method.trim()) {
        alert("HTTP method is mandatory.");
        return false;
    }

    if (!url.trim() || !/^\/[a-zA-Z0-9_]+$/.test(url)) {
        alert("URL is mandatory or not valid. Must starts with '/' (only chars, number or underscores allowed)");
        return false;
    }

    return true;
}

document.getElementById('save-atomic-button')
  .addEventListener('click', saveAtomicService);