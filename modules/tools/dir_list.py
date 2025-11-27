import os

def invoke(payload: dict):
    path = payload.get("path")
    if not path:
        return {"ok": False, "error": "missing:path"}

    path = os.path.expanduser(path)

    if not os.path.isdir(path):
        return {"ok": False, "error": f"not_a_directory: {path}"}

    try:
        items = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            typ = "dir" if os.path.isdir(full) else "file"
            items.append({"name": name, "type": typ})
        return {"ok": True, "path": path, "items": items}
    except Exception as e:
        return {"ok": False, "error": str(e)}
