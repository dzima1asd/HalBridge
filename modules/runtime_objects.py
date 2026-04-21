from modules.hardware_adapter import get_bridge
from modules.browser_bridge import BrowserBridge

_bridge = None
_browser = None


def build_runtime_objects():
    global _bridge, _browser

    if _bridge is None:
        _bridge = get_bridge()

    if _browser is None:
        _browser = BrowserBridge()

    return _bridge, _browser
