from __future__ import annotations

from typing import Any


def build_execution_metadata(
    *,
    route_hint: str | None = None,
    source_kind: str | None = None,
    request_kind: str | None = None,
    endpoint: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {}

    if route_hint:
        meta["route_hint"] = route_hint
    if source_kind:
        meta["source_kind"] = source_kind
    if request_kind:
        meta["request_kind"] = request_kind
    if endpoint:
        meta["endpoint"] = endpoint

    if extra:
        meta.update(dict(extra))

    return meta


def build_voice_execution_metadata(
    *,
    route_hint: str,
    voice_route: str,
    route_result: dict[str, Any] | None = None,
    wake_result: dict[str, Any] | None = None,
    dispatch_result: dict[str, Any] | None = None,
    original_text: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = build_execution_metadata(
        route_hint=route_hint,
        source_kind="voice",
        request_kind="voice_execute",
        extra={
            "voice_route": voice_route,
            "route_result": dict(route_result or {}),
            "wake_result": dict(wake_result or {}),
            "dispatch_result": dict(dispatch_result or {}),
            "original_text": original_text,
        },
    )
    if extra:
        meta.update(dict(extra))
    return meta


def build_server_execution_metadata(
    *,
    route_hint: str,
    endpoint: str,
    request_kind: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_execution_metadata(
        route_hint=route_hint,
        source_kind="server",
        request_kind=request_kind,
        endpoint=endpoint,
        extra=extra,
    )
