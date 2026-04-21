from __future__ import annotations
import importlib.util
import shlex
from typing import Tuple
from typing import List
from typing import Optional, List
from pathlib import Path
from modules.runtime_core import Config, RotatingLogger
class ModuleRunner:
    """
    Ładowanie i uruchamianie prostych modułów z katalogu 'modules'.
    Moduł to:
      - plik:   modules/<nazwa>.py
      - albo pkg: modules/<nazwa>/__init__.py
    Wymagana funkcja: main(args) (args: lista lub None)
    Opcjonalnie: __doc__ do opisu.
    """
    def __init__(self, cfg: Config, logger: RotatingLogger, base_dir: str = "modules"):
        self.cfg = cfg
        self.logger = logger
        self.base = Path(base_dir)

    def _module_file(self, name: str) -> Optional[Path]:
        p_file = self.base / f"{name}.py"
        p_pkg = self.base / name / "__init__.py"
        if p_file.exists():
            return p_file
        if p_pkg.exists():
            return p_pkg
        return None

    def list(self) -> List[str]:
        mods: List[str] = []
        if not self.base.exists():
            return mods

        for p in self.base.iterdir():
            name: Optional[str] = None
            mf: Optional[Path] = None

            if p.is_file() and p.suffix == ".py":
                name = p.stem
                mf = p
            elif p.is_dir() and (p / "__init__.py").exists():
                name = p.name
                mf = p / "__init__.py"

            if not name or not mf:
                continue

            try:
                spec = importlib.util.spec_from_file_location(f"modules.{name}", mf)
                if not spec or not spec.loader:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[attr-defined]
                if hasattr(mod, "main"):
                    mods.append(name)
            except Exception:
                continue

        return sorted(mods)

    def run(self, name: str, args: str = "") -> Tuple[bool, str]:
        mf = self._module_file(name)
        if not mf:
            return False, f"❌ Brak modułu: {self.base / (name + '.py')}"
        try:
            spec = importlib.util.spec_from_file_location(f"modules.{name}", mf)
            if not spec or not spec.loader:
                return False, "❌ Nie mogę załadować spec modułu."
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[attr-defined]
            if not hasattr(mod, "main"):
                return False, "❌ Moduł nie ma funkcji main(args)"
            argv = shlex.split(args) if isinstance(args, str) else (args or [])
            res = mod.main(argv)
            return True, str(res) if res is not None else "✅ OK"
        except Exception as e:
            return False, f"❌ Błąd modułu: {e}"

    def info(self, name: str) -> str:
        mf = self._module_file(name)
        if not mf:
            return "❌ Brak modułu."
        try:
            spec = importlib.util.spec_from_file_location(f"modules.{name}", mf)
            if not spec or not spec.loader:
                return "❌ Nie mogę załadować spec modułu."
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[attr-defined]
            doc = getattr(mod, "__doc__", None)
            return (doc or "(brak opisu)").strip()
        except Exception as e:
            return f"❌ Błąd info: {e}"

# =================== GPTChatAPI (LLM + pamięć + tokeny + projekty + logi + sieć) ===================

