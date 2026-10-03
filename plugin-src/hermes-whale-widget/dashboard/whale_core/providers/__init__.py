"""Provider gateway package — credential-aware outbound HTTP for balance APIs.

Implemented in M4: base.py (error taxonomy + injectable httpx transport),
gateway.py (secret resolution + fingerprint + outbound origin whitelist),
deepseek.py (first vendor template), registry.py (M11 generalises).
deepseek.py is the first vendor template (M4), registry.py the user-template
store (M11).
"""

from __future__ import annotations  # noqa: F401  (stub package — implemented in M4/M11)
