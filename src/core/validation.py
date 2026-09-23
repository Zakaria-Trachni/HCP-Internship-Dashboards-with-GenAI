"""Grounded-findings validation.

The Reporter agent writes prose findings. To keep the narrative honest,
`validate_findings` checks every number that appears in the findings
against the set of numbers the deterministic engine actually computed
(KPI values + profile statistics). Numbers that can't be matched within
a small tolerance are flagged as unsupported — catching hallucinations
like a fabricated revenue figure or an invented growth rate.

This is intentionally conservative: it only validates numbers it can
confidently extract, and it absorbs rounding differences (the prose may
say "1.3M" for a KPI of 1,325,855.86). It flags rather than blocks.
"""
from __future__ import annotations

import re
from typing import Any


# Matches numbers like: 1,234  45.6%  $1.2M  3.3K  -0.66  +12.5%  2808
# The magnitude suffix (K/M/B) must be DIRECTLY attached and at a word
# boundary, so prose like "3 measure(s)" is read as 3 — not 3,000,000
# (the 'm' of "measure" must not be mistaken for "million").
_NUM_RE = re.compile(
    r"""
    (?<![A-Za-z0-9_])          # not preceded by an identifier char
    [-+]?                       # optional sign
    \$?                         # optional currency
    (\d{1,3}(?:,\d{3})+|\d+)    # integer part, with or without thousands commas
    (?:\.\d+)?                  # optional decimal
    ([KkMmBb])?                 # optional magnitude suffix (attached only)
    %?                          # optional percent
    (?![A-Za-z])                # ...and not immediately followed by a letter
    """,
    re.VERBOSE,
)

_SUFFIX = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}

# A number must match a known value within this relative tolerance to be
# considered "supported". 2% absorbs prose rounding.
_REL_TOL = 0.02
# Absolute floor so tiny values (e.g. correlations near 0) still match.
_ABS_TOL = 0.01


def _to_float(core: str, suffix: str | None) -> float | None:
    try:
        v = float(core.replace(",", "").replace("$", "").replace("+", ""))
    except ValueError:
        return None
    if suffix:
        v *= _SUFFIX.get(suffix.lower(), 1)
    return v


def extract_numbers(text: str) -> list[float]:
    """Pull candidate numeric values out of a piece of prose."""
    out: list[float] = []
    for m in _NUM_RE.finditer(text):
        core = m.group(1)
        # Re-grab the full match to recover decimals + suffix reliably.
        whole = m.group(0)
        suffix = None
        for ch in whole:
            if ch in "KkMmBb":
                suffix = ch
                break
        # Reconstruct the numeric core including any decimal part.
        num_match = re.search(r"[-+]?\$?\d[\d,]*(?:\.\d+)?", whole)
        core_full = num_match.group(0) if num_match else core
        v = _to_float(core_full, suffix)
        if v is not None:
            # Emit each token once. We do NOT also emit a percent/fraction
            # twin here — `_known_numbers` registers both scalings of every
            # KPI, so "23.4%" still matches a KPI stored as 0.234 without
            # inflating the claim count.
            out.append(v)
    return out


def _known_numbers(
    kpis: list[dict[str, Any]],
    profile: dict[str, Any],
    anomalies: list[dict[str, Any]] | None = None,
    segments: list[dict[str, Any]] | None = None,
) -> list[float]:
    known: list[float] = []

    def add(x: Any) -> None:
        try:
            if x is None:
                return
            f = float(x)
            known.append(f)
            # Also register a percent-scaled twin so prose "33%" matches a
            # KPI value stored as a fraction 0.33 and vice-versa.
            known.append(f * 100.0)
            if abs(f) > 1:
                known.append(f / 100.0)
        except (TypeError, ValueError):
            return

    for k in kpis or []:
        add(k.get("value"))
        # Numbers embedded in the display string ("23.4% (North)").
        for v in extract_numbers(str(k.get("display", ""))):
            add(v)

    if profile:
        add(profile.get("row_count"))
        add(profile.get("column_count"))
        # Schema counts are legitimately grounded facts a report may cite
        # ("3 measures, 7 dimensions"), so register their lengths.
        for key in ("measures", "dimensions", "datetimes", "identifiers"):
            seq = profile.get(key)
            if isinstance(seq, list):
                add(len(seq))
        for col in profile.get("columns", []) or []:
            for stat in ("min", "max", "mean", "median", "std"):
                if col.get(stat) is not None:
                    add(col.get(stat))
        for c in profile.get("correlations", []) or []:
            add(c.get("pearson"))

    # Insight numbers the Reporter is encouraged to cite are also grounded.
    for a in anomalies or []:
        add(a.get("count"))
        for ex in a.get("examples", []) or []:
            add(ex.get("value"))
            add(ex.get("score"))
    for sg in segments or []:
        for side in ("top", "bottom"):
            grp = sg.get(side) or {}
            add(grp.get("mean"))
            add(grp.get("count"))
        add(sg.get("ratio"))

    return known


def _is_supported(value: float, known: list[float]) -> bool:
    for k in known:
        tol = max(_ABS_TOL, abs(k) * _REL_TOL)
        if abs(value - k) <= tol:
            return True
    return False


def validate_findings(
    findings: list[str],
    kpis: list[dict[str, Any]],
    profile: dict[str, Any],
    anomalies: list[dict[str, Any]] | None = None,
    segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check the numbers in `findings` against computed KPIs + profile
    (plus anomaly/segment insight values, which the Reporter may cite).

    Returns:
        {
          "checked": int,        # numbers examined
          "supported": int,      # numbers matched to a known value
          "unsupported": [{"finding": str, "number": str}],
          "verdict": "verified" | "partial" | "none",
        }
    """
    known = _known_numbers(kpis, profile, anomalies, segments)
    checked = 0
    supported = 0
    unsupported: list[dict[str, str]] = []

    for finding in findings or []:
        nums = extract_numbers(finding)
        # Dedupe within a finding so "50% of 50 rows" counts 50 once per token.
        seen: set[float] = set()
        for v in nums:
            key = round(v, 6)
            if key in seen:
                continue
            seen.add(key)
            checked += 1
            if _is_supported(v, known):
                supported += 1
            else:
                unsupported.append({
                    "finding": finding[:160],
                    "number": _fmt_num(v),
                })

    if checked == 0:
        verdict = "verified"  # nothing numeric to dispute
    elif supported == checked:
        verdict = "verified"
    elif supported == 0:
        verdict = "none"
    else:
        verdict = "partial"

    return {
        "checked": checked,
        "supported": supported,
        "unsupported": unsupported,
        "verdict": verdict,
    }


def _fmt_num(v: float) -> str:
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:,.4g}"
