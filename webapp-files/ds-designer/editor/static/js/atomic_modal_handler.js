// Variabili globali
let currentElement = null;
let isNewTask = false;

// Funzione principale per aprire la modale di un as
function openAtomicServiceForm(element, isNew = false) {

  if (!element || !element.businessObject) return;

  currentElement = element;
  isNewTask = isNew;

  const bo = element.businessObject;

  let atomicType = '';
  let inputParams = '';
  let outputParams = '';
  let method = '';
  let url = '';
  let owner = '';
  

  //popolo campi form se oggetto bpmn gia presente -> bo = business object
  if (bo.extensionElements?.values?.length) {
    const customExt = bo.extensionElements.values.find(e => e.$type === 'custom:AtomicExtension');
    if (customExt) {
      atomicType = customExt.atomicType || '';
      inputParams = customExt.inputParams || '';
      outputParams = customExt.outputParams || '';
      method = customExt.method || '';
      url = customExt.url || '';
      owner = customExt.owner || '';
    }
  }

  // 👉 QUI inserisci il fallback automatico
    if (!owner) {
      owner = detectParticipantForElement(element);
    }


  document.getElementById('serviceName').value = bo.name || '';
  document.getElementById('atomicType').value = atomicType;
  document.getElementById('inputParams').value = inputParams;
  document.getElementById('outputParams').value = outputParams;
  document.getElementById('httpMethod').value = method;
  document.getElementById('serviceUrl').value = url;
  document.getElementById('owner').value = owner;

  const modalEl = document.getElementById('atomicServiceModal');
  const modal = new bootstrap.Modal(modalEl);
  modal.show();
}

// Chiudi e rimuovi task vuoti
document.addEventListener('DOMContentLoaded', function () {
  const modalEl = document.getElementById('atomicServiceModal');

  if (modalEl) {
    modalEl.addEventListener('hidden.bs.modal', function () {
      if (!isNewTask || !currentElement) return;

      const isFormEmpty =
        !document.getElementById('serviceName').value.trim() &&
        !document.getElementById('inputParams').value.trim() &&
        !document.getElementById('outputParams').value.trim() &&
        !document.getElementById('serviceUrl').value.trim();

      if (isFormEmpty) {
        const modeling = window.bpmnModeler.get('modeling');
        const elementRegistry = window.bpmnModeler.get('elementRegistry');
        const element = elementRegistry.get(currentElement.id);
        if (element) {
          modeling.removeElements([element]);
          showToast("Task removed - not configured.");
        }
      }

      isNewTask = false;
      currentElement = null;
    });
  }
});


function showToast(message) {
  const toastEl = document.getElementById('taskToast');
  document.getElementById('taskToastBody').innerText = message;
  const toast = new bootstrap.Toast(toastEl);
  toast.show();
}


function detectParticipantForElement(element) {
  const elementRegistry = bpmnModeler.get('elementRegistry');
  const canvas = bpmnModeler.get('canvas');

  const elementBBox = canvas.getAbsoluteBBox(element);

  const participants = elementRegistry.filter(el => el.type === 'bpmn:Participant');

  const containing = participants.find(part => {
    const partBBox = canvas.getAbsoluteBBox(part);
    return (
      elementBBox.x >= partBBox.x &&
      elementBBox.x + elementBBox.width <= partBBox.x + partBBox.width &&
      elementBBox.y >= partBBox.y &&
      elementBBox.y + elementBBox.height <= partBBox.y + partBBox.height
    );
  });

  return containing ? (containing.businessObject.name || '') : '';
}


// Esponi globalmente
window.openAtomicServiceForm = openAtomicServiceForm;
