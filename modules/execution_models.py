from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ExecutionContext:
    source: str = "unknown"
    session_id: str = "default"
    user_id: str | None = None
    actor: str | None = None
    mode: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionRequest:
    source: str
    text: str
    session_id: str = "default"
    user_id: str | None = None
    actor: str | None = None
    mode: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_input: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        source: str,
        session_id: str = "default",
        user_id: str | None = None,
        actor: str | None = None,
        mode: str = "default",
        metadata: dict[str, Any] | None = None,
        raw_input: Any = None,
    ) -> "ExecutionRequest":
        return cls(
            source=source,
            text=(text or "").strip(),
            session_id=session_id,
            user_id=user_id,
            actor=actor,
            mode=mode,
            metadata=dict(metadata or {}),
            raw_input=raw_input,
        )


@dataclass
class ExecutionResult:
    handled: bool
    route: str = "unknown"
    action: str = "noop"
    reply_text: str = ""
    data: Any = None
    requires_confirmation: bool = False
    confidence: float = 0.0
    resolution: str = "final"
    telemetry: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_execution_context(
    *,
    source: str = "unknown",
    session_id: str = "default",
    user_id: str | None = None,
    actor: str | None = None,
    mode: str = "default",
    metadata: dict[str, Any] | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        source=source,
        session_id=session_id,
        user_id=user_id,
        actor=actor,
        mode=mode,
        metadata=dict(metadata or {}),
    )


def make_success_result(
    *,
    route: str,
    action: str,
    reply_text: str = "",
    data: Any = None,
    requires_confirmation: bool = False,
    confidence: float = 1.0,
    resolution: str = "final",
    telemetry: dict[str, Any] | None = None,
) -> ExecutionResult:
    return ExecutionResult(
        handled=True,
        route=route,
        action=action,
        reply_text=reply_text,
        data=data,
        requires_confirmation=requires_confirmation,
        confidence=float(confidence),
        resolution=resolution,
        telemetry=dict(telemetry or {}),
        error=None,
    )


def make_error_result(
    *,
    route: str = "unknown",
    action: str = "error",
    reply_text: str = "",
    error: str = "unknown_error",
    data: Any = None,
    requires_confirmation: bool = False,
    confidence: float = 0.0,
    resolution: str = "final",
    telemetry: dict[str, Any] | None = None,
    handled: bool = False,
) -> ExecutionResult:
    return ExecutionResult(
        handled=handled,
        route=route,
        action=action,
        reply_text=reply_text,
        data=data,
        requires_confirmation=requires_confirmation,
        confidence=float(confidence),
        resolution=resolution,
        telemetry=dict(telemetry or {}),
        error=error,
    )
