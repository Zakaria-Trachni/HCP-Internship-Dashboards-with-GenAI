"""Adaptive dataset profiler.

Given an arbitrary DataFrame, classify every column into one of a small
set of semantic roles so downstream code (KPI engine, chart builder,
report writer) can act generically.

Roles
-----
- measure          : numeric column suitable for aggregation
- dimension        : low-cardinality categorical
- high_card_dim    : high-cardinality categorical (treated specially)
- datetime         : parseable date/time column
- identifier       : looks like an ID or code, exclude from analytics
- text             : free-form text, exclude from analytics
- boolean          : 2-value flag

The role assignment is heuristic, not magical: thresholds come from
config.yaml and can be tuned without code changes.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd


class ColumnRole(str, Enum):
    MEASURE = "measure"
    DIMENSION = "dimension"
    HIGH_CARD_DIM = "high_card_dim"
    DATETIME = "datetime"
    IDENTIFIER = "identifier"
    TEXT = "text"
    BOOLEAN = "boolean"
    GEO = "geo"


@dataclass
class ColumnProfile:
    name: str
    role: ColumnRole
    dtype: str
    non_null: int
    null_count: int
    null_pct: float
    cardinality: int
    sample_values: list[Any] = field(default_factory=list)
    # Role-specific stats (populated only when relevant):
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    min_date: str | None = None
    max_date: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["role"] = self.role.value
        return d


@dataclass
class DatasetProfile:
    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    measures: list[str]
    dimensions: list[str]
    datetimes: list[str]
    identifiers: list[str]
    # Columns whose values are recognizable country names (usable as a
    # choropleth location). A subset of `dimensions`.
    geos: list[str] = field(default_factory=list)
    # Pearson correlations between measures (>= report threshold only):
    correlations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_count": self.row_count,
            "column_count": self.column_count,
            "columns": [c.to_dict() for c in self.columns],
            "measures": self.measures,
            "dimensions": self.dimensions,
            "datetimes": self.datetimes,
            "identifiers": self.identifiers,
            "geos": self.geos,
            "correlations": self.correlations,
        }


# Names that strongly hint a column is an identifier even if it parses
# as numeric. Kept short on purpose — we don't want to be too clever.
_ID_NAME_HINTS = ("id", "code", "uuid", "guid", "sku", "ref")


# Country / territory names recognized for geospatial detection. Lower-cased.
# Includes football-relevant entities (England, Scotland, ...) so columns of
# national teams are detected as geographic even though Plotly's country
# choropleth may not render the sub-national ones.
_COUNTRY_NAMES: frozenset[str] = frozenset(
    n.lower()
    for n in (
        "Afghanistan", "Albania", "Algeria", "Andorra", "Angola", "Antigua and Barbuda",
        "Argentina", "Armenia", "Australia", "Austria", "Azerbaijan", "Bahamas", "Bahrain",
        "Bangladesh", "Barbados", "Belarus", "Belgium", "Belize", "Benin", "Bhutan",
        "Bolivia", "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei", "Bulgaria",
        "Burkina Faso", "Burundi", "Cambodia", "Cameroon", "Canada", "Cape Verde",
        "Central African Republic", "Chad", "Chile", "China", "Colombia", "Comoros",
        "Congo", "Costa Rica", "Croatia", "Cuba", "Cyprus", "Czech Republic", "Czechia",
        "Denmark", "Djibouti", "Dominica", "Dominican Republic", "DR Congo", "Ecuador",
        "Egypt", "El Salvador", "England", "Equatorial Guinea", "Eritrea", "Estonia",
        "Eswatini", "Ethiopia", "Faroe Islands", "Fiji", "Finland", "France", "Gabon",
        "Gambia", "Georgia", "Germany", "Ghana", "Greece", "Grenada", "Guatemala", "Guinea",
        "Guinea-Bissau", "Guyana", "Haiti", "Honduras", "Hong Kong", "Hungary", "Iceland",
        "India", "Indonesia", "Iran", "Iraq", "Ireland", "Israel", "Italy", "Ivory Coast",
        "Jamaica", "Japan", "Jordan", "Kazakhstan", "Kenya", "Kosovo", "Kuwait", "Kyrgyzstan",
        "Laos", "Latvia", "Lebanon", "Lesotho", "Liberia", "Libya", "Liechtenstein",
        "Lithuania", "Luxembourg", "Macau", "Madagascar", "Malawi", "Malaysia", "Maldives",
        "Mali", "Malta", "Mauritania", "Mauritius", "Mexico", "Moldova", "Monaco", "Mongolia",
        "Montenegro", "Morocco", "Mozambique", "Myanmar", "Namibia", "Nepal", "Netherlands",
        "New Zealand", "Nicaragua", "Niger", "Nigeria", "North Korea", "North Macedonia",
        "Northern Ireland", "Norway", "Oman", "Pakistan", "Palestine", "Panama",
        "Papua New Guinea", "Paraguay", "Peru", "Philippines", "Poland", "Portugal", "Qatar",
        "Romania", "Russia", "Rwanda", "Saint Kitts and Nevis", "Saint Lucia",
        "Saint Vincent and the Grenadines", "Samoa", "San Marino", "Saudi Arabia", "Scotland",
        "Senegal", "Serbia", "Seychelles", "Sierra Leone", "Singapore", "Slovakia", "Slovenia",
        "Solomon Islands", "Somalia", "South Africa", "South Korea", "South Sudan", "Spain",
        "Sri Lanka", "Sudan", "Suriname", "Sweden", "Switzerland", "Syria", "Taiwan",
        "Tajikistan", "Tanzania", "Thailand", "Timor-Leste", "Togo", "Tonga",
        "Trinidad and Tobago", "Tunisia", "Turkey", "Turkmenistan", "Uganda", "Ukraine",
        "United Arab Emirates", "United Kingdom", "United States", "Uruguay", "Uzbekistan",
        "Vanuatu", "Venezuela", "Vietnam", "Wales", "Yemen", "Zambia", "Zimbabwe", "USA",
        "UK", "Curacao", "New Caledonia", "Tahiti", "Puerto Rico", "Gibraltar",
    )
)


def _looks_like_geo(series: pd.Series, threshold: float) -> bool:
    """True when most of a column's distinct values are country names —
    i.e. it can plausibly drive a choropleth. Value-based (not name-based)
    so it generalizes to any dataset."""
    distinct = series.dropna().astype(str).str.strip().unique()
    if len(distinct) < 2:
        return False
    matches = sum(1 for v in distinct if v.lower() in _COUNTRY_NAMES)
    return (matches / len(distinct)) >= threshold


def _looks_like_identifier(name: str, cardinality: int, row_count: int, *, is_numeric: bool) -> bool:
    """Decide whether a column looks like an identifier rather than a
    measure/dimension. We apply two signals:

    1. A name hint (`id`, `code`, `sku`, ...). Applied to both string
       and numeric columns.
    2. A uniqueness signal (cardinality / row count > 0.95). Applied
       only to non-numeric columns — a numeric measure can legitimately
       be all-unique (e.g. transaction amounts, sensor readings), and
       we don't want to lose it from analytics just because of that.
    """
    lname = name.lower()
    if any(lname == h or lname.endswith("_" + h) or lname.endswith(h) for h in _ID_NAME_HINTS):
        return True
    if not is_numeric and row_count > 20 and cardinality / max(row_count, 1) > 0.95:
        return True
    return False


def _try_parse_datetime(series: pd.Series, threshold: float) -> pd.Series | None:
    """Return a parsed datetime series if at least `threshold` of
    non-null values parse, else None."""
    non_null = series.dropna()
    if non_null.empty:
        return None
    # Already datetime?
    if pd.api.types.is_datetime64_any_dtype(non_null):
        return pd.to_datetime(series, errors="coerce")
    # Strings or objects: try parsing. Pandas 3+ uses StringDtype for
    # string columns; pandas 2 uses object. Accept either, and skip
    # numeric/bool dtypes (which we handle elsewhere).
    is_text_like = (
        pd.api.types.is_string_dtype(non_null)
        or pd.api.types.is_object_dtype(non_null)
    )
    if is_text_like and not pd.api.types.is_numeric_dtype(non_null):
        try:
            # Probing text columns will often fail to infer a format —
            # that's expected (we're checking IF the column is a date,
            # not assuming it is). Silence the noise.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=UserWarning)
                parsed = pd.to_datetime(non_null, errors="coerce", utc=False)
        except Exception:
            return None
        success_rate = parsed.notna().mean()
        if success_rate >= threshold:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=UserWarning)
                return pd.to_datetime(series, errors="coerce")
    return None


def profile_dataframe(
    df: pd.DataFrame,
    *,
    numeric_id_cardinality_threshold: int = 10,
    categorical_max_cardinality: int = 50,
    datetime_parse_threshold: float = 0.8,
    correlation_report_threshold: float = 0.5,
    geo_match_threshold: float = 0.6,
) -> DatasetProfile:
    """Profile an arbitrary DataFrame.

    The thresholds correspond to the `engine` section of config.yaml.
    """
    row_count = len(df)
    columns: list[ColumnProfile] = []

    # Make a working copy so we can promote string columns to datetime
    # without mutating the caller's DataFrame.
    work = df.copy()

    for col in work.columns:
        s = work[col]
        non_null = int(s.notna().sum())
        nulls = int(s.isna().sum())
        null_pct = round((nulls / row_count) * 100, 2) if row_count else 0.0
        card = int(s.nunique(dropna=True))
        # Sample up to 5 distinct example values for the LLM.
        try:
            sample = s.dropna().unique().tolist()[:5]
            sample = [_jsonable(v) for v in sample]
        except Exception:
            sample = []

        # --- Role inference --------------------------------------------------
        role: ColumnRole
        prof = ColumnProfile(
            name=str(col),
            role=ColumnRole.TEXT,  # placeholder
            dtype=str(s.dtype),
            non_null=non_null,
            null_count=nulls,
            null_pct=null_pct,
            cardinality=card,
            sample_values=sample,
        )

        # 1. Boolean
        if pd.api.types.is_bool_dtype(s) or (card == 2 and pd.api.types.is_numeric_dtype(s)):
            role = ColumnRole.BOOLEAN
        # 2. Datetime (native or string-parseable)
        else:
            parsed_dt = _try_parse_datetime(s, datetime_parse_threshold)
            if parsed_dt is not None:
                role = ColumnRole.DATETIME
                work[col] = parsed_dt  # promote in working copy
                non_null_dt = parsed_dt.dropna()
                if not non_null_dt.empty:
                    prof.min_date = str(non_null_dt.min())
                    prof.max_date = str(non_null_dt.max())
            # 3. Numeric → measure vs identifier vs low-card flag
            elif pd.api.types.is_numeric_dtype(s):
                if _looks_like_identifier(str(col), card, row_count, is_numeric=True):
                    role = ColumnRole.IDENTIFIER
                elif card <= numeric_id_cardinality_threshold:
                    # Low-cardinality numeric (e.g. status code) — dimension.
                    role = ColumnRole.DIMENSION
                else:
                    role = ColumnRole.MEASURE
                    non_null_num = s.dropna()
                    if not non_null_num.empty:
                        prof.min = float(non_null_num.min())
                        prof.max = float(non_null_num.max())
                        prof.mean = float(non_null_num.mean())
                        prof.median = float(non_null_num.median())
                        prof.std = float(non_null_num.std()) if len(non_null_num) > 1 else 0.0
            # 4. String / object
            else:
                # Geo is tested first and overrides the cardinality rule:
                # a column of country names is geographic even when it has
                # high cardinality (e.g. 200+ national teams).
                if _looks_like_geo(s, geo_match_threshold):
                    role = ColumnRole.GEO
                elif _looks_like_identifier(str(col), card, row_count, is_numeric=False):
                    role = ColumnRole.IDENTIFIER
                elif card <= categorical_max_cardinality:
                    role = ColumnRole.DIMENSION
                elif card > categorical_max_cardinality and card / max(row_count, 1) > 0.5:
                    # Likely free text.
                    role = ColumnRole.TEXT
                else:
                    role = ColumnRole.HIGH_CARD_DIM

        prof.role = role
        columns.append(prof)

    # --- Bucket columns by role --------------------------------------------
    measures = [c.name for c in columns if c.role == ColumnRole.MEASURE]
    # GEO columns are categorical too, so they remain usable as dimensions
    # (bar/pie) in addition to driving the choropleth.
    dimensions = [
        c.name
        for c in columns
        if c.role in (ColumnRole.DIMENSION, ColumnRole.BOOLEAN, ColumnRole.HIGH_CARD_DIM, ColumnRole.GEO)
    ]
    datetimes = [c.name for c in columns if c.role == ColumnRole.DATETIME]
    identifiers = [
        c.name for c in columns if c.role in (ColumnRole.IDENTIFIER, ColumnRole.TEXT)
    ]
    geos = [c.name for c in columns if c.role == ColumnRole.GEO]

    # --- Correlations between measures -------------------------------------
    correlations: list[dict[str, Any]] = []
    if len(measures) >= 2:
        try:
            corr = work[measures].corr(numeric_only=True)
            seen: set[tuple[str, str]] = set()
            for i, a in enumerate(measures):
                for j, b in enumerate(measures):
                    if i >= j:
                        continue
                    val = corr.loc[a, b]
                    if pd.isna(val):
                        continue
                    if abs(val) >= correlation_report_threshold:
                        key = tuple(sorted([a, b]))
                        if key in seen:
                            continue
                        seen.add(key)
                        correlations.append(
                            {"a": a, "b": b, "pearson": round(float(val), 3)}
                        )
            # Strongest first.
            correlations.sort(key=lambda x: abs(x["pearson"]), reverse=True)
        except Exception:
            pass

    return DatasetProfile(
        row_count=row_count,
        column_count=len(columns),
        columns=columns,
        measures=measures,
        dimensions=dimensions,
        datetimes=datetimes,
        identifiers=identifiers,
        geos=geos,
        correlations=correlations,
    )


def _jsonable(v: Any) -> Any:
    """Convert numpy/pandas scalars to plain JSON-serializable values."""
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    return v
