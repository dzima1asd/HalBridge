from __future__ import annotations

import traceback
from flask import jsonify

from modules.server_settings import ServerSettings
from modules.service_registry import (
    get_web,
    health_snapshot,
    reset_service,
    reset_all,
)
from modules.agent_runtime import reset_api
from modules.server_kernel_bridge import (
    execute_server_agent_ask,
    execute_server_hardware_run,
    execution_result_http_payload,
)


def json_error(message, status=400, **extra):
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return jsonify(payload), status


def handle_health():
    snap = health_snapshot()
    snap["ok"] = True
    snap["service"] = ServerSettings.SERVICE_NAME
    return jsonify(snap)


def handle_agent_ask(data: dict):
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return json_error("Missing 'prompt'")

    try:
        result = execute_server_agent_ask(data=data)
        return jsonify(execution_result_http_payload(result, endpoint="/agent/ask"))
    except Exception as e:
        return json_error(
            "Execution kernel failed for /agent/ask",
            status=500,
            details=f"{type(e).__name__}: {e}",
            traceback=traceback.format_exc(),
        )


def handle_hardware_run(data: dict):
    command = (data.get("command") or "").strip()
    if not command:
        return json_error("Missing 'command'")

    try:
        result = execute_server_hardware_run(data=data)
        return jsonify(execution_result_http_payload(result, endpoint="/hardware/run"))
    except Exception as e:
        return json_error(
            "Execution kernel failed for /hardware/run",
            status=500,
            details=f"{type(e).__name__}: {e}",
            traceback=traceback.format_exc(),
        )


def handle_web_fetch(data: dict):
    module = get_web()
    if module is None:
        return json_error(
            "Web adapter unavailable",
            status=500,
            details=health_snapshot().get("web_fetch_import_error"),
        )

    url = (data.get("url") or "").strip()
    query = (data.get("query") or "").strip()

    try:
        result = module.fetch(url=url, query=query)
        return jsonify(result)
    except Exception as e:
        return json_error(
            "Web adapter fetch failed",
            status=500,
            details=f"{type(e).__name__}: {e}",
            traceback=traceback.format_exc(),
        )


def handle_runtime_reset(data: dict):
    target = (data.get("target") or "agent").strip().lower()

    try:
        if target == "agent":
            reset_api()
            reset_service("agent")
        elif target == "hardware":
            reset_service("hardware")
        elif target == "web":
            reset_service("web")
        elif target == "all":
            reset_api()
            reset_all()
        else:
            return json_error(
                "Unknown reset target",
                status=400,
                allowed=["agent", "hardware", "web", "all"],
            )

        return jsonify({
            "ok": True,
            "handled": True,
            "target": target,
            "message": f"Runtime reset completed for: {target}",
        })
    except Exception as e:
        return json_error(
            "Runtime reset failed",
            status=500,
            details=f"{type(e).__name__}: {e}",
            traceback=traceback.format_exc(),
        )
