from __future__ import annotations


def handle_project_runtime(line: str, api) -> tuple[bool, str | None]:
    if line == "project list":
        rows = api.projects.list()
        if not rows:
            return True, "(brak projektów)"
        return True, "Dostępne projekty:\n" + "\n".join(f"- {x}" for x in rows)

    if line.startswith("project new "):
        name = line[len("project new "):].strip()
        if not name:
            return True, "❌ Składnia: project new <nazwa>"
        created = api.projects.new(name)
        return True, f"✅ Utworzono i otwarto projekt: {created}"

    if line.startswith("project open "):
        name = line[len("project open "):].strip()
        if not name:
            return True, "❌ Składnia: project open <nazwa>"
        ok = api.projects.open(name)
        return True, f"✅ Otworzono projekt: {name}" if ok else f"❌ Projekt nie istnieje: {name}"

    if line == "project pwd":
        try:
            return True, str(api.projects.current_path())
        except Exception:
            return True, "(brak ścieżki projektu)"

    return False, None
