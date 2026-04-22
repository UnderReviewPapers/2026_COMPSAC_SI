# openapi_docs/oas_validation.py
def validate_openapi(oas: dict) -> tuple[bool, list[str]]:
    """
    Se presente il pacchetto openapi-spec-validator viene usato,
    altrimenti controlli minimi.
    """
    errors = []
    try:
        from openapi_spec_validator import validate as oas_validate
        oas_validate(oas)
        return True, []
    except ImportError:
        for k in ("openapi", "info", "paths"):
            if k not in oas:
                errors.append(f"Missing: {k}")
        return (len(errors) == 0), errors
    except Exception as e:
        errors.append(str(e))
        return False, errors
