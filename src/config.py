"""Central configuration.

Every value can be overridden by an environment variable (normally set in a `.env` file
copied from `.env.example`). Nothing secret is ever hard-coded here.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv is optional at import time so tests can run without a .env file
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent


def _path(name: str, default: str) -> Path:
    raw = os.getenv(name, default)
    p = Path(raw)
    return p if p.is_absolute() else (ROOT / p)


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # ---- data -------------------------------------------------------------------------------
    docs_path: Path = field(default_factory=lambda: _path("DOCS_PATH", "data/documentation.json"))
    train_path: Path = field(default_factory=lambda: _path("TRAIN_PATH", "data/development_tickets.json"))
    storage_dir: Path = field(default_factory=lambda: _path("STORAGE_DIR", "storage"))
    chroma_path: Path = field(default_factory=lambda: _path("CHROMA_PATH", "storage/chroma"))
    decision_db: Path = field(default_factory=lambda: _path("DECISION_DB", "storage/decisions.db"))
    model_dir: Path = field(default_factory=lambda: _path("MODEL_DIR", "storage/models"))
    thresholds_path: Path = field(default_factory=lambda: _path("THRESHOLDS_PATH", "config/thresholds.json"))
    kill_switch_path: Path = field(default_factory=lambda: _path("KILL_SWITCH_PATH", "storage/KILL_SWITCH"))
    llm_cache_path: Path = field(default_factory=lambda: _path("LLM_CACHE_PATH", "storage/llm_cache.sqlite"))

    # ---- retrieval --------------------------------------------------------------------------
    # "auto" tries Chroma + all-MiniLM-L6-v2 first and falls back to a local TF-IDF index if the
    # embedding model or chromadb cannot be loaded (offline machine, CI, first run without network).
    retrieval_backend: str = field(default_factory=lambda: os.getenv("RETRIEVAL_BACKEND", "auto"))
    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
    top_k: int = field(default_factory=lambda: _int("RETRIEVAL_TOP_K", 5))

    # ---- model provider ---------------------------------------------------------------------
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openrouter"))
    openrouter_api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", "").strip())
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", "").strip())
    model_name: str = field(default_factory=lambda: os.getenv("MODEL_NAME", "meta-llama/llama-3.1-8b-instruct"))
    llm_timeout_s: float = field(default_factory=lambda: _float("LLM_TIMEOUT_SECONDS", 12.0))
    llm_max_retries: int = field(default_factory=lambda: _int("LLM_MAX_RETRIES", 3))
    llm_requests_per_minute: int = field(default_factory=lambda: _int("LLM_REQUESTS_PER_MINUTE", 18))
    # "auto": use the model when a key is configured, otherwise the extractive generator.
    # "extractive": never call the model. "llm": always try the model (still falls back on failure).
    generation_mode: str = field(default_factory=lambda: os.getenv("GENERATION_MODE", "auto"))

    # ---- behaviour --------------------------------------------------------------------------
    auto_respond_enabled: bool = field(default_factory=lambda: _bool("AUTO_RESPOND_ENABLED", True))
    metrics_port: int = field(default_factory=lambda: _int("METRICS_PORT", 0))  # 0 = do not start a server
    admin_token: str = field(default_factory=lambda: "" if os.getenv("ADMIN_TOKEN", "").strip() in ("", "change_me")
                             else os.getenv("ADMIN_TOKEN", "").strip())
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    def ensure_dirs(self) -> None:
        for p in (self.storage_dir, self.model_dir, self.chroma_path, self.decision_db.parent):
            p.mkdir(parents=True, exist_ok=True)

    @property
    def api_key(self) -> str:
        key = self.groq_api_key if self.llm_provider == "groq" else self.openrouter_api_key
        return "" if key.lower() in {"", "your_key_here", "changeme", "none"} else key


DEFAULT_THRESHOLDS = {
    # Written by `python -m src.train` from cross-validated development data; these defaults are only
    # used if that file is missing and are deliberately conservative (escalate more, not less).
    "intent_confidence_min": 0.5,
    "answerable_probability_min": 0.75,
    "retrieval_min_score": 0.2,
    "grounding_min_support": 0.5,
    "selected_by": "conservative defaults (thresholds.json missing)",
}


def load_thresholds(settings: Settings | None = None) -> dict:
    settings = settings or Settings()
    data = dict(DEFAULT_THRESHOLDS)
    try:
        data.update(json.loads(settings.thresholds_path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        pass
    except Exception:
        # A corrupt thresholds file must not take the system down; defaults are conservative.
        pass
    # Optional manual override, recorded in every decision so it is auditable.
    override = os.getenv("CONFIDENCE_THRESHOLD")
    if override:
        try:
            data["answerable_probability_min"] = float(override)
            data["selected_by"] = f"overridden by CONFIDENCE_THRESHOLD={override}"
        except ValueError:
            pass
    return data
