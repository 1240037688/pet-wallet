"""Vendor template registry (M4: DeepSeek only; M11 generalises).

M4 keeps this intentionally minimal — one active provider, resolved by id.
M11 will move template instantiation here ([DSH] F1 shape: name / currency /
keyRef / balance url+auth+json path+scale / probeUrl / matchIds / noBalanceApi)
with the "field-verified only" admission rule.
"""

from __future__ import annotations

from typing import Any

from .deepseek import DeepSeekProvider
from .codex import CodexProvider

_PROVIDERS: dict[str, type] = {
    DeepSeekProvider.id: DeepSeekProvider,
    CodexProvider.id: CodexProvider,
}


def get_provider(provider_id: str) -> Any:
    """Return the provider instance or raise KeyError (unknown id)."""
    return _PROVIDERS[provider_id]()


def known_ids() -> list[str]:
    return sorted(_PROVIDERS)
