from __future__ import annotations

from modules.execution_metadata_factory import build_execution_metadata
from modules.execution_request_factory import build_execution_request
from modules.execution_router import execute_request


def execute_cli_hardware(text: str) -> dict:
    request = build_execution_request(
        text=text,
        source="cli",
        session_id="cli_entry",
        actor="cli_hardware",
        metadata=build_execution_metadata(
            route_hint="device",
            source_kind="cli",
            request_kind="cli_hardware",
        ),
        raw_input={"text": text},
    )
    return execute_request(request).to_dict()


def execute_cli_fallback(text: str) -> dict:
    request = build_execution_request(
        text=text,
        source="cli",
        session_id="cli_entry",
        actor="cli_fallback",
        metadata=build_execution_metadata(
            route_hint="conversation",
            source_kind="cli",
            request_kind="cli_fallback",
        ),
        raw_input={"text": text},
    )
    return execute_request(request).to_dict()


def execute_cli_intent(text: str) -> dict:
    request = build_execution_request(
        text=text,
        source="cli",
        session_id="cli_entry",
        actor="cli_intent",
        metadata=build_execution_metadata(
            route_hint="intent",
            source_kind="cli",
            request_kind="cli_intent",
        ),
        raw_input={"text": text},
    )
    return execute_request(request).to_dict()


def cli_result_to_printable(result: dict) -> str:
    reply = (result.get("reply_text") or "").strip()
    if reply:
        return reply

    data = result.get("data")
    if isinstance(data, str) and data.strip():
        return data.strip()

    error = result.get("error")
    if error:
        return f"❌ {error}"

    return "⚠️ Brak odpowiedzi."
