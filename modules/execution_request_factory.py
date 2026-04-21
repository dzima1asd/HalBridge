from __future__ import annotations

from typing import Any

from modules.execution_models import ExecutionRequest


def build_execution_request(
    *,
    text: str,
    source: str,
    session_id: str = "default",
    user_id: str | None = None,
    actor: str | None = None,
    mode: str = "default",
    metadata: dict[str, Any] | None = None,
    raw_input: Any = None,
) -> ExecutionRequest:
    return ExecutionRequest.from_text(
        text,
        source=source,
        session_id=session_id,
        user_id=user_id,
        actor=actor,
        mode=mode,
        metadata=dict(metadata or {}),
        raw_input=raw_input,
    )


def build_voice_execution_request(
    *,
    text: str,
    session_id: str = "voice_daemon",
    actor: str = "voice",
    mode: str = "default",
    metadata: dict[str, Any] | None = None,
    raw_input: Any = None,
) -> ExecutionRequest:
    return build_execution_request(
        text=text,
        source="voice",
        session_id=session_id,
        actor=actor,
        mode=mode,
        metadata=metadata,
        raw_input=raw_input,
    )


def build_server_execution_request(
    *,
    text: str,
    session_id: str = "server_api",
    actor: str = "server",
    mode: str = "default",
    metadata: dict[str, Any] | None = None,
    raw_input: Any = None,
) -> ExecutionRequest:
    return build_execution_request(
        text=text,
        source="server",
        session_id=session_id,
        actor=actor,
        mode=mode,
        metadata=metadata,
        raw_input=raw_input,
    )
