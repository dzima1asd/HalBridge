import importlib

class ToolRegistry:
    def __init__(self):
        self.tools = {}

    def register(self, name: str, module_path: str):
        mod = importlib.import_module(module_path)
        self.tools[name] = mod

    def get(self, name: str):
        return self.tools.get(name)

    def invoke(self, name: str, payload: dict):
        tool = self.get(name)
        if not tool:
            return {"ok": False, "error": f"tool_not_found: {name}"}
        if not hasattr(tool, "invoke"):
            return {"ok": False, "error": f"no_invoke_in_tool: {name}"}
        return tool.invoke(payload)


registry = ToolRegistry()
registry.register("web_fetch", "modules.tools.web_fetch")
registry.register("browser_query", "modules.tools.browser_query")
registry.register("file_access", "modules.tools.file_access")
registry.register("dir_list", "modules.tools.dir_list")
registry.register("file_search", "modules.tools.file_search")
registry.register("file_chunk", "modules.tools.file_chunk")
registry.register("file_write", "modules.tools.file_write")
