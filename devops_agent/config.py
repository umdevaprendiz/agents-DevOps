"""Configuração do agente. Tudo pode ser sobrescrito por variáveis de ambiente."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    model: str = field(default_factory=lambda: os.getenv("AGENT_MODEL", "qwen3:4b"))
    # None = a biblioteca do Ollama usa OLLAMA_HOST ou http://localhost:11434
    ollama_host: str | None = field(default_factory=lambda: os.getenv("OLLAMA_HOST"))
    max_steps: int = field(default_factory=lambda: int(os.getenv("AGENT_MAX_STEPS", "12")))
    num_ctx: int = field(default_factory=lambda: int(os.getenv("AGENT_NUM_CTX", "8192")))
    max_tool_output: int = field(default_factory=lambda: int(os.getenv("AGENT_MAX_TOOL_OUTPUT", "4000")))
    audit_file: Path = field(
        default_factory=lambda: Path(os.getenv("AGENT_AUDIT_FILE", PROJECT_ROOT / "logs" / "audit.jsonl"))
    )
