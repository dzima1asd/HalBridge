import os
import re

def invoke(payload: dict):
    root = payload.get("root")
    pattern = payload.get("pattern")

    if not root or not pattern:
        return {"ok": False, "error": "missing: root or pattern"}

    root = os.path.expanduser(root)

    results = []
    rx = re.compile(pattern, re.IGNORECASE)

    for base, dirs, files in os.walk(root):
        for fn in files:
            if fn.endswith((".py", ".json", ".txt", ".md")):
                path = os.path.join(base, fn)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        for lineno, line in enumerate(f, start=1):
                            if rx.search(line):
                                results.append({
                                    "file": path,
                                    "line": lineno,
                                    "match": line.strip()
                                })
                except:
                    pass

    return {"ok": True, "results": results}
