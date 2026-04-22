import os
import json
import shutil
import subprocess
import argparse
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List
import prompt as prompt_module

TEMPLATE_PATH = Path("laravel-base")              
OUTPUT_ROOT = Path("output-projects")            
LARAVEL_VERSION = "12"                          

api_key = os.environ.get("OPENAI_API_KEY")

if api_key:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
    except ImportError:
        print("Errore nella creazione del client OpenAI.")
else:
    client = None

def parse_bpmn(bpmn_path: str) -> str:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
    except ImportError:
        raise RuntimeError("Errore nella creazione del client OpenAI.")
    prompt = f"""
    ## ISTRUZIONE ##
    Sei un assistente esperto nella traduzione di modelli BPMN in specifiche formali di workflow distribuiti.
    Il tuo compito è analizzare il file BPMN fornito in formato XML e generare una relativa specifica formale in formato JSON.
    
    ### CONTESTO ###
    Il file BPMN fornito è stato generato tramite BPMN.io, segue le regole di modellazione BPMN e rappresenta l'interazione di più attori in una supply chain
    tramite servizi atomici, CPPS e CPPN.
    Per ogni attore viene specificato un processo all'interno del tag partecipant nell'attributo 'processRef'.
    In ogni processo vengono riportati:
    1. tutti i servizi atomici associati all'attore senza fare distinzioni per CPPN.
    2. le interconnesioni tra i servizi atomici tramite il sequenceFlow.
    3. eventuali gateway paralleli tra i servizi atomici tramite il parallelGateway, indicando un'esecuzione parallela dei servizi atomici.
    4. eventuali gateway esclusivi identificati tramite l'exclusiveGateway, indicando una scelta a due vie.
    All'interno dell'XML, i servizi atomici sono rappresentati come "task" con proprietà personalizzate che indicano il tipo atomico (dispatch, collect, process&monitor, display).
    I gruppi di task interni alle lane rappresentano i CPPS, mentre i pool rappresentano i CPPN.
    Questi gruppi possono includere gateway per rappresentare le interconnessioni tra i servizi atomici e sono dichiarati all'inizio del file XML.


    ## INPUT ##
    Dato il seguente file BPMN in formato XML:
    {open(bpmn_path, 'r', encoding='utf-8').read()}

    ## RESTRIZIONI ##
    1. Non includere commenti o descrizioni aggiuntive nella risposta.
    2. Rispondi esclusivamente in formato JSON valido.
    3. Nel file XML ci sono alcuni campi che possono essere trascurati per la generazione della specifica formale, come le informazioni racchiuse nel tag <bpmndi:BPMNDiagram>.
    
    ### OUTPUT RICHIESTO ###
    Fornisci una specifica formale in formato JSON che descriva:
    1. Gli attori coinvolti (campo 'owner').
    2. I servizi atomici, specificando per ciascuno:
       - Nome del servizio (campo 'name').
       - Tipo atomico ('dispatch', 'collect', 'process&monitor' o 'display').
       - Attore proprietario (campo 'owner').
       - Tipo di input e output richiesti (string, number o array).
       - URL del servizio.
       - Metodo HTTP (GET, POST, PUT, DELETE).
    3. Le interconnessioni tra i servizi atomici e gli elementi del BPMN come startEvent, endEvent, parallelGateway, exclusiveGateway (specificate nel campo 'sequenceFlow').
    4. I messageFlow tra i servizi atomici di attori diversi (specificati nel tag '<bpmn:messageFlow>') che indicano le comunicazioni tra attori, specificando sorgente e destinazione.
    5. I CPPS specificando:
       - Nome del CPPS (campo 'name').
       - Attore proprietario (campo 'actor').
       - Elenco dei servizi atomici coinvolti e loro interconnessioni gateway (campo 'members').
       - URL del CPPS (se non è presente fornire URL sintetico sulla base del nome del CPPS).
       - Metodo HTTP (POST).
    6. I CPPN specificando:
       - Nome del CPPN (campo 'name').
       - Attori coinvolti (campo 'members').
       - Elenco dei servizi atomici con eventuali CPPS coinvolti e loro interconnessioni (campo 'services')
   """

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": "Sei un esperto di modellazione BPMN e generazione di specifiche formali per workflow distribuiti."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    spec = response.choices[0].message.content.strip()
    return spec


def call_llm(prompt: str) -> Dict:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
    except ImportError:
        raise RuntimeError("Errore nella creazione del client OpenAI.")
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": "Sei un esperto sviluppatore Laravel. Rispondi solo in JSON valido senza riportare ```json nel testo."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )

    content = response.choices[0].message.content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        raise ValueError(f"Risposta LLM non in JSON valido:\n{content}")


def clone_template_for_actors(actors: List[Dict], session_dir: Path) -> Dict[str, Path]:
    actor_paths = {}

    print(f"=== CLONAZIONE PROGETTI PER OGNI ATTORE NELLA SESSIONE '{session_dir.name}' ===")
    session_dir.mkdir(parents=True, exist_ok=True)

    for actor in actors:
        node_name = actor["name"].replace(" ", "_")
        target = session_dir / node_name

        if target.exists():
            print(f"- Pulizia progetto esistente per {node_name}...")
            shutil.rmtree(target)

        print(f"- Creazione progetto per attore: {node_name}")
        shutil.copytree(TEMPLATE_PATH, target, dirs_exist_ok=True)
        actor_paths[node_name] = target

    print("=== CLONAZIONE COMPLETATA ===\n")
    return actor_paths


def write_actor_files(actor_paths: Dict[str, Path], actors: List[Dict]):
    print("=== SCRITTURA FILE NEI PROGETTI ===")
    for actor in actors:
        node_name = actor["name"].replace(" ", "_")
        root = actor_paths[node_name]

        for file in actor["files"]:
            path = root / file["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(file["content"])
            print(f"- [{node_name}] Scritto file: {path.relative_to(root)}")

    print("=== SCRITTURA COMPLETATA ===\n")


def refresh_autoload(target: Path):
    print(f"- Rigenerazione autoload... {target.resolve()}")
    subprocess.run(["composer", "dump-autoload"], cwd=str(target.resolve()), shell=True, check=True)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Generatore Laravel da file BPMN")
    parser.add_argument("bpmn", help="Percorso del file BPMN XML")
    parser.add_argument("session_name", help="Nome cartella che conterrà i progetti generati")
    args = parser.parse_args()

    session_dir = OUTPUT_ROOT / args.session_name
    parsed = parse_bpmn(args.bpmn)

    prompt = prompt_module.build_best_prompt(parsed)
    llm_result = call_llm(prompt)

    actors = llm_result["actors"]
    actor_paths = clone_template_for_actors(actors, session_dir)
    print("Scrittura file per ogni attore...")
    write_actor_files(actor_paths, actors)

    print(f"\nProgetti Laravel generati con successo")