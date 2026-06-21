"""
dataset_profiler.py
─────────────────────────────────────────────
Understands an uploaded dataset:
  1. detect_schema()      → numeric / categorical / datetime / boolean / id columns
  2. detect_semantic_roles() → heuristic guesses at *meaning*
     (revenue, customer, product, region/country, date, ...)
  3. build_profile()      → a single DatasetProfile combining both,
     plus df.head(10), dtypes, missing %, shape — everything the
     rule engine and the AI layer need, and nothing more.
  4. DatasetProfile.to_ai_context() → a small, capped, JSON-safe dict
     suitable for sending to an LLM. NEVER the full dataframe.

This module has no Streamlit and no AI-provider dependency — it is
pure pandas, so it can be unit tested and reused by chart_engine,
kpi_engine, insight_engine, ai_engine, and chat_engine alike.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────
# CONSTANTS / HEURISTIC KEYWORD TABLES
# ─────────────────────────────────────────────
DATE_HINTS = {"date", "time", "year", "month", "day", "created", "updated", "period", "week", "quarter", "timestamp"}
ID_HINTS = {"id", "uuid", "code", "key", "index", "no", "num", "#", "serial", "ref"}
CAT_UNIQUE_LIMIT = 50

# Semantic role -> keywords used to scan column names.
SEMANTIC_ROLE_HINTS: dict[str, list[str]] = {
    "revenue": ["revenue", "sales", "turnover", "gmv"],
    "profit": ["profit", "margin", "net_income", "earnings"],
    "amount": ["amount", "total", "value", "price", "cost", "spend", "budget", "fee", "charge"],
    "quantity": ["qty", "quantity", "units", "count", "volume"],
    "customer": ["customer", "client", "buyer", "user_id", "account"],
    "product": ["product", "item", "sku", "model", "service"],
    "region": ["region", "territory", "zone", "area", "state", "province"],
    "country": ["country", "nation", "market"],
    "date": list(DATE_HINTS),
    "order": ["order", "transaction", "invoice", "deal"],
    "employee": ["employee", "staff", "headcount", "hire"],
    "category": ["category", "segment", "type", "class", "group"],
}

# Priority keywords used to pick the "primary measure" among numeric columns.
PRIMARY_MEASURE_PRIORITY = [
    "revenue", "sales", "amount", "value", "total", "profit", "cost", "price",
    "salary", "income", "spend", "budget", "score", "qty", "quantity",
]

TEMPLATE_HINTS: dict[str, list[str]] = {
    "Sales": ["revenue", "sales", "amount", "deal", "order", "price", "qty", "quantity", "units"],
    "Finance": ["profit", "loss", "cost", "budget", "expense", "income", "margin", "tax", "cash"],
    "HR": ["salary", "headcount", "tenure", "age", "hire", "attrition", "rating", "bonus", "leave"],
    "Marketing": ["clicks", "impressions", "ctr", "cpc", "spend", "leads", "conversions", "roas", "roi"],
    "Auto": [],
}


def _tokenize_column(col: str) -> set[str]:
    """Split a column name into lowercase tokens on separators and
    camelCase boundaries. 'Sales_Amount' / 'salesAmount' / 'sales amount'
    all yield {'sales', 'amount'}.
    """
    # insert a separator at camelCase boundaries before splitting
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", col)
    raw_tokens = re.split(r"[^A-Za-z0-9]+", spaced)
    return {tok.lower() for tok in raw_tokens if tok}


def _keyword_match(col: str, keywords: list[str]) -> bool:
    """Word/segment-boundary keyword match against a column name.

    Plain `kw in col.lower()` substring checks produce false positives
    like "count" matching inside "country", or "id" matching inside
    "valid". The column name is tokenized on separators and camelCase
    boundaries, and a keyword matches only if it equals a whole token.
    This naturally covers compound names like "sales_amount",
    "salesAmount", or "amount usd". We deliberately do NOT fall back to
    substring/prefix matching: short keywords like "count" or "id" are
    frequent prefixes of unrelated words ("country", "identifier"), so
    any non-token-exact fallback reintroduces the same false positives
    it's meant to avoid.
    """
    tokens = _tokenize_column(col)
    return any(kw in tokens for kw in keywords)


# ─────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────
@dataclass
class DatasetProfile:
    """Everything downstream engines need to know about the dataset."""

    schema: dict[str, list[str]]
    semantic_roles: dict[str, list[str]]
    shape: tuple[int, int]
    dtypes: dict[str, str]
    missing_pct_by_col: dict[str, float]
    head_sample: list[dict[str, Any]]
    primary_measure: str | None
    dataset_type: str  # "Time Series" | "Cross-sectional" | "Numeric Only" | "Unstructured"

    def to_ai_context(self, max_cols: int = 20) -> dict[str, Any]:
        """A compact, JSON-serializable summary safe to send to an LLM.

        Caps columns and rows so the prompt payload stays small and
        predictable regardless of how wide/long the source file is.
        Never includes the full dataframe.
        """
        cols = list(self.dtypes.keys())[:max_cols]
        return {
            "shape": {"rows": self.shape[0], "columns": self.shape[1]},
            "dataset_type": self.dataset_type,
            "columns": [
                {
                    "name": c,
                    "dtype": self.dtypes.get(c),
                    "missing_pct": self.missing_pct_by_col.get(c, 0.0),
                }
                for c in cols
            ],
            "schema": {k: v[:max_cols] for k, v in self.schema.items()},
            "semantic_roles": self.semantic_roles,
            "primary_measure": self.primary_measure,
            "sample_rows": self.head_sample[:10],
            "truncated_columns": max(0, len(self.dtypes) - max_cols),
        }


# ─────────────────────────────────────────────
# SCHEMA DETECTION
# ─────────────────────────────────────────────
def detect_schema(df: pd.DataFrame) -> dict[str, list[str]]:
    """Classify every column as date / numeric / categorical / id / boolean.

    Mutates `df` in place only to coerce numeric-looking string columns
    (e.g. "$1,200") into real numeric dtype — same behavior as the
    original app, preserved intentionally so downstream aggregations work.
    """
    schema: dict[str, list[str]] = {"date": [], "numeric": [], "categorical": [], "id": [], "boolean": []}

    for col in df.columns:
        series = df[col].dropna()
        if series.empty:
            continue

        if pd.api.types.is_datetime64_any_dtype(df[col]):
            schema["date"].append(col)
            continue
        if _keyword_match(str(col), list(DATE_HINTS)):
            try:
                pd.to_datetime(series.head(50), errors="raise")
                schema["date"].append(col)
                continue
            except Exception:
                pass

        if pd.api.types.is_numeric_dtype(df[col]):
            nuniq = series.nunique()
            if nuniq <= 2:
                schema["boolean"].append(col)
            elif _keyword_match(str(col), list(ID_HINTS)) and nuniq > 0.8 * len(series):
                schema["id"].append(col)
            else:
                schema["numeric"].append(col)
            continue

        # try coercing numeric-looking strings ("$1,200", "45%")
        cleaned = series.astype(str).str.replace(r"[,$€£¥%\s]", "", regex=True)
        try:
            pd.to_numeric(cleaned, errors="raise")
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(r"[,$€£¥%\s]", "", regex=True), errors="coerce"
            )
            schema["numeric"].append(col)
            continue
        except Exception:
            pass

        nuniq = series.nunique()
        if _keyword_match(str(col), list(ID_HINTS)) and nuniq > 0.5 * len(series):
            schema["id"].append(col)
        elif nuniq <= CAT_UNIQUE_LIMIT or nuniq / max(len(series), 1) < 0.15:
            schema["categorical"].append(col)
        else:
            schema["id"].append(col)

    return schema


def coerce_dates(df: pd.DataFrame, date_cols: list[str]) -> pd.DataFrame:
    """Coerce detected date columns to real datetime dtype, in place."""
    for col in date_cols:
        try:
            df[col] = pd.to_datetime(df[col], errors="coerce")
        except Exception:
            pass
    return df


# ─────────────────────────────────────────────
# SEMANTIC ROLE DETECTION (heuristics; AI may refine later)
# ─────────────────────────────────────────────
def detect_semantic_roles(df: pd.DataFrame, schema: dict[str, list[str]]) -> dict[str, list[str]]:
    """Heuristically map columns to business meaning.

    Returns e.g. {"revenue": ["Sales_USD"], "country": ["Country"], ...}.
    A column can appear under multiple roles if its name is ambiguous;
    callers should treat the first match as most likely.
    This is intentionally pure heuristics — fast, deterministic, and
    works even when the AI layer is unavailable. The AI layer (ai_engine)
    may later *reprioritize* these lists but never invents roles for
    columns that don't exist.
    """
    roles: dict[str, list[str]] = {role: [] for role in SEMANTIC_ROLE_HINTS}
    all_cols = schema["numeric"] + schema["categorical"] + schema["date"] + schema["id"] + schema["boolean"]

    for col in all_cols:
        for role, keywords in SEMANTIC_ROLE_HINTS.items():
            if _keyword_match(str(col), keywords):
                roles[role].append(col)

    return {role: cols for role, cols in roles.items() if cols}


def pick_primary_measure(df: pd.DataFrame, numeric_cols: list[str]) -> str | None:
    """Pick the single most business-relevant numeric column."""
    if not numeric_cols:
        return None
    for kw in PRIMARY_MEASURE_PRIORITY:
        for col in numeric_cols:
            if _keyword_match(str(col), [kw]):
                return col
    try:
        return max(numeric_cols, key=lambda c: df[c].sum())
    except Exception:
        return numeric_cols[0]


def pick_primary_with_template(df: pd.DataFrame, numeric_cols: list[str], template: str) -> str | None:
    """Same as pick_primary_measure but lets a chosen dashboard template
    (Sales/Finance/HR/Marketing) bias the keyword priority."""
    if not numeric_cols:
        return None
    hints = TEMPLATE_HINTS.get(template, [])
    for kw in hints:
        for col in numeric_cols:
            if _keyword_match(str(col), [kw]):
                return col
    return pick_primary_measure(df, numeric_cols)


# ─────────────────────────────────────────────
# COLUMN DESCRIPTION (human + AI readable)
# ─────────────────────────────────────────────
def describe_column(df: pd.DataFrame, col: str) -> str:
    series = df[col].dropna()
    if series.empty:
        return f"Column '{col}' is completely empty."
    dtype = str(series.dtype)
    n_missing = int(df[col].isna().sum())
    pct_missing = n_missing / max(len(df), 1) * 100
    desc = f"Column '{col}' (type: {dtype}): "
    if pd.api.types.is_numeric_dtype(series):
        desc += (
            f"numeric, {len(series):,} non-null values, missing {n_missing} ({pct_missing:.1f}%), "
            f"min={series.min():.2f}, max={series.max():.2f}, mean={series.mean():.2f}, "
            f"std={series.std():.2f}, median={series.median():.2f}, "
            f"25th percentile={series.quantile(0.25):.2f}, 75th percentile={series.quantile(0.75):.2f}."
        )
    elif pd.api.types.is_datetime64_any_dtype(series):
        desc += (
            f"datetime, from {series.min():%Y-%m-%d} to {series.max():%Y-%m-%d}, "
            f"spanning {(series.max() - series.min()).days} days, missing {n_missing} ({pct_missing:.1f}%)."
        )
    else:
        top5 = series.value_counts().head(5)
        top_str = ", ".join(f"'{k}' ({v} rows)" for k, v in top5.items())
        desc += (
            f"categorical, {series.nunique():,} unique values, missing {n_missing} ({pct_missing:.1f}%), "
            f"top categories: {top_str}."
        )
    return desc


# ─────────────────────────────────────────────
# PROFILE BUILDER (the main entrypoint)
# ─────────────────────────────────────────────
def build_profile(df: pd.DataFrame, schema: dict[str, list[str]] | None = None) -> DatasetProfile:
    """Build the full DatasetProfile used by every other engine.

    Uses df.head(10) (never head(3), never the full frame) plus
    column metadata — exactly the context the spec calls for.
    """
    if schema is None:
        schema = detect_schema(df)

    semantic_roles = detect_semantic_roles(df, schema)
    primary = pick_primary_measure(df, schema["numeric"])

    dtypes = {c: str(df[c].dtype) for c in df.columns}
    missing_pct = {c: round(float(df[c].isna().mean() * 100), 2) for c in df.columns}

    # head(10), JSON-safe (NaN -> None, Timestamps -> isoformat str)
    head_df = df.head(10).copy()
    for c in head_df.columns:
        if pd.api.types.is_datetime64_any_dtype(head_df[c]):
            head_df[c] = head_df[c].astype(str)
    head_sample = head_df.replace({np.nan: None}).to_dict(orient="records")

    if schema["date"]:
        dataset_type = "Time Series"
    elif schema["categorical"]:
        dataset_type = "Cross-sectional"
    elif schema["numeric"]:
        dataset_type = "Numeric Only"
    else:
        dataset_type = "Unstructured"

    return DatasetProfile(
        schema=schema,
        semantic_roles=semantic_roles,
        shape=(len(df), len(df.columns)),
        dtypes=dtypes,
        missing_pct_by_col=missing_pct,
        head_sample=head_sample,
        primary_measure=primary,
        dataset_type=dataset_type,
    )
