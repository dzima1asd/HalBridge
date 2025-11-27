#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
modules/auto_fix.py – Faza 6: naprawa automatyczna (wersja kompletna, stabilna)
Czyta ~/.local/share/halbridge/auto_patch.log, wyszukuje błędne pliki,
dla każdego tworzy kopię .bak, generuje poprawkę, testuje ją
i jeśli przejdzie kompilację i sandbox — zapisuje.
"""

from pathlib import Path
import json, shutil, time, py_compile, tempfile

# --- Importy zależne ---
try:
    from modules import intelligence
except Exception:
    intelligence = None

try:
    from modules import code as code_sandbox
except Exception:
    code_sandbox = None

try:
    from modules import code_registry
except Exception:
    code_registry = None


LOG = Path.home() / ".local/share/halbridge/auto_patch.log"

def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")

def load_failures(limit=20):
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            out.append(json.loads(line))
        except:
            pass
    return out

def backup_file(path: Path):
    bak = path.with_suffix(path.suffix + f".bak_{int(time.time())}")
    shutil.copy2(path, bak)
    return bak

def _compile_ok(path: Path) -> bool:
    try:
        py_compile.compile(str(path), doraise=True)
        return True
    except Exception:
        return False

def _sandbox_ok(path: Path) -> bool:
    if not code_sandbox:
        return True
    res = code_sandbox.run_file(str(path), profile="headless")
    return bool(res.get("ok"))


# ======================================================================
#                      WŁAŚCIWA FUNKCJA attempt_fix()
# ======================================================================

def attempt_fix(path: Path, stderr: str):
    print(f"\n🧠 Próba naprawy: {path.name}")

    if not path.exists():
        print(f"⚠️ Plik nie istnieje: {path}")
        return

    if not intelligence:
        print("⚠️ Brak modułu intelligence — tylko backup.")
        backup_file(path)
        return

    src = path.read_text(encoding="utf-8", errors="ignore")

    # Nowy, wyczyszczony prompt „napisz od nowa”
    prompt = (
        "Napisz OD NOWA kompletną, poprawioną, działającą wersję tego pliku Python. "
        "Zwróć WYŁĄCZNIE pełną zawartość pliku, bez komentarzy i bez ```python.\n\n"
        f"Błąd oryginalny:\n{stderr}\n\n"
        "----- ORYGINAŁ PLIKU -----\n"
        f"{src}\n"
        "---------------------------\n"
    )

    for n in range(1, 4):
        print(f"  ▶ próba {n}/3")

        try:
            candidate = intelligence.suggest_fix(prompt)
        except Exception as e:
            print("  ❌ Błąd przy komunikacji z intelligence:", e)
            return

        if not isinstance(candidate, str) or len(candidate.strip()) < 5:
            print("  ❌ Odpowiedź AI nie wygląda jak kod — pomijam")
            continue

        tmp = Path(tempfile.gettempdir()) / f"afix_{int(time.time())}_{path.name}"
        tmp.write_text(candidate, encoding="utf-8")

        if not _compile_ok(tmp):
            print("  ❌ kompilacja nieudana — kolejna próba")
            continue

        if not _sandbox_ok(tmp):
            print("  ❌ sandbox nie zaakceptował — kolejna próba")
            continue

        # Sukces — zapisujemy
        backup_file(path)
        path.write_text(candidate, encoding="utf-8")
        print("  ✅ Poprawka zatwierdzona i zapisana.")

        if code_registry:
            code_registry.register_path(
                str(path),
                project="auto-fix",
                meta={"ts": _now(), "src": "auto_fix", "status": "applied"},
            )

        return

    print("❌ Nie udało się naprawić pliku po 3 próbach.")


# ======================================================================
#                               MAIN
# ======================================================================

def main():
    fails = load_failures()
    if not fails:
        print("Brak błędów do naprawy.")
        return

    for entry in fails:
        p = Path(entry.get("path") or "")
        err = entry.get("stderr", "")
        if not p or not err:
            continue
        attempt_fix(p, err)


if __name__ == "__main__":
    main()
