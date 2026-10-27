"""Loads versioned prompts from the prompts/ directory (the prompt library, Stage 3).

Each prompt file starts with a small header block:

    ---
    id: PR-03
    version: 1.2
    serves: FR-08, FR-09, FR-10
    ---
    <prompt text>

The id and version are written into every decision that used the prompt.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .config import ROOT

PROMPT_DIR = ROOT / "prompts"


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str
    serves: str
    text: str

    @property
    def tag(self) -> str:
        return f"{self.id} v{self.version}"


@lru_cache(maxsize=None)
def load_prompt(relative: str) -> Prompt:
    raw = (PROMPT_DIR / relative).read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    body = raw
    if raw.startswith("---"):
        _, header, body = raw.split("---", 2)
        for line in header.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    return Prompt(meta.get("id", relative), meta.get("version", "0"), meta.get("serves", ""), body.strip())
