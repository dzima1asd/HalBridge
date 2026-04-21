from __future__ import annotations

from typing import Any

from modules.execution_request_factory import build_server_execution_request
from modules.execution_metadata_factory import build_server_execution_metadata
from modules.execution_router import execute_request


def execution_result_http_payload(result: dict, *, endpoint: str) -> dict:
    payload = dict(result)
    payload["ok"] = bool(payload.get("handled", False)) and not bool(payload.get("error"))
    payload["endpoint"] = endpoint
    return payload


def execute_server_agent_ask(*, data: dict[str, Any]) -> dict:
    prompt = (data.get("prompt") or "").strip()
    session_id = (data.get("session_id") or "server_api").strip() or "server_api"

    request = build_server_execution_request(
        text=prompt,
        session_id=session_id,
        actor="agent_ask",
        metadata=build_server_execution_metadata(
            route_hint="conversation",
            endpoint="/agent/ask",
            request_kind="agent_ask",
        ),
        raw_input=data,
    )
    return execute_request(request).to_dict()


def execute_server_hardware_run(*, data: dict[str, Any]) -> dict:
    command = (data.get("command") or "").strip()
    session_id = (data.get("session_id") or "server_api").strip() or "server_api"

    request = build_server_execution_request(
        text=command,
        session_id=session_id,
        actor="hardware_run",
        metadata=build_server_execution_metadata(
            route_hint="device",
            endpoint="/hardware/run",
            request_kind="hardware_run",
        ),
        raw_input=data,
    )
    return execute_request(request).to_dict()
