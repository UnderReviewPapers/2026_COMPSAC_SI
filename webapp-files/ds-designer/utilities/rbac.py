from .mongodb_handler import rbac_collection, atomic_services_collection, cpps_collection
from datetime import datetime
ALLOW_TYPES = {"atomic", "cpps"}

def _service_invoke_actors(diagram_id: str, sid: str, stype: str) -> list[str]:
        """
        Ritorna la lista di attori con 'invoke' dal documento RBAC del servizio (atomic/cpps).
        Per atomic: permissions = [{actor, permission}]
        Per cpps  : permissions = [{actor, service, permission}] → ignoriamo 'service' qui, interessa l'attore.
        """
        if stype == "atomic":
            doc = rbac_collection.find_one(
                {"diagram_id": diagram_id, "service_type": "atomic", "atomic_id": sid},
                {"permissions": 1, "owner": 1, "_id": 0}
            )
            if not doc:
                return []
            actors = []
            for p in (doc.get("permissions") or []):
                if p.get("permission") == "invoke":
                    a = (p.get("actor") or "").strip()
                    if a: actors.append(a)
            # owner normalmente è già dentro con 'invoke', ma lo includiamo se mancasse
            owner = (doc.get("owner") or "").strip()
            if owner and owner not in actors:
                actors.append(owner)
            # unici preservando ordine
            seen=set(); out=[]
            for a in actors:
                k=a.lower()
                if k in seen: continue
                seen.add(k); out.append(a)
            return out

        elif stype == "cpps":
            doc = rbac_collection.find_one(
                {"diagram_id": diagram_id, "service_type": "cpps", "cpps_id": sid},
                {"permissions": 1, "owner": 1, "_id": 0}
            )
            if not doc:
                return []
            actors = []
            for p in (doc.get("permissions") or []):
                if p.get("permission") == "invoke":
                    a = (p.get("actor") or "").strip()
                    if a: actors.append(a)
            owner = (doc.get("owner") or "").strip()
            if owner and owner not in actors:
                actors.append(owner)
            seen=set(); out=[]
            for a in actors:
                k=a.lower()
                if k in seen: continue
                seen.add(k); out.append(a)
            return out
        return []

class rbac:
    
    @staticmethod
    def atomic_policy(atomic_data):
        diagram_id = atomic_data['diagram_id']
        atomic_name = atomic_data['name']
        service_type = 'atomic'
        atomic_type = atomic_data['atomic_type']
        task_id = atomic_data['task_id']
        components = [task_id]
        owner = atomic_data['owner']

        actors = [owner]

        #Access Control Matrix
        acm: dict[str, str] = {}
        for actor in actors:
            acm[actor] = {}
            for comp in components:
                acm[actor][comp] = "none"

        #owner può invocare il proprio atomic
        acm[owner][task_id] = 'invoke'

        #costruzione policy
        policy = {
            'diagram_id': diagram_id,
            'service_name' : atomic_name,
            "service_type" : service_type,
            "atomic_type" : atomic_type,
            "owner" : owner,
            "permissions": 
            [
                {"actor": actor , "permission": perm}
                for actor, cols in acm.items()
                for comp,perm in cols.items()
            ]
        }

        try:
            result = rbac_collection.update_one(
                {'atomic_id': task_id},
                {'$set': policy},
                upsert=True
            )
            created = result.upserted_id is not None
            
            return {'status': 'ok', 'created policy': created}, 200

        except Exception as e:
            return {'error': str(e)}, 500

    @staticmethod
    def cpps_policy_from_import(cpps_data_import, components):

        atomic_ids = []
        cpps_ids = []
        for c in components:
            if c['type'].lower() == 'atomic':
                atomic_ids.append(c['id'])
            elif c['type'].lower() == 'cpps':
                cpps_ids.append(c['id'])
        
        rbac.cpps_policy(cpps_data_import, atomic_ids, cpps_ids)


    @staticmethod
    def cpps_policy(cpps_data, atomic_ids, cpps_ids):
        cpps_name = cpps_data['name']
        diagram_id = cpps_data['diagram_id']
        service_type = 'cpps'
        group_id = cpps_data['group_id']
        components = atomic_ids
        owner = cpps_data['owner']

        if cpps_ids:
            components = components + cpps_ids
        
        acm: dict[str, str] = {}
        acm[owner] = {}
        for comp in components:
            acm[owner][comp] = "invoke"
        
        #costruzione policy
        policy = {
            'diagram_id' : diagram_id,
            'service_name' : cpps_name,
            "service_type" : service_type,
            "owner" : owner,
            "permissions": 
            [
                {"actor": actor , "service" : comp , "permission": perm}
                for actor, cols in acm.items()
                for comp,perm in cols.items()
            ]
        }

        try:
            result = rbac_collection.update_one(
                {'cpps_id' : group_id},
                {'$set': policy},
                upsert=True
            )
            created = result.upserted_id is not None
            
            return {'status': 'ok', 'created policy': created}, 200

        except Exception as e:
            return {'error': str(e)}, 500


    @staticmethod
    def cppn_policy(cppn_data, components_cppn):
        """
        Costruisce/aggiorna la policy CPPN con SOLO tuple 'invoke' (overlay 'pulito').
        - include nei members SOLO componenti di tipo 'atomic' o 'cpps'
        - per ogni member, semina le tuple (actor, service, 'invoke') usando i doc RBAC del servizio
        (owner + eventuali extra già presenti a livello servizio)
        - 'actors' = unione degli attori che risultano invoke su almeno un member
        """
        service_name = cppn_data['name']
        diagram_id   = cppn_data['diagram_id']
        group_id     = cppn_data['group_id']   # cppn_id
        service_type = 'cppn'

        members = []            # solo servizi (atomic/cpps)
        permissions = []        # SOLO tuple 'invoke'
        actors_set = set()      # unione attori effettivi

        # 1) raccogli i members (solo servizi)
        for c in components_cppn:
            ctype = (c.get('type') or '').lower()
            if ctype not in ALLOW_TYPES:
                continue
            sid = (c.get('id') or '').strip()
            if not sid:
                continue
            members.append((sid, ctype))

        # dedup preservando ordine
        seen = set()
        members = [(sid, st) for (sid, st) in members if (sid not in seen and not seen.add(sid))]

        # 2) per ogni member, semina overlay = attori che hanno invoke nel servizio
        for sid, stype in members:
            invokers = _service_invoke_actors(diagram_id, sid, stype)
            for a in invokers:
                permissions.append({"actor": a, "service": sid, "permission": "invoke"})
                actors_set.add(a)

        policy = {
            "cppn_id"      : group_id,
            "service_name" : service_name,
            "diagram_id"   : diagram_id,
            "service_type" : service_type,
            "actors"       : sorted(actors_set),                 # attori effettivi (invoke su almeno un member)
            "members"      : [sid for (sid, _) in members],      # solo id servizio
            "permissions"  : permissions,                        # SOLO 'invoke'
            "updated_at"   : datetime.utcnow(),
        }

        try:
            result = rbac_collection.update_one(
                {"diagram_id": diagram_id, "service_type": "cppn", "cppn_id": group_id},
                {"$set": policy},
                upsert=True
            )
            created = result.upserted_id is not None
            return {"status": "ok", "created_policy": created,
                    "members": len(policy["members"]), "invoke_tuples": len(policy["permissions"])}, 200
        except Exception as e:
            return {"error": str(e)}, 500
        
    @staticmethod
    def find_atomic_owner(task_id):
        atomic = atomic_services_collection.find_one({'task_id' : task_id })
        return atomic['owner']
    
    @staticmethod
    def find_cpps_owner(group_id):
        cpps = cpps_collection.find_one({'group_id' : group_id })
        return cpps['owner']