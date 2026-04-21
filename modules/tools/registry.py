import importlib


class ToolRegistry:
    def __init__(self):
        self._module_paths = {}
        self._tools = {}
        self._errors = {}

    def register(self, name: str, module_path: str):
        self._module_paths[name] = module_path

    def _load(self, name: str):
        if name in self._tools:
            return self._tools[name]

        module_path = self._module_paths.get(name)
        if not module_path:
            return None

        try:
            mod = importlib.import_module(module_path)
            self._tools[name] = mod
            self._errors.pop(name, None)
            return mod
        except Exception as e:
            self._errors[name] = f"{type(e).__name__}: {e}"
            return None

    def get(self, name: str):
        return self._load(name)

    def get_error(self, name: str):
        return self._errors.get(name)

    def registered_names(self):
        return sorted(self._module_paths.keys())

    def invoke(self, name: str, payload: dict):
        tool = self.get(name)
        if not tool:
            err = self.get_error(name)
            if err:
                return {"ok": False, "error": f"tool_import_failed: {name}", "details": err}
            return {"ok": False, "error": f"tool_not_found: {name}"}

        if not hasattr(tool, "invoke"):
            return {"ok": False, "error": f"no_invoke_in_tool: {name}"}

        return tool.invoke(payload)


registry = ToolRegistry()
registry.register("web_fetch", "modules.tools.web_fetch")
registry.register("web_orchestrator", "modules.tools.web_orchestrator")
registry.register("browser_query", "modules.tools.browser_query")
registry.register("file_access", "modules.tools.file_access")
registry.register("dir_list", "modules.tools.dir_list")
registry.register("file_search", "modules.tools.file_search")
registry.register("file_chunk", "modules.tools.file_chunk")
registry.register("file_write", "modules.tools.file_write")
