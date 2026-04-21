from __future__ import annotations

import importlib

SERVICE_PATHS = {
    "agent": "modules.agent_adapter",
    "hardware": "modules.hardware_adapter",
    "web": "modules.web_adapter",
}

_services = {
    name: {"module": None, "error": None}
    for name in SERVICE_PATHS
}

def _load(name: str):
    entry = _services[name]
    if entry["module"] is not None:
        return entry["module"]

    module_path = SERVICE_PATHS[name]
    try:
        mod = importlib.import_module(module_path)
        entry["module"] = mod
        entry["error"] = None
        return mod
    except Exception as e:
        entry["error"] = f"{type(e).__name__}: {e}"
        return None

def get_agent():
    return _load("agent")

def get_hardware():
    return _load("hardware")

def get_web():
    return _load("web")

def reset_service(name: str):
    if name not in _services:
        raise ValueError(f"Unknown service: {name}")

    module_path = SERVICE_PATHS[name]
    entry = _services[name]

    try:
        if entry["module"] is not None:
            importlib.reload(entry["module"])
        else:
            mod = importlib.import_module(module_path)
            importlib.reload(mod)
    except Exception:
        # błąd reloadu zapisze się przy następnym _load
        pass

    _services[name] = {"module": None, "error": None}

def reset_all():
    for name in list(_services.keys()):
        reset_service(name)

def health_snapshot():
    return {
        "agent_adapter": get_agent() is not None,
        "agent_import_error": _services["agent"]["error"],
        "hardware_bridge": get_hardware() is not None,
        "hardware_import_error": _services["hardware"]["error"],
        "web_fetch": get_web() is not None,
        "web_fetch_import_error": _services["web"]["error"],
    }
