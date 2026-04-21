from __future__ import annotations

import shlex


def handle_memory_runtime(line: str, api) -> tuple[bool, str | None]:
    if line.startswith("mem add "):
        txt = line[len("mem add "):].strip()
        mid = api.memory.add_memory(api.session_id, txt, kind="note", pinned=False)
        return True, f"✅ Dodano pamięć #{mid}"

    if line.startswith("mem pin "):
        try:
            mid = int(line[len("mem pin "):].strip())
            api.memory.pin_memory(mid, True)
            return True, f"✅ Przypięto pamięć #{mid}"
        except Exception:
            return True, "❌ Składnia: mem pin <id>"

    if line.startswith("mem unpin "):
        try:
            mid = int(line[len("mem unpin "):].strip())
            api.memory.pin_memory(mid, False)
            return True, f"✅ Odpięto pamięć #{mid}"
        except Exception:
            return True, "❌ Składnia: mem unpin <id>"

    if line.startswith("mem search "):
        q = line[len("mem search "):].strip()
        rows = api.memory.search_memories(api.session_id, q, limit=20)
        if not rows:
            return True, "(brak wyników)"
        lines = []
        for r in rows:
            pin = "📌" if r["pinned"] else "  "
            lines.append(f"{pin} #{r['id']} [{r['kind']}] {r['created_at']}\n  {r['content']}")
        return True, "\n".join(lines)

    if line.startswith("mem list"):
        parts = shlex.split(line)
        n = 20
        if len(parts) == 3 and parts[2].isdigit():
            n = int(parts[2])
        rows = api.memory.list_memories(api.session_id, limit=n)
        if not rows:
            return True, "(pusto)"
        lines = []
        for r in rows:
            pin = "📌" if r["pinned"] else "  "
            lines.append(f"{pin} #{r['id']} [{r['kind']}] {r['created_at']}\n  {r['content']}")
        return True, "\n".join(lines)

    if line == "mem clear":
        cnt = api.memory.clear_memories(api.session_id)
        return True, f"🗑️ Usunięto {cnt} wpisów pamięci"

    return False, None
