"""Pricing — three-level cost basis + built-in/custom price tables (M3).

Cost basis priority (IMPLEMENTATION_PLAN M3 / DATA_MODEL §2.4):

1. ``hermes_estimate`` — the turn's usage snapshot carries ``Usage.cost_usd``
   → adopt the CUMULATIVE-cost delta against the session watermark (all
   ``Usage`` fields are session-cumulative, AUDIT §5.1; per-turn cost =
   adjacent snapshot difference). Currency: USD (DR-12: no auto conversion).
2. ``whale_pricing`` — tokens × unit price. Custom per-model price (the
   ``model`` table ``pricing_json`` column, user-overridable) wins over the
   built-in table; both match by SUBSTRING with the LONGEST key first
   ([DSH] ``priceFor``: prevents "pro" hitting "deepseek-reasoner-pro").
   ``reasoning`` tokens are NEVER billed separately — reasoning ⊆ output
   ([DSH] A3 issue #89), so billed components are cache_read×hit +
   input×miss + output×out (+ cache_write×write when the price declares it;
   DeepSeek bills no cache writes).
3. ``token_only`` — no price resolvable (unknown/unpriced model) or a
   counter-reset turn (increment unknowable, DATA_MODEL §3.3). The turn row
   gets ``pricing_status='unknown_model'`` with ``estimated_cost_units NULL``
   and ``currency NULL`` — **never billed as 0** (cost NULL ≠ 0, DATA_MODEL
   §8.3; schema v2 relaxed the v1 NOT NULL for exactly this honesty).

Money is 1e8 fixed-point (DATA_MODEL §1.2): every price/value is converted
through :data:`SCALE` integer units; conversions go via ``Decimal``/string
(never raw float arithmetic); overflow beyond i64 raises.

Built-in prices are DATA WITH A VERIFICATION LABEL — the DeepSeek entries
mirror the [DSH] A3 price table (peak tier; peak/valley differentiation is a
V2 item, so the conservative UPPER price is the Phase-1 default) and are
marked ``unverified`` until the user confirms them against live pricing
(never probed automatically — no real paid API calls, TEST_PLAN §0.3).

Price override semantics: a custom price REPLACES the whole quote for the
matched key (no field merge), carries its own currency, and is frozen into
``turn_cost.pricing_snapshot_json`` at settlement — later price edits never
rewrite history (DATA_MODEL §2.2 note).
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal, InvalidOperation
from typing import Any

#: fixed-point scale — 1e8 units per currency unit (8 decimal places).
SCALE = 100_000_000

#: i64 bound for a single amount column (SQLite INTEGER).
MAX_UNITS = 2**63 - 1

#: divisor mapping "per 1M tokens" prices onto token counts.
TOKENS_PER_PRICE_UNIT = 1_000_000

VALID_PRICING_CURRENCIES = ("CNY", "USD")

BASIS_HERMES = "hermes_estimate"
BASIS_WHALE = "whale_pricing"
BASIS_TOKEN_ONLY = "token_only"

STATUS_HERMES = "hermes_estimate"
STATUS_WHALE = "whale_pricing"
STATUS_UNKNOWN_MODEL = "unknown_model"


class PricingError(ValueError):
    """Invalid price specification → 4xx at the REST edge."""


# ---------------------------------------------------------------------------
# fixed-point helpers (pure; the JS half mirrors these in money.js — ACC-07)
# ---------------------------------------------------------------------------

def to_units(value: Any) -> int:
    """Convert a decimal amount (int/str/float/Decimal) into 1e8 integer units.

    Floats go through ``str()`` first (shortest-repr) so no binary-float
    artifacts enter the ledger. Raises ``PricingError`` on unparseable input
    and ``OverflowError`` beyond the i64 bound.
    """
    if value is None:
        raise PricingError("cannot convert missing amount to units")
    if isinstance(value, bool):
        raise PricingError("boolean is not a money amount")
    try:
        dec = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, ArithmeticError) as exc:
        raise PricingError(f"unparseable money amount (kind={type(value).__name__})") from exc
    units = int((dec * SCALE).to_integral_value(rounding="ROUND_FLOOR"))
    if units > MAX_UNITS or units < -MAX_UNITS:
        raise OverflowError("money amount exceeds the 1e8 fixed-point i64 range")
    return units


def units_to_decimal_string(units: int | None) -> str | None:
    """Render fixed-point units as a plain decimal string (``None`` passes through)."""
    if units is None:
        return None
    sign = "-" if units < 0 else ""
    magnitude = abs(int(units))
    whole, frac = divmod(magnitude, SCALE)
    return f"{sign}{whole}.{frac:08d}"


def check_units_bound(*parts: int) -> None:
    """Raise ``OverflowError`` when any intermediate exceeds the i64 bound."""
    for part in parts:
        if part > MAX_UNITS or part < -MAX_UNITS:
            raise OverflowError("fixed-point arithmetic exceeded the i64 range")


# ---------------------------------------------------------------------------
# built-in price table (pure data; verification labels are part of the data)
# ---------------------------------------------------------------------------

def _builtin(key: str, hit: str, miss: str, out: str, note: str) -> dict[str, Any]:
    return {
        "match": key,
        "currency": "CNY",
        "hit": to_units(hit),    # per-1M cache-read (cache hit) price in units
        "miss": to_units(miss),  # per-1M input (cache miss) price in units
        "out": to_units(out),    # per-1M output price in units
        "write": None,           # DeepSeek bills no cache writes
        "source": "builtin",
        "note": note,
    }


#: Longest-key-wins substring matching happens at resolve time; the list order
#: here is display order only.
BUILTIN_PRICES: list[dict[str, Any]] = [
    _builtin(
        "deepseek-chat", "0.04", "2", "8",
        "DeepSeek V4.1 Flash alias (peak tier, [DSH] A3 table; peak/valley split is V2; unverified-2026-10-03",
    ),
    _builtin(
        "deepseek-flash", "0.04", "2", "8",
        "DeepSeek V4.1 Flash (peak tier, [DSH] A3 table; peak/valley split is V2; unverified-2026-10-03",
    ),
    _builtin(
        "deepseek-reasoner", "0.12", "6", "24",
        "DeepSeek V4.1 Pro alias = 3x Flash (peak tier, [DSH] A3 table; unverified-2026-10-03",
    ),
    _builtin(
        "deepseek-pro", "0.12", "6", "24",
        "DeepSeek V4.1 Pro = 3x Flash (peak tier, [DSH] A3 table; unverified-2026-10-03",
    ),
]


def _match_by_longest_key(model: str, keys_and_payloads: list[tuple[str, Any]]) -> Any | None:
    """Substring match with the LONGEST key first ([DSH] ``priceFor`` discipline)."""
    lowered = model.lower()
    for key, payload in sorted(keys_and_payloads, key=lambda kp: len(kp[0]), reverse=True):
        if key and key.lower() in lowered:
            return payload
    return None


# ---------------------------------------------------------------------------
# custom prices (model.pricing_json) — validate, write, read
# ---------------------------------------------------------------------------

def validate_custom_price(pricing: Any) -> dict[str, Any]:
    """Validate a custom price spec ``{hit, miss, out[, write], currency}``.

    Bounds per [DSH] F3: each unit price 0..1,000,000 (per 1M tokens);
    currency must be CNY/USD; **no automatic FX conversion** (DR-12) — a USD
    price bills in USD, period.
    """
    if not isinstance(pricing, dict):
        raise PricingError("pricing must be an object")
    currency = pricing.get("currency")
    if currency not in VALID_PRICING_CURRENCIES:
        raise PricingError("pricing currency must be CNY or USD")
    out: dict[str, Any] = {"currency": currency, "source": "custom"}
    for field in ("hit", "miss", "out", "write"):
        if field not in pricing or pricing[field] is None:
            if field == "write":
                out[field] = None
                continue
            raise PricingError(f"pricing.{field} is required")
        raw = pricing[field]
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            raise PricingError(f"pricing.{field} must be a number")
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ArithmeticError) as exc:
            raise PricingError(f"pricing.{field} is not a number") from exc
        if value < 0 or value > Decimal(1_000_000):
            raise PricingError(f"pricing.{field} out of range (0..1000000 per 1M tokens)")
        units = int((value * SCALE).to_integral_value(rounding="ROUND_FLOOR"))
        if units > MAX_UNITS:
            raise OverflowError(f"pricing.{field} exceeds the fixed-point range")
        out[field] = units
    return out


def set_custom_price(conn: sqlite3.Connection, model: str, pricing: Any, *, now: int) -> dict[str, Any]:
    """Write (or clear with ``pricing=None``) a custom price for a model id."""
    if not isinstance(model, str) or not model.strip() or len(model) > 256:
        raise PricingError("model id must be a non-empty string")
    model = model.strip()
    now = int(now)
    if pricing is None:
        conn.execute(
            "UPDATE model SET pricing_json = NULL, pricing_source = 'none', enabled = 1 WHERE id = ?",
            (model,),
        )
        conn.execute(
            """
            INSERT INTO model(id, display_name, pricing_json, pricing_source, enabled)
            VALUES (?, NULL, NULL, 'none', 1)
            ON CONFLICT(id) DO NOTHING
            """,
            (model,),
        )
        conn.commit()
        return {"model": model, "pricing": None}

    validated = validate_custom_price(pricing)
    payload = json.dumps(
        {
            "hit": units_to_decimal_string(validated["hit"]),
            "miss": units_to_decimal_string(validated["miss"]),
            "out": units_to_decimal_string(validated["out"]),
            "write": units_to_decimal_string(validated["write"]),
            "currency": validated["currency"],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    conn.execute(
        """
        INSERT INTO model(id, display_name, pricing_json, pricing_source, enabled)
        VALUES (?, NULL, ?, 'whale_pricing', 1)
        ON CONFLICT(id) DO UPDATE SET
            pricing_json = excluded.pricing_json,
            pricing_source = 'whale_pricing',
            enabled = 1
        """,
        (model, payload),
    )
    conn.commit()
    return {"model": model, "pricing": validated}


def _custom_prices_from_db(conn: sqlite3.Connection) -> list[tuple[str, dict[str, Any]]]:
    rows = conn.execute(
        "SELECT id, pricing_json FROM model WHERE pricing_json IS NOT NULL AND enabled = 1"
    ).fetchall()
    entries: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        try:
            data = json.loads(row["pricing_json"])
        except ValueError:
            continue  # corrupt row → ignore, never break settlement
        if not isinstance(data, dict):
            continue
        try:
            validated = validate_custom_price(data)
        except (PricingError, OverflowError):
            continue
        validated["source"] = "custom"
        entries.append((row["id"], validated))
    return entries


def resolve_price(conn: sqlite3.Connection | None, model: str) -> dict[str, Any] | None:
    """Resolve the effective price quote for a model (custom → builtin).

    Returns ``None`` when nothing matches (→ ``token_only`` / unknown_model).
    """
    if not model:
        return None
    custom = _custom_prices_from_db(conn) if conn is not None else []
    if custom:
        hit = _match_by_longest_key(model, custom)
        if hit is not None:
            return hit
    return _match_by_longest_key(
        model, [(entry["match"], entry) for entry in BUILTIN_PRICES]
    )


def pricing_overview(conn: sqlite3.Connection) -> dict[str, Any]:
    """REST view: built-in table + active custom overrides (never any secret)."""
    custom = [
        {"model": model, "pricing": _quote_payload(quote)}
        for model, quote in sorted(_custom_prices_from_db(conn))
    ]
    return {
        "builtin": [_quote_payload(entry) | {"match": entry["match"]} for entry in BUILTIN_PRICES],
        "custom": custom,
        "scale": SCALE,
        "price_unit": "per 1M tokens",
        "notes": [
            "builtin prices carry an unverified-<date> label until confirmed against live pricing",
            "reasoning tokens are never billed separately (reasoning ⊆ output)",
            "custom prices replace the whole quote for the matched key and freeze into turn snapshots",
        ],
    }


def _quote_payload(quote: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "hit": quote["hit"],
        "miss": quote["miss"],
        "out": quote["out"],
        "write": quote.get("write"),
        "currency": quote["currency"],
        "source": quote["source"],
    }
    if "note" in quote:
        payload["note"] = quote["note"]
    return payload


# ---------------------------------------------------------------------------
# settlement (the ingest-side decision function)
# ---------------------------------------------------------------------------

def compute_settlement(
    conn: sqlite3.Connection | None,
    model: str,
    deltas: dict[str, Any],
    usage: dict[str, Any],
    *,
    reset: bool,
    watermark_cost_units: int | None,
) -> dict[str, Any]:
    """Decide the cost for one settled turn (see module docstring priority).

    Returns ``{cost_basis, estimated_cost_units (int|None), currency
    (str|None), pricing_status, pricing_snapshot (dict|None)}``. ``units`` is
    ``None`` for honest "no price" rows — callers must never coerce it to 0.
    """
    if reset:
        # DATA_MODEL §3.3: post-reset increment is unknowable → token_only.
        return {
            "cost_basis": BASIS_TOKEN_ONLY,
            "estimated_cost_units": None,
            "currency": None,
            "pricing_status": STATUS_UNKNOWN_MODEL,
            "pricing_snapshot": None,
        }

    cost_usd = usage.get("cost_usd")
    if cost_usd is not None:
        snapshot_units = to_units(cost_usd)
        if watermark_cost_units is None:
            delta = snapshot_units
        else:
            delta = snapshot_units - watermark_cost_units
        if delta < 0:
            delta = 0  # money never regresses within a session; never bill negative
        return {
            "cost_basis": BASIS_HERMES,
            "estimated_cost_units": delta,
            "currency": "USD",
            "pricing_status": STATUS_HERMES,
            "pricing_snapshot": {
                "source": "hermes",
                "cost_usd_cumulative": str(cost_usd),
                "cost_delta_usd": units_to_decimal_string(delta),
            },
        }

    quote = resolve_price(conn, model)
    if quote is None:
        return {
            "cost_basis": BASIS_TOKEN_ONLY,
            "estimated_cost_units": None,
            "currency": None,
            "pricing_status": STATUS_UNKNOWN_MODEL,
            "pricing_snapshot": None,
        }

    # numerator in (tokens × units-per-1M) space; single floor-divide keeps the
    # rounding error < 1 unit (1e-8 currency) per turn — ACC-07 vectors pin it.
    numerator = (
        int(deltas.get("input") or 0) * quote["miss"]
        + int(deltas.get("cache_read") or 0) * quote["hit"]
        + int(deltas.get("output") or 0) * quote["out"]
    )
    write_price = quote.get("write")
    if write_price:
        numerator += int(deltas.get("cache_write") or 0) * write_price
    check_units_bound(numerator)
    units = numerator // TOKENS_PER_PRICE_UNIT
    snapshot = {
        "matched": quote.get("match") or quote.get("source"),
        "hit": quote["hit"],
        "miss": quote["miss"],
        "out": quote["out"],
        "write": quote.get("write"),
        "currency": quote["currency"],
        "source": quote["source"],
        "price_unit": "per 1M tokens",
    }
    return {
        "cost_basis": BASIS_WHALE,
        "estimated_cost_units": units,
        "currency": quote["currency"],
        "pricing_status": STATUS_WHALE,
        "pricing_snapshot": snapshot,
    }
