"""Persistent desktop settings (never the Gemini API key)."""

from __future__ import annotations

import json
import socket
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from .paths import AppPaths
from .security import atomic_write_text

# Verified against the official Gemini API pricing/model pages on this date.
GEMINI_MODEL = "gemini-3.8-flash"
GEMINI_MODEL_VERIFIED = "2026-10-21"
GEMINI_API_DOCS = "https://ai.google.dev/gemini-api/docs"

# Simple-and-fast free-tier brain. One-shot ask = no tool calling and no
# screen automation, so the whole free catalogue is usable; this model needs
# neither audio input nor tools. Verified live on 2026-10-23 (~1.4 s latency,
# 262k-token context, completed the COMMAND format on the first try).
OPENROUTER_DEFAULT_MODEL = "poolside/laguna-s-2.1:free"
# Backup ids used when the primary is removed or throttled. gemma MoE (fast),
# laguna-xs (same family, smaller), minimax flash (fast when its pool returns).
OPENROUTER_FALLBACK_MODELS = (
    "google/gemma-4-26b-a4b-it:free,poolside/laguna-xs-2.1:free,minimax/minimax-m3.1-flash:free"
)
OPENROUTER_MODELS_URL = "https://openrouter.ai/models"

# Qwen on xkiro — OpenAI-compatible endpoint (https://api.xkiro.com/v1).
# Verified live on 2026-10-24: GET /v1/models answers without a key (public
# catalogue), chat completions require Authorization: Bearer <key>.  Qwen3
# Omni Flash is the free-tier default (~262k context); the fallback chain
# stays on free ids.
XKIRO_BASE_URL = "https://api.xkiro.com/v1"
# The brain the owner wants: free Qwen3.8 Omni Flash on xkiro. Their account
# shows ~1M-token context and up to 65K output tokens; verified live against
# GET /v1/models (97 ids) and one chat completion on 2026-10-24 (~1.5 s).
# One-shot ask = no tool calling and no screen automation, so free ids work.
XKIRO_DEFAULT_MODEL = "qwen/qwen3.8-omni-flash:free"
XKIRO_FALLBACK_MODELS = (
    "qwen/qwen3.5-omni-flash:free,qwen/qwen3.7-flash:free,qwen/qwen3-vl-plus:free"
)
AI_PROVIDERS = ("xkiro", "openrouter", "gemini")


class ConfigError(RuntimeError):
    pass


@dataclass
class Config:
    display_name: str = ""
    port: int = 8765
    bind_host: str = "0.0.0.0"

    ai_provider: str = "xkiro"
    gemini_model: str = GEMINI_MODEL
    openrouter_model: str = OPENROUTER_DEFAULT_MODEL
    # Tried in order when the primary model is gone (404), throttled (429) or
    # its provider is down. Comma-separated model ids.
    openrouter_fallback_models: str = OPENROUTER_FALLBACK_MODELS
    # Qwen on xkiro (OpenAI-compatible). Its key lives in secrets.json as
    # xkiro_api_key; without one the holder falls back to another provider.
    xkiro_base_url: str = XKIRO_BASE_URL
    xkiro_model: str = XKIRO_DEFAULT_MODEL
    xkiro_fallback_models: str = XKIRO_FALLBACK_MODELS
    use_mock_ai: bool = False
    allow_screenshots_to_gemini: bool = False
    screen_awareness_enabled: bool = True
    send_screen_text_to_gemini: bool = True

    confirm_actions: bool = True
    # Codeless pairing: the phone can connect with one tap; the desktop owner
    # still confirms every new phone through the Allow/Deny dialog.
    allow_codeless_pairing: bool = True
    control_enabled_at_startup: bool = False
    emergency_hotkey: str = "<ctrl>+<alt>+s"
    overlay_hotkey: str = "<ctrl>+<alt>+h"
    point_hotkey: str = "<ctrl>+<alt>+p"

    overlay_visible: bool = True
    # Kept for config compatibility. The desktop cursor only moves when a
    # pointing tool asks it to; it never follows the real mouse pointer.
    overlay_follow_pointer: bool = False
    overlay_screen_index: int = -1  # -1 means the primary screen

    max_audio_bytes: int = 12 * 1024 * 1024
    max_text_chars: int = 4000
    # Generous by design: OpenRouter free-tier models allow ~20 requests/minute
    # and up to 1000/day on funded accounts; the local limit sits at the same
    # ceiling so it protects without starving the tiny one-shot brain.
    max_requests_per_minute: int = 20
    max_requests_per_day: int = 500
    tool_round_limit: int = 6  # unused since tool calling was removed; kept for config compatibility
    http_timeout_seconds: int = 75

    meeting_chunk_seconds: int = 300
    meeting_retain_audio: bool = True
    meeting_transcribe: bool = True
    meeting_transcription_model: str = GEMINI_MODEL

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = f"BerryLink on {socket.gethostname()}"
        self.validate()

    def validate(self) -> None:
        if not 1 <= int(self.port) <= 65535:
            raise ConfigError("port must be between 1 and 65535")
        if self.ai_provider not in AI_PROVIDERS:
            raise ConfigError(f"ai_provider must be one of {', '.join(AI_PROVIDERS)}")
        model = self.openrouter_model.strip()
        if len(model) > 120 or any(c.isspace() for c in model):
            raise ConfigError("openrouter_model must look like an OpenRouter model id")
        self.openrouter_model = model
        chain = ",".join(part.strip() for part in (self.openrouter_fallback_models or "").split(",") if part.strip())
        for part in chain.split(","):
            if len(part) > 120 or any(c.isspace() for c in part):
                raise ConfigError("openrouter_fallback_models entries must look like model ids")
        if len(chain) > 600:
            raise ConfigError("openrouter_fallback_models is too long")
        self.openrouter_fallback_models = chain
        if not self.display_name.strip() or len(self.display_name) > 80:
            raise ConfigError("display name must be 1-80 characters")
        if not self.bind_host.strip():
            raise ConfigError("bind host may not be empty")
        if not 1 <= int(self.max_requests_per_minute) <= 60:
            raise ConfigError("max_requests_per_minute must be 1-60")
        if not 1 <= int(self.max_requests_per_day) <= 1000:
            raise ConfigError("max_requests_per_day must be 1-1000")
        if not 1 <= int(self.tool_round_limit) <= 12:
            raise ConfigError("tool_round_limit must be 1-12")
        if not 1 <= int(self.max_audio_bytes) <= 12 * 1024 * 1024:
            raise ConfigError("max_audio_bytes must be at most 12 MiB")
        if not 30 <= int(self.http_timeout_seconds) <= 300:
            raise ConfigError("http_timeout_seconds must be 30-300")
        if not 60 <= int(self.meeting_chunk_seconds) <= 360:
            raise ConfigError("meeting_chunk_seconds must be 60-360")

    @classmethod
    def load(cls, paths: AppPaths) -> "Config":
        path = paths.config_file
        if not path.exists():
            cfg = cls()
            cfg.save(paths)
            return cfg
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("root is not an object")
            known = {f.name for f in fields(cls)}
            data: dict[str, Any] = {
                k: v for k, v in raw.items() if k in known
            }
            return cls(**data)
        except (OSError, ValueError, TypeError) as exc:
            raise ConfigError(f"Could not read {path}: {exc}") from exc

    def save(self, paths: AppPaths) -> None:
        self.validate()
        payload = json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"
        atomic_write_text(paths.config_file, payload, mode=0o600)

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_config(paths: AppPaths | None = None) -> Config:
    p = paths or AppPaths.default()
    p.ensure()
    return Config.load(p)
