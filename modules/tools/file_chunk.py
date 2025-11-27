import os

def invoke(payload: dict):
    path = payload.get("path")
    offset = payload.get("offset", 0)
    size = payload.get("size", 20000)

    if not path:
        return {"ok": False, "error": "missing:path"}

    path = os.path.expanduser(path)

    try:
        with open(path, "r", encoding="utf-8") as f:
            f.seek(offset)
            chunk = f.read(size)
        return {
            "ok": True,
            "path": path,
            "offset": offset,
            "size": size,
            "content": chunk
        }
    except Exception as e:
        return {"ok": False, "path": path, "error": str(e)}
