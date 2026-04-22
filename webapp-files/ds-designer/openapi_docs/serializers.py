from rest_framework import serializers

GDPR_ROLES = ["Data Controller", "Data Processor", "Data Subject", "Supervisory Authority"]

class AtomicUpsertSerializer(serializers.Serializer):
    diagram_id = serializers.CharField()
    task_id = serializers.CharField()       # = service_id
    name = serializers.CharField()
    atomic_type = serializers.CharField()   # collect | dispatch | process&monitor | display
    method = serializers.ChoiceField(choices=['GET','POST','PUT','PATCH','DELETE'])
    url = serializers.CharField()
    owner = serializers.CharField()
    # input/output: { "<example>": "<type>" }  es: { "100": "integer", "abc": "string" }
    input = serializers.DictField(child=serializers.CharField())
    output = serializers.DictField(child=serializers.CharField())

class CPPSComponentSerializer(serializers.Serializer):
    """
    Un componente del CPPS. Per ora accettiamo:
    - Atomic: riferimento a un servizio atomico
    - CPPS: (eventuale) nesting futuro
    - External: step esterni (es. hook)
    """
    id = serializers.CharField()
    type = serializers.ChoiceField(choices=["Atomic", "CPPS", "External"], default="Atomic")


class CPPSEndpointSerializer(serializers.Serializer):
    """
    Endpoint opzionali a supporto del CPPS (es. webhook, callback).
    Non sono richiesti; manteniamo schema permissivo ma tipizzato.
    """
    name = serializers.CharField(required=False, allow_blank=True)
    url = serializers.URLField()
    method = serializers.ChoiceField(choices=["GET", "POST", "PUT", "PATCH", "DELETE"], default="POST")
    description = serializers.CharField(required=False, allow_blank=True)


class CPPSUpsertSerializer(serializers.Serializer):
    """
    Serializer per l'upsert di documenti CPPS su Mongo e per la
    generazione della specifica OpenAPI 3.1 coerente con il paper bagozi.
    """
    group_id = serializers.CharField()
    diagram_id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True, required=False)
    owner = serializers.CharField()  # attore responsabile (actor nel paper)

    group_type = serializers.ChoiceField(choices=["CPPS"], default="CPPS")

    components = serializers.ListField(child=CPPSComponentSerializer(), allow_empty=False)

    # Esempio dal documento:
    # "workflow": { "Activity_07o8s0a": ["Activity_16oz7n2"] }
    workflow = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        allow_empty=False
    )

    workflow_type = serializers.ChoiceField(choices=["sequence", "parallel", "custom"], default="sequence")

    endpoints = serializers.ListField(
        child=CPPSEndpointSerializer(),
        required=False,
        default=list
    )

    def validate(self, data):
        """
        Cross-field validation:
        - component ids univoche e non vuote
        - chiavi/valori del workflow appartengono ai component ids
        - group_type deve essere 'CPPS'
        - niente self-loop evidenti in workflow (opzionale, ma utile)
        """
        #component ids
        comp_ids = [c["id"] for c in data.get("components", [])]
        if any(not cid.strip() for cid in comp_ids):
            raise serializers.ValidationError("Tutti i component.id devono essere non vuoti.")
        if len(set(comp_ids)) != len(comp_ids):
            raise serializers.ValidationError("I component.id devono essere univoci nel CPPS.")

        #workflow references
        wf = data.get("workflow", {})
        unknown = set()

        for src, nxts in wf.items():
            if src not in comp_ids:
                unknown.add(src)
            for target in nxts:
                if target not in comp_ids:
                    unknown.add(target)
                if target == src:
                    raise serializers.ValidationError(f"Self-loop non consentito sul nodo '{src}'.")

        if unknown:
            raise serializers.ValidationError(
                f"Workflow fa riferimento a id non presenti in components: {sorted(list(unknown))}"
            )

        # tipo
        if data.get("group_type") != "CPPS":
            raise serializers.ValidationError("group_type deve essere 'CPPS'.")

        return data
    
# --- CPPN ---

GDPR_ROLES = [
    "Data Controller", "Joint Controller", "Data Processor",
    "Data Subject", "Supervisory Authority"
]

class CPPNComponentSerializer(serializers.Serializer):
    id = serializers.CharField()
    type = serializers.ChoiceField(choices=["Atomic", "CPPS", "External", "ParallelGateway"])
    # solo per i gateway paralleli
    targets = serializers.ListField(
        child=serializers.CharField(), allow_empty=True, required=False
    )

class CPPNUpsertSerializer(serializers.Serializer):
    group_id      = serializers.CharField()
    diagram_id    = serializers.CharField()
    name          = serializers.CharField()
    description   = serializers.CharField(allow_blank=True, required=False)
    group_type    = serializers.ChoiceField(choices=["CPPN"], default="CPPN")
    workflow_type = serializers.ChoiceField(choices=["sequence", "parallel", "custom"], required=True)

    actors   = serializers.ListField(child=serializers.CharField(), allow_empty=False)
    gdpr_map = serializers.DictField(child=serializers.CharField(), required=False)

    components = serializers.ListField(child=CPPNComponentSerializer())
    workflow   = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()), required=True
    )
    endpoints  = serializers.ListField(child=serializers.DictField(), required=False)

    def validate(self, data):
        comp_ids = [c["id"] for c in data.get("components", [])]
        if any(not cid.strip() for cid in comp_ids):
            raise serializers.ValidationError("Tutti i component.id devono essere non vuoti.")
        if len(set(comp_ids)) != len(comp_ids):
            raise serializers.ValidationError("I component.id devono essere univoci nel CPPN.")

        # workflow refs + niente self-loop
        wf = data.get("workflow", {})
        unknown = set()
        for src, nxts in wf.items():
            if src not in comp_ids:
                unknown.add(src)
            for target in nxts:
                if target not in comp_ids:
                    unknown.add(target)
                if target == src:
                    raise serializers.ValidationError(f"Self-loop non consentito sul nodo '{src}'.")
        if unknown:
            raise serializers.ValidationError(
                f"Workflow fa riferimento a id non presenti in components: {sorted(list(unknown))}"
            )

        # gateway paralleli: i targets devono esistere
        for c in data.get("components", []):
            if c.get("type") == "ParallelGateway":
                tgts = c.get("targets", [])
                bad = [t for t in tgts if t not in comp_ids]
                if bad:
                    raise serializers.ValidationError(
                        f"ParallelGateway '{c['id']}' ha targets non validi: {bad}"
                    )

        # attori + GDPR
        actors = set([a.strip() for a in data.get("actors", []) if a.strip()])
        if not actors:
            raise serializers.ValidationError("actors non può essere vuoto.")
        gmap = data.get("gdpr_map", {}) or {}
        for k, v in gmap.items():
            if k not in actors:
                raise serializers.ValidationError(f"gdpr_map contiene attore sconosciuto: {k}")
            if v not in GDPR_ROLES:
                raise serializers.ValidationError(f"gdpr_map[{k}] ha ruolo non valido: {v}")

        return data

