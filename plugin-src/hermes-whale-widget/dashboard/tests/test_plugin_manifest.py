"""Plugin manifest/catalog YAML regression (served-side parse gate).

The Hermes serve process parses ``plugin.yaml`` for every enabled plugin
(``pm/plugin_declarations.py:27`` — the exact error the 2026-10-05 deploy hit:
an unquoted colon inside the ``description`` scalar produced "mapping values
are not allowed here" and blocked the whole backend). These tests pin:

* both YAML files parse cleanly with the same rules (PyYAML safe_load);
* manifest fields match what the Hermes schema reads
  (``hermes_cli/plugins_manifest.py:33`` key whitelist, :350 provides_hooks,
  :550 data.get('provides_hooks', data.get('hooks', [])));
* no unquoted ``": "`` sequence survives in any plain scalar
  (the bug-class tripwire).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[2]

MANIFEST_KEYS_KNOWN_TO_HERMES = {
    "name", "version", "description", "author", "requires_env", "provides_tools",
    "provides_hooks", "hooks", "permissions", "config", "platforms", "capabilities",
}


_KEY_LINE = re.compile(r"^\s*[\w.-]+:\s+(\S.*)$")

def _unquoted_colon_lines(path: Path) -> list[str]:
    """Raw-text scan: ``key: <unquoted value containing ': '>`` — the exact
    bug class that blocked the 2026-10-05 deploy. Quoted / block / flow values
    are safe and skipped."""
    offenders: list[str] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if line.lstrip().startswith("#"):
            continue
        m = _KEY_LINE.match(line)
        if m:
            value = m.group(1)
            if value[0] not in "\"'|>&*#[]{}" and ": " in value:
                offenders.append(f"line {i + 1}: {value.strip()[:80]}")
    return offenders


def test_plugin_yaml_parses_and_matches_hermes_schema():
    data = yaml.safe_load((PLUGIN_ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    assert data["name"] == "whale-widget"
    assert data["version"] == "0.1.0"
    assert isinstance(data["description"], str) and data["description"].startswith("Whale accounting widget")
    # Hermes reads this exact key for agent-half hook declarations
    assert data["provides_hooks"] == ["pre_approval_request", "post_approval_response"]
    unknown = set(data) - MANIFEST_KEYS_KNOWN_TO_HERMES
    assert not unknown, f"manifest keys outside the Hermes whitelist: {unknown}"


def test_no_yaml_scalar_carries_an_unquoted_mapping_tripwire():
    """The 2026-10-05 deploy blocker: `package: agent` inside a plain scalar."""
    for name in ("plugin.yaml", "catalog/whale-widget.yaml"):
        offenders = _unquoted_colon_lines(PLUGIN_ROOT / name)
        assert not offenders, f"{name}: unquoted ': ' in scalar value(s): {offenders}"


def test_catalog_yaml_required_fields():
    data = yaml.safe_load((PLUGIN_ROOT / "catalog" / "whale-widget.yaml").read_text(encoding="utf-8"))
    assert data["name"] == "whale-widget"
    # SHA must stay quoted — all-digit pin would parse as a YAML integer (M13 note)
    assert isinstance(data["sha"], str)
