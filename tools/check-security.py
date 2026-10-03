#!/usr/bin/env python
"""check-security.py — project-wide static self-check (M0, AGENTS.md §7 / §10).

Scans ALL project sources (plugin-src/** + tools/**, minus ignored dirs) for:

  1. forbidden dynamic-code patterns: eval(, exec(, compile(, __import__,
     new Function, prototype patching, document.write, <script> injection;
  2. imports outside the allowed sets:
     - plugin-src desktop JS sources: relative imports + bare specifiers
       limited to @hermes/plugin-sdk / react* / node: builtins (the BUILT
       ARTIFACT is held to the stricter runtime-loader whitelist by
       tools/check-security.mjs);
     - tools/** scripts: node: builtins + project-local relative imports only
       (esbuild import is the recorded devDependency, package.json);
     - Python: third-party imports limited to the recorded set (AGENTS.md §10);
  3. credential-shaped plaintext: ``sk-…`` keys and ``Bearer …`` values —
     EXCEPT explicit fake test keys with the ``sk-test-fake-`` prefix
     (TEST_PLAN §2.1) and the allowlists below (each entry justified inline).

Run: .venv/Scripts/python.exe tools/check-security.py   (exit 0 = clean)

Aligned with the spirit of the official admission lint
(hermes_cli/plugin_validate_desktop.py) — not a substitute for it (M13).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SCAN_DIRS = [
    PROJECT_ROOT / "plugin-src",
    PROJECT_ROOT / "tools",
]
SKIP_DIR_NAMES = {
    "__pycache__", "node_modules", ".venv", "dist", ".git",
    "references", "experiments",  # AGENTS.md §2: never enter release artifacts
    ".preview-build",             # dev-preview generated bundles
}
SCAN_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".json", ".yaml", ".yml", ".md"}

# Desktop source import whitelist (runtime-loader rule, IMPLEMENTATION_PLAN §3.3).
JS_ALLOWED_BARE = {
    "@hermes/plugin-sdk",
    "react",
    "react/jsx-runtime",
    "react/jsx-dev-runtime",
}
JS_BARE_PREFIX_ALLOWED = ("node:",)  # node builtins (tests / dev tools only)

# Python import allowlist. First-party + recorded third-party (AGENTS.md §10:
# every entry carries a reason; expand deliberately, never silently).
PY_ALLOWED_IMPORTS = {
    # first-party
    "whale_core": "dashboard business package (imported via plugin_api sys.path bootstrap)",
    "conftest": "pytest fixture sharing inside dashboard/tests",
    # third-party
    "fastapi": "dashboard REST half (router, mounted by hermes serve)",
    "pydantic": "fastapi dependency (payload models from M1)",
    "httpx": "M4 provider client (injectable transport, TEST_PLAN §2.1)",
    "pytest": "test framework only (dashboard/tests)",
    "hermes_constants": "Hermes host runtime (guarded import; profile home resolution)",
}

# Credential-shape detection (sk-test-fake- prefix = sanctioned fake, TEST_PLAN §2.1).
SK_RE = re.compile(r"\bsk-(?!test-fake-)[A-Za-z0-9_\-]{8,}\b")
BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=\-]{6,}", re.IGNORECASE)

# Files that legitimately CONTAIN credential shapes because they implement or
# exercise the redaction/detection:
#   - whale_core redaction filter + REST-side secret scan;
#   - both checkers (pattern definitions);
#   - test_logging_redaction (SEC-01 asserts the redaction with fake keys).
CREDENTIAL_SHAPE_ALLOWLIST = {
    "plugin-src/hermes-whale-widget/dashboard/whale_core/logging_setup.py",
    "plugin-src/hermes-whale-widget/dashboard/whale_core/security.py",
    "tools/check-security.py",
    "tools/check-security.mjs",
    # SEC-01 test: feeds FAKE credential shapes to assert redaction works.
    "plugin-src/hermes-whale-widget/dashboard/tests/test_logging_redaction.py",
}

# Files allowed to contain otherwise-forbidden code patterns, with reasons:
#   - tools/check-security.*      (they DEFINE the patterns they scan for);
#   - tools/dev-preview.mjs       (generates preview HTML — real <script> tags
#                                  by design; dev tool, never in the artifact);
#   - desktop/tests/artifact.test.mjs (scanner smoke: deliberately embeds
#                                  bad-shape test vectors for scanArtifact).
FORBIDDEN_PATTERN_ALLOWLIST = {
    "tools/check-security.py",
    "tools/check-security.mjs",
    "tools/dev-preview.mjs",
    "plugin-src/hermes-whale-widget/desktop/tests/artifact.test.mjs",
}

# (name, regex). Lookbehinds keep re.compile / regex .exec from false-positive.
FORBIDDEN: list[tuple[str, re.Pattern[str]]] = [
    ("eval(", re.compile(r"(?<![.\w])eval\s*\(")),
    ("exec(", re.compile(r"(?<![.\w])exec\s*\(")),
    ("compile(", re.compile(r"(?<![.\w])compile\s*\(")),
    ("__import__", re.compile(r"\b__import__\s*\(")),
    ("new Function", re.compile(r"\bnew\s+Function\b")),
    ("prototype patch", re.compile(
        r"__proto__|Object\.defineProperty\s*\(\s*(Object|Array|String|Number|Promise)\.prototype")),
    ("document.write", re.compile(r"(?<![.\w])document\.write\s*\(")),
    ("<script> injection", re.compile(r"<script\b", re.IGNORECASE)),
]


def iter_files() -> list[Path]:
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for path in sorted(scan_dir.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.suffix.lower() not in SCAN_SUFFIXES:
                continue
            files.append(path)
    return files


def rel(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


# tools/** scripts may additionally import these bare specifiers (dev-only;
# never bundled into the release artifact):
TOOLS_BARE_ALLOWED = {"esbuild", "react", "react-dom", "react-dom/client"}


def _js_import_findings(rel_posix: str, line: str, findings: list[str]) -> None:
    """Import-whitelist check. Strict for plugin-src sources; looser for tools/
    dev scripts (node builtins, project-relative, TOOLS_BARE_ALLOWED)."""
    in_plugin_src = rel_posix.startswith("plugin-src/")

    def tools_disallowed(spec: str) -> bool:
        if spec.startswith((".", "/")) or spec.startswith(JS_BARE_PREFIX_ALLOWED):
            return False
        return spec not in TOOLS_BARE_ALLOWED

    for match in re.finditer(r"\bimport\s*\(\s*['\"]([^'\"]+)['\"]", line):
        spec = match.group(1)
        if in_plugin_src:
            if _bare_disallowed(spec):
                findings.append(f"{rel_posix}: dynamic import outside whitelist: {spec}")
        elif tools_disallowed(spec):
            findings.append(f"{rel_posix}: unexpected dynamic import target: {spec}")

    static = re.search(r"^\s*import\s[^'\"]*['\"]([^'\"]+)['\"]", line)
    if static:
        spec = static.group(1)
        if in_plugin_src:
            if _bare_disallowed(spec):
                findings.append(f"{rel_posix}: import outside whitelist: {spec}")
        elif tools_disallowed(spec):
            findings.append(f"{rel_posix}: unexpected import target: {spec}")


def _bare_disallowed(spec: str) -> bool:
    if spec.startswith("."):
        return False
    if spec in JS_ALLOWED_BARE:
        return False
    if spec.startswith(JS_BARE_PREFIX_ALLOWED):
        return False
    return True


def scan_file(path: Path) -> list[str]:
    findings: list[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    is_python = path.suffix == ".py"
    is_js = path.suffix in {".js", ".mjs", ".cjs"}
    rel_posix = rel(path)
    pattern_allowed = rel_posix in FORBIDDEN_PATTERN_ALLOWLIST
    cred_allowed = rel_posix in CREDENTIAL_SHAPE_ALLOWLIST

    for lineno, line in enumerate(text.splitlines(), start=1):
        if not pattern_allowed:
            for name, pattern in FORBIDDEN:
                if pattern.search(line):
                    findings.append(f"{rel_posix}:{lineno}: forbidden pattern {name}")

        if is_js:
            _js_import_findings(rel_posix, line, findings)

        if is_python:
            match = re.match(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_.]*)", line)
            if match:
                root_module = match.group(1).split(".")[0]
                if root_module not in PY_ALLOWED_IMPORTS and not _is_stdlib(root_module):
                    findings.append(
                        f"{rel_posix}:{lineno}: import not in allowlist "
                        f"(add to PY_ALLOWED_IMPORTS with justification): {root_module}"
                    )

        if not cred_allowed:
            if SK_RE.search(line):
                findings.append(f"{rel_posix}:{lineno}: credential-shaped plaintext (sk-…)")
            if BEARER_RE.search(line):
                findings.append(f"{rel_posix}:{lineno}: credential-shaped plaintext (Bearer …)")

    return findings


def _is_stdlib(module: str) -> bool:
    try:
        return module in sys.stdlib_module_names  # py3.10+
    except AttributeError:  # pragma: no cover
        return False


def main() -> int:
    files = iter_files()
    findings: list[str] = []
    for path in files:
        findings.extend(scan_file(path))

    print(f"check-security.py: scanned {len(files)} files under plugin-src/ + tools/")
    if not findings:
        print("check-security.py: OK — no forbidden patterns, imports within allowlist, no credential plaintext")
        return 0
    print(f"check-security.py: FAILED — {len(findings)} finding(s):")
    for finding in findings:
        print(f"  - {finding}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
