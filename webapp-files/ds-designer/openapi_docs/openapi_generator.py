from typing import Dict, Any, List
from utilities.mongodb_handler import openapi_collection

class OpenAPIGenerator:
    """
    Genera una OpenAPI 3.1 per un Atomic Service a partire dal documento atomic:
    {
      "task_id", "diagram_id", "name", "atomic_type", "owner",
      "method", "url", "input": { "<example>": "<type>" }, "output": { ... }
    }
    """
    @staticmethod
    def _cast_example(value: str, oas_type: str):
        if oas_type == 'integer':
            try: return int(value)
            except: return value
        if oas_type == 'number':
            try: return float(value)
            except: return value
        if oas_type == 'boolean':
            v = str(value).lower()
            if v in ('true','1','yes','y'): return True
            if v in ('false','0','no','n'): return False
            return value
        return value  # string

    @staticmethod
    def generate_atomic_openapi(doc: dict, version: str = "1.0.0") -> dict:
        mapping = {'string':'string','integer':'integer','float':'number','number':'number','boolean':'boolean'}

        # Costruzione proprietà input/output
        in_props, out_props = {}, {}
        for i, (ex, typ) in enumerate(doc.get("input", {}).items(), start=1):
            t = mapping.get(typ, "string")
            in_props[f"input_{i}"] = {"type": t, "example": OpenAPIGenerator._cast_example(ex, t)}
        for i, (ex, typ) in enumerate(doc.get("output", {}).items(), start=1):
            t = mapping.get(typ, "string")
            out_props[f"output_{i}"] = {"type": t, "example": OpenAPIGenerator._cast_example(ex, t)}

        method = doc["method"].lower()
        op = {"summary": f"{doc['atomic_type']} atomic service"}

        if method == "get":
            # Parametri in query
            op["parameters"] = [{
                "in": "query", "name": k, "required": True,
                "schema": {"type": v["type"]},
                "example": v.get("example")
            } for k, v in in_props.items()]
        else:
            # Body JSON
            op["requestBody"] = {
                "required": True,
                "content": {"application/json": {
                    "schema": {"$ref":"#/components/schemas/AtomicInput"},
                    "examples": {"default":{"value":{k:v["example"] for k,v in in_props.items()}}}
                }}
            }

        # Risposte
        op["responses"] = {
            "200": {"description":"Success","content":{"application/json":{
                "schema":{"$ref":"#/components/schemas/AtomicOutput"},
                "examples":{"default":{"value":{k:v["example"] for k,v in out_props.items()}}}
            }}}
        }

        # Documento OpenAPI
        oas = {
            "openapi": "3.1.0",
            "jsonSchemaDialect": "https://spec.openapis.org/oas/3.1/dialect/base",
            "info": {
                "title": doc["name"],
                "version": version,
                "x-service_id": doc.get("task_id"),
                "x-diagram_id": doc.get("diagram_id"),
                "x-owner": doc["owner"],
                "x-service-type": "atomic",
                "x-atomic-type": doc["atomic_type"]
            },
            "paths": { doc["url"]: { method: op } },
            "components": {
                "securitySchemes": {
                    "bearerAuth": { "type":"http", "scheme":"bearer", "bearerFormat":"JWT" }
                },
                "schemas": {
                    "AtomicInput": { "type":"object","properties": in_props,"required": list(in_props.keys()) },
                    "AtomicOutput": { "type":"object","properties": out_props }
                }
            },
            "security": [{"bearerAuth": []}]
        }
        return oas
    
    @staticmethod
    def _parse_semver(v: str) -> tuple[int, int, int]:
        try:
            M, m, p = v.split(".")
            return (int(M), int(m), int(p))
        except Exception:
            return (0, 0, 0)

    @staticmethod
    def _latest_atomic_oas(service_id: str) -> dict | None:
        """
        Cerca tra le atomic OAS pubblicate quella con versione semver più alta per service_id.
        """
        cur = openapi_collection.find(
            {"level": "atomic", "service_id": service_id, "status": "published"},
            {"_id": 0, "version": 1, "oas": 1}
        )
        best = None
        best_t = (-1, -1, -1)
        for d in cur:
            v = d.get("version")
            t = OpenAPIGenerator._parse_semver(v or "")
            if t > best_t:
                best_t = t
                best = d
        return best["oas"] if best else None

    @staticmethod
    def _mk_fallback_atomic_in() -> Dict[str, Any]:
        return {"type": "object", "additionalProperties": True}

    @staticmethod
    def _mk_fallback_atomic_out() -> Dict[str, Any]:
        return {"type": "object", "additionalProperties": True}

    @staticmethod
    def generate_cpps_openapi(doc: dict, version: str = "1.0.0") -> dict:
        group_id = doc["group_id"]
        
        meta_value = {
            "group_id": group_id,
            "name": doc.get("name"),
            "owner": doc.get("owner"),
            "description": doc.get("description"),
            "diagram_id": doc.get("diagram_id"),
            "group_type": doc.get("group_type", "CPPS"),
            "workflow_type": doc.get("workflow_type"),
            "workflow": doc.get("workflow", {}),
            "components": doc.get("components", []),
            "endpoints": doc.get("endpoints", []),
        }

        # --- operations invarianti ---
        get_op = {
            "summary": "Get CPPS definition",
            "tags": ["Definition"],
            "operationId": f"cpps_get_{group_id}",
            "responses": {
                "200": {
                    "description": "Definition",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/CPPSMeta"},
                            "examples": {
                                "current": {
                                    "summary": "Current CPPS metadata",
                                    "value": meta_value
                                }
                            }
                        }
                    }
                }
            }
        }

        post_op = {
            "summary": "Invoke CPPS workflow",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/CPPSInput"},
                        "examples": {"default": {"value": {"params": {}, "context": {}}}}
                    }
                }
            },
            "responses": {
                "200": {
                    "description": "Execution result",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/CPPSOutput"}
                        }
                    }
                }
            }
        }

        oas = {
            "openapi": "3.1.0",
            "jsonSchemaDialect": "https://spec.openapis.org/oas/3.1/dialect/base",
            "info": {
                "title": doc["name"],
                "version": version,
                "description": doc.get("description", ""),
                "x-service-type": "CPPS",
                "x-layer": "CPPS",
                "x-group_id": group_id,
                "x-diagram_id": doc.get("diagram_id"),
                "x-owner": doc.get("owner"),
                "x-workflow-type": doc.get("workflow_type"),
                "x-components": doc.get("components", []),
            },
            "paths": {
                f"/cpps/{group_id}": {"get": get_op},
                f"/cpps/{group_id}/invoke": {"post": post_op},
            },
            "components": {
                "securitySchemes": {
                    "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
                },
                "schemas": {

            "CPPSComponent": {
                "type": "object",
                "properties": {
                    "id":   {"type": "string"},
                    "type": {"type": "string", "enum": ["Atomic", "CPPS", "External"]}
                },
                "required": ["id", "type"]
            },
            "CPPSEndpoint": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": "string", "format": "uri"},
                    "method": {"type": "string", "enum": ["GET","POST","PUT","PATCH","DELETE"]},
                    "description": {"type": "string"}
                },
                "required": ["url", "method"]
            },
            "CPPSMeta": {
                "type": "object",
                "properties": {
                    "group_id":     {"type": "string", "const": group_id},
                    "name":         {"type": "string" },
                    "owner":        {"type": "string"},
                    "description":  {"type": "string"},
                    "diagram_id":   {"type": "string"},
                    "group_type":   {"type": "string", "const": "CPPS"},
                    "workflow_type":{"type": "string", "enum": ["sequence","parallel","custom"]},
                    "workflow": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "description": "Adjacency list: { nodeId: [nextNodeId, ...] }"
                    },
                    "components": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/CPPSComponent"}
                    },
                    "endpoints": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/CPPSEndpoint"}
                    }
                },
                "required": ["group_id", "name", "components"]
            },
                    "CPPSInput": {
                        "type": "object",
                        "properties": {
                            "params": {"type": "object", "additionalProperties": True},
                            "context": {"type": "object", "additionalProperties": True}
                        },
                        "required": ["params"]
                    },
                    "CPPSOutput": {
                        "type": "object",
                        "properties": {
                            "status": {"type": "string", "enum": ["OK", "ERROR"]},
                            "results": {"type": "object", "additionalProperties": True},
                            "trace": {"type": "array", "items": {"type": "object"}}
                        },
                        "required": ["status"]
                    }
                }
            },
            "security": [{"bearerAuth": []}]
        }

        # ---------composizione dagli Atomic ----------
        inputs: Dict[str, Any] = {}
        outputs: Dict[str, Any] = {}

        for comp in doc.get("components", []):
            if comp.get("type") != "Atomic":
                # (eventuale estensione: se CPPS nested, per comporre ricorsivamente)
                continue
            sid = comp["id"]
            atomic_oas = OpenAPIGenerator._latest_atomic_oas(sid)
            if atomic_oas:
                schemas = (atomic_oas.get("components") or {}).get("schemas") or {}
                ain = schemas.get("AtomicInput") or OpenAPIGenerator._mk_fallback_atomic_in()
                aout = schemas.get("AtomicOutput") or OpenAPIGenerator._mk_fallback_atomic_out()
            else:
                ain = OpenAPIGenerator._mk_fallback_atomic_in()
                aout = OpenAPIGenerator._mk_fallback_atomic_out()

            inputs[sid] = ain
            outputs[sid] = aout

        if inputs:
            oas["components"]["schemas"]["CPPSInput"] = {
                "type": "object",
                "properties": {k: v for k, v in inputs.items()},
                "additionalProperties": False
            }

        if outputs:
            oas["components"]["schemas"]["CPPSOutput"] = {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["OK", "ERROR"]},
                    "results": {
                        "type": "object",
                        "properties": {k: v for k, v in outputs.items()},
                        "additionalProperties": False
                    },
                    "trace": {"type": "array", "items": {"type": "object"}}
                },
                "required": ["status"]
            }

        oas["components"]["schemas"]["CPPSMeta"]["examples"] = [meta_value]

        return oas
    

    @staticmethod
    def _latest_cpps_oas(group_id: str) -> dict | None:
        cur = openapi_collection.find(
            {"level":"cpps", "group_id": group_id, "status":"published"},
            {"_id":0,"version":1,"oas":1}
        )
        best, best_t = None, (-1,-1,-1)
        for d in cur:
            t = OpenAPIGenerator._parse_semver(d.get("version") or "")
            if t > best_t:
                best_t, best = t, d
        return best["oas"] if best else None

    @staticmethod
    def _mk_fallback_obj() -> Dict[str, Any]:
        return {"type":"object","additionalProperties": True}

    @staticmethod
    def generate_cppn_openapi(doc: dict, version: str="1.0.0") -> dict:
        gid = doc["group_id"]
        # meta per example
        meta_value = {
            "group_id": gid,
            "name": doc.get("name"),
            "business_goal": doc.get("business_goal", ""),
            "description": doc.get("description"),
            "diagram_id": doc.get("diagram_id"),
            "group_type": "CPPN",
            "workflow_type": doc.get("workflow_type"),
            "actors": doc.get("actors", []),
            "gdpr_map": doc.get("gdpr_map", {}),
            "workflow": doc.get("workflow", {}),
            "components": doc.get("components", []),
            "endpoints": doc.get("endpoints", []),
        }

        get_op = {
            "summary": "Get CPPN definition",
            "tags": ["Definition"],
            "operationId": f"cppn_get_{gid}",
            "responses": {
                "200": {"description": "Definition",
                    "content": {"application/json":{
                        "schema": {"$ref":"#/components/schemas/CPPNMeta"},
                        "examples":{"current":{"value": meta_value}}
                    }}
                }
            }
        }

        post_op = {
            "summary": "Invoke CPPN orchestration",
            "tags": ["Execution"],
            "operationId": f"cppn_invoke_{gid}",
            "requestBody": {"required": True, "content":{
                "application/json": {"schema":{"$ref":"#/components/schemas/CPPNInput"}}
            }},
            "responses": {"200":{"description":"Result","content":{
                "application/json": {"schema":{"$ref":"#/components/schemas/CPPNOutput"}}
            }}}
        }

        oas = {
            "openapi": "3.1.0",
            "jsonSchemaDialect": "https://spec.openapis.org/oas/3.1/dialect/base",
            "info": {
                "title": doc["name"],
                "version": version,
                "description": doc.get("description",""),
                "x-layer": "CPPN",
                "x-service-type": "CPPN",
                "x-group_id": gid,
                "x-diagram_id": doc.get("diagram_id"),
                "x-actors": doc.get("actors", []),
                "x-gdpr_map": doc.get("gdpr_map", {}),
                "x-workflow-type": doc.get("workflow_type"),
                "x-components": doc.get("components", []),
                "x-business_goal": doc.get("business_goal", "")
            },
            "paths": {
                f"/cppn/{gid}": {"get": get_op},
                f"/cppn/{gid}/invoke": {"post": post_op},
            },
            "components": {
                "securitySchemes": {
                    "bearerAuth": {"type":"http","scheme":"bearer","bearerFormat":"JWT"}
                },
                "schemas": {
                    "CPPNComponent": {
                        "type":"object",
                        "properties":{
                            "id":{"type":"string"},
                            "type":{"type":"string","enum":["Atomic","CPPS","External","ParallelGateway"]},
                            "targets":{"type":"array","items":{"type":"string"}}
                        },
                        "required":["id","type"],
                        "additionalProperties": False
                    },
                    "CPPNMeta": {
                        "type":"object",
                        "properties":{
                            "group_id":{"type":"string","const": gid},
                            "name":{"type":"string"},
                            "business_goal": {"type":"string"},
                            "description":{"type":"string"},
                            "diagram_id":{"type":"string"},
                            "group_type":{"type":"string","const":"CPPN"},
                            "workflow_type":{"type":"string","enum":["sequence","parallel","custom"]},
                            "actors":{"type":"array","items":{"type":"string"}},
                            "gdpr_map":{"type":"object","additionalProperties":{"type":"string"}},
                            "workflow":{
                                "type":"object",
                                "additionalProperties":{"type":"array","items":{"type":"string"}}
                            },
                            "components":{"type":"array","items":{"$ref":"#/components/schemas/CPPNComponent"}},
                            "endpoints":{"type":"array","items":{"type":"object"}}
                        },
                        "required":["group_id","name","actors","components"]
                    },
                    # saranno riempiti sotto
                    "CPPNInput": {"type":"object","properties":{},"additionalProperties": False},
                    "CPPNOutput":{
                        "type":"object",
                        "properties":{
                            "status":{"type":"string","enum":["OK","ERROR"]},
                            "results":{"type":"object","properties":{},"additionalProperties": False},
                            "trace":{"type":"array","items":{"type":"object"}}
                        },
                        "required":["status"]
                    }
                }
            },
            "security":[{"bearerAuth": []}],
            "tags":[
                {"name":"Definition","description":"CPPN definition endpoints"},
                {"name":"Execution","description":"CPPN execution endpoints"}
            ]
        }

        # --- composizione dagli OAS latest di Atomic e CPPS ---
        in_props, out_props = {}, {}
        for comp in doc.get("components", []):
            cid = comp["id"]
            ctype = comp.get("type")
            schema_in = schema_out = None

            if ctype == "Atomic":
                aoas = OpenAPIGenerator._latest_atomic_oas(cid)
                if aoas:
                    sch = (aoas.get("components") or {}).get("schemas") or {}
                    schema_in  = sch.get("AtomicInput")
                    schema_out = sch.get("AtomicOutput")
            elif ctype == "CPPS":
                coas = OpenAPIGenerator._latest_cpps_oas(cid)
                if coas:
                    sch = (coas.get("components") or {}).get("schemas") or {}
                    schema_in  = sch.get("CPPSInput")
                    schema_out = sch.get("CPPSOutput")

            in_props[cid]  = schema_in  or OpenAPIGenerator._mk_fallback_obj()
            out_props[cid] = schema_out or OpenAPIGenerator._mk_fallback_obj()

        oas["components"]["schemas"]["CPPNInput"] = {
            "type":"object", "properties": in_props, "additionalProperties": False
        }
        oas["components"]["schemas"]["CPPNOutput"]["properties"]["results"] = {
            "type":"object", "properties": out_props, "additionalProperties": False
        }

        return oas