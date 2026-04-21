from __future__ import annotations

from typing import Any


SUPPORTED_BACKENDS = (
    "openwakeword",
    "porcupine",
)

try:
    import numpy as np
    NUMPY_IMPORT_ERROR = None
except Exception as e:
    np = None
    NUMPY_IMPORT_ERROR = f"{type(e).__name__}: {e}"

try:
    import openwakeword
    from openwakeword import Model as OpenWakeWordModel
    OPENWAKEWORD_IMPORT_ERROR = None
except Exception as e:
    openwakeword = None
    OpenWakeWordModel = None
    OPENWAKEWORD_IMPORT_ERROR = f"{type(e).__name__}: {e}"


def hotword_backend_status(preferred_backend: str = "openwakeword") -> dict[str, Any]:
    backend = (preferred_backend or "openwakeword").strip().lower()

    if backend not in SUPPORTED_BACKENDS:
        return {
            "ok": False,
            "backend": backend,
            "available": False,
            "reason": "unsupported_backend",
        }

    if backend == "porcupine":
        return {
            "ok": True,
            "backend": backend,
            "available": False,
            "reason": "backend_not_installed",
        }

    if backend == "openwakeword":
        if OpenWakeWordModel is None:
            return {
                "ok": False,
                "backend": backend,
                "available": False,
                "reason": "import_failed",
                "error": OPENWAKEWORD_IMPORT_ERROR,
            }

        if np is None:
            return {
                "ok": False,
                "backend": backend,
                "available": False,
                "reason": "numpy_unavailable",
                "error": NUMPY_IMPORT_ERROR,
            }

        try:
            model = OpenWakeWordModel()
            raw_model_names = sorted(list(getattr(model, "models", {}).keys()))
            normalized_model_names = sorted(list(dict.fromkeys(
                name.replace("_timer", "").replace("_", " ")
                for name in raw_model_names
            )))
            return {
                "ok": True,
                "backend": backend,
                "available": True,
                "reason": "ready",
                "models": normalized_model_names,
                "raw_models": raw_model_names,
            }
        except Exception as e:
            return {
                "ok": False,
                "backend": backend,
                "available": False,
                "reason": "model_init_failed",
                "error": f"{type(e).__name__}: {e}",
            }

    return {
        "ok": False,
        "backend": backend,
        "available": False,
        "reason": "unknown_backend_state",
    }


def _normalize_openwakeword_scores(scores: dict[str, float]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for key, value in scores.items():
        name = key.replace("_timer", "").replace("_", " ")
        try:
            normalized[name] = max(float(normalized.get(name, 0.0)), float(value))
        except Exception:
            normalized[name] = float(normalized.get(name, 0.0))
    return normalized


def _detect_with_openwakeword(
    pcm_bytes: bytes | None = None,
    *,
    threshold: float = 0.5,
    target_model: str | None = None,
) -> dict[str, Any]:
    status = hotword_backend_status("openwakeword")
    if not status.get("available"):
        return {
            "ok": False,
            "backend": "openwakeword",
            "detected": False,
            "score": 0.0,
            "reason": status.get("reason"),
            "error": status.get("error"),
        }

    if pcm_bytes is None:
        return {
            "ok": True,
            "backend": "openwakeword",
            "detected": False,
            "score": 0.0,
            "reason": "no_audio",
            "models": status.get("models", []),
            "raw_scores": {},
        }

    if not isinstance(pcm_bytes, (bytes, bytearray)):
        return {
            "ok": False,
            "backend": "openwakeword",
            "detected": False,
            "score": 0.0,
            "reason": "invalid_pcm_type",
        }

    if len(pcm_bytes) < 2:
        return {
            "ok": True,
            "backend": "openwakeword",
            "detected": False,
            "score": 0.0,
            "reason": "audio_too_short",
            "models": status.get("models", []),
            "raw_scores": {},
        }

    try:
        pcm = np.frombuffer(pcm_bytes, dtype=np.int16)
    except Exception as e:
        return {
            "ok": False,
            "backend": "openwakeword",
            "detected": False,
            "score": 0.0,
            "reason": "pcm_decode_failed",
            "error": f"{type(e).__name__}: {e}",
        }

    if pcm.size == 0:
        return {
            "ok": True,
            "backend": "openwakeword",
            "detected": False,
            "score": 0.0,
            "reason": "audio_empty",
            "models": status.get("models", []),
            "raw_scores": {},
        }

    try:
        model = OpenWakeWordModel()
        raw_scores = model.predict(pcm)
        raw_scores = dict(raw_scores or {})
        normalized_scores = _normalize_openwakeword_scores(raw_scores)

        best_match = None
        best_score = 0.0
        if normalized_scores:
            best_match = max(normalized_scores, key=normalized_scores.get)
            best_score = float(normalized_scores.get(best_match, 0.0))

        target = (target_model or "").strip().lower()
        selected_match = best_match
        selected_score = best_score

        if target:
            selected_match = target
            selected_score = float(normalized_scores.get(target, 0.0))

        return {
            "ok": True,
            "backend": "openwakeword",
            "detected": selected_score >= float(threshold),
            "score": selected_score,
            "best_match": best_match,
            "selected_match": selected_match,
            "reason": "detected" if selected_score >= float(threshold) else "not_detected",
            "models": status.get("models", []),
            "raw_scores": normalized_scores,
        }
    except Exception as e:
        return {
            "ok": False,
            "backend": "openwakeword",
            "detected": False,
            "score": 0.0,
            "reason": "predict_failed",
            "error": f"{type(e).__name__}: {e}",
        }


def detect_hotword(
    pcm_bytes: bytes | None = None,
    *,
    preferred_backend: str = "openwakeword",
    threshold: float = 0.5,
    target_model: str | None = None,
) -> dict[str, Any]:
    backend = (preferred_backend or "openwakeword").strip().lower()

    if backend == "openwakeword":
        return _detect_with_openwakeword(
            pcm_bytes,
            threshold=threshold,
            target_model=target_model,
        )

    status = hotword_backend_status(backend)
    return {
        "ok": False if not status.get("available") else True,
        "backend": status.get("backend"),
        "detected": False,
        "score": 0.0,
        "reason": status.get("reason"),
        "error": status.get("error"),
    }


if __name__ == "__main__":
    raise SystemExit("voice_hotword.py is a module, not a standalone runner")
