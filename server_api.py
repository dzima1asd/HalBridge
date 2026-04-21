from flask import Flask, request
from modules.server_settings import ServerSettings
from modules.server_handlers import (
    json_error,
    handle_health,
    handle_agent_ask,
    handle_hardware_run,
    handle_web_fetch,
    handle_runtime_reset,
)

app = Flask(__name__)

API_TOKEN = ServerSettings.api_token()



def check_auth(req):
    auth = req.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
    else:
        token = req.headers.get("X-API-Token", "").strip()
    return token == API_TOKEN


@app.before_request
def require_auth():
    if request.path == "/health":
        return
    if not check_auth(request):
        return json_error("Unauthorized", status=401)


@app.route("/health", methods=["GET"])
def health():
    return handle_health()

@app.route("/agent/ask", methods=["POST"])
def agent_ask():
    data = request.get_json(silent=True) or {}
    return handle_agent_ask(data)

@app.route("/hardware/run", methods=["POST"])
def hardware_run():
    data = request.get_json(silent=True) or {}
    return handle_hardware_run(data)

@app.route("/web/fetch", methods=["POST"])
def web_fetch_route():
    data = request.get_json(silent=True) or {}
    return handle_web_fetch(data)

@app.route("/runtime/reset", methods=["POST"])
def runtime_reset():
    data = request.get_json(silent=True) or {}
    return handle_runtime_reset(data)

if __name__ == "__main__":
    host = ServerSettings.host()
    port = ServerSettings.port()
    app.run(host=host, port=port, debug=False, threaded=False)
