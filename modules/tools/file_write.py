import os

def invoke(payload: dict):
    path = payload.get("path")
    content = payload.get("content")

    if not path:
        return {"ok": False, "error": "missing:path"}

    path = os.path.expanduser(path)

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "path": path}
    except Exception as e:
        return {"ok": False, "path": path, "error": str(e)}
