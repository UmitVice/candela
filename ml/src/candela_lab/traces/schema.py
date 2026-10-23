import re
from typing import Any

_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}


def _check(schema: dict[str, Any], value: Any, path: str, out: list[str]) -> None:
    t = schema.get("type")
    if isinstance(t, str) and t in _TYPES:
        ok = isinstance(value, _TYPES[t]) and not (t in ("integer", "number") and isinstance(value, bool))
        if not ok:
            out.append(f"{path}: expected {t}")
            return
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{path}: not one of {schema['enum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            out.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{path}: does not match {schema['pattern']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{path}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{path}: above {schema['maximum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in value:
                out.append(f"{path}.{req}: required")
        for k, v in value.items():
            if k in props:
                _check(props[k], v, f"{path}.{k}", out)
            elif schema.get("additionalProperties") is False:
                out.append(f"{path}.{k}: unexpected property")


def validate_arguments(schema: dict[str, Any], arguments: Any) -> list[str]:
    problems: list[str] = []
    _check({**schema, "type": "object"}, arguments, "arguments", problems)
    return problems
