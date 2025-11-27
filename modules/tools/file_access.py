import os

def invoke(payload: dict) -> dict:
    """
    Tool: file_access
    Oczekuje payloadu w postaci: {"path": "<ścieżka do pliku>"}
    Zwraca:
      {"ok": True, "path": "...", "content": "..."}
    albo:
      {"ok": False, "path": "...", "error": "..."}
    """
    path = payload.get("path", "")
    try:
        if not path:
            return {
                "ok": False,
                "path": path,
                "error": "missing_path",
            }

        # Normalizacja ścieżki typu ~/...
        path = os.path.expanduser(path)

        with open(path, "r", encoding="utf-8") as f:
            return {
                "ok": True,
                "path": path,
                "content": f.read(),
            }

    except Exception as e:
        return {
            "ok": False,
            "path": path,
            "error": str(e),
        }
