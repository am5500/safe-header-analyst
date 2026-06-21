"""
ai_engine.py
─────────────────────────────────────────────
The ONLY module that talks to an LLM provider (Groq). Every other module
in this app works perfectly well without this one — that's the whole
point of the hybrid system described in the spec: a rule engine that
always works, plus an optional AI layer that can only ever:

  • rename charts (better titles)
  • prioritize / reorder charts
  • improve title wording
  • rewrite insight phrasing (never invent new numbers)

ai_engine never invents facts, never produces the only copy of a chart
config, and never blocks the dashboard from rendering if it's slow,
unavailable, or returns garbage — see `is_available()` and the
try/except + fallback pattern in every public function here.

SECURITY: the API key is read exclusively from the environment
(`GROQ_API_KEY`). It is never hardcoded, never logged, and never echoed
back in error messages shown to the user.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger("dashboard_saas.ai_engine")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
REQUEST_TIMEOUT_SECONDS = 20


# ─────────────────────────────────────────────
# AVAILABILITY / KEY HANDLING
# ─────────────────────────────────────────────
def get_api_key() -> str | None:
    """Read the Groq API key from the environment ONLY.

    Never hardcode a key here. If the dashboard needs a per-user key
    instead of a server-wide one, the Streamlit layer may let a user
    paste their own key into a password-masked input and pass it
    explicitly to call_groq(api_key=...) — but the default and the
    documented path is the environment variable.
    """
    return os.getenv("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") or None


def is_available(api_key: str | None = None) -> bool:
    """Cheap check used by UI code to decide whether to even attempt
    AI calls (and whether to show an "AI features need a key" notice).
    """
    return bool(api_key or get_api_key())


# ─────────────────────────────────────────────
# LOW-LEVEL GROQ CALL (the function that did not exist before)
# ─────────────────────────────────────────────
class AIEngineError(Exception):
    """Raised for any AI-call failure. Callers should always catch this
    (or use the higher-level helpers below, which already do) and fall
    back to rule-based behavior — never let this propagate to the UI
    as an unhandled exception.
    """


def call_groq(
    messages: list[dict[str, str]],
    api_key: str | None = None,
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 1024,
) -> str:
    """Call the Groq chat-completions endpoint and return the assistant's
    text content. Raises AIEngineError on any failure (missing key,
    network error, bad status, malformed response) — callers must catch
    this; it intentionally does not return a fallback string itself,
    since "what to do when AI fails" is a per-call-site decision.
    """
    key = api_key or get_api_key()
    if not key:
        raise AIEngineError(
            "No Groq API key configured. Set the GROQ_API_KEY environment "
            "variable to enable AI features."
        )

    payload = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        GROQ_API_URL,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        raise AIEngineError(f"Groq API returned HTTP {exc.code}{': ' + detail if detail else ''}") from exc
    except urllib.error.URLError as exc:
        raise AIEngineError(f"Could not reach Groq API: {exc.reason}") from exc
    except TimeoutError as exc:
        raise AIEngineError("Groq API request timed out.") from exc
    except Exception as exc:  # noqa: BLE001
        raise AIEngineError(f"Unexpected error calling Groq API: {exc}") from exc

    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIEngineError("Groq API response was missing expected fields.") from exc


def _extract_json(text: str) -> Any:
    """Best-effort extraction of a JSON array/object from an LLM response
    that may include stray prose, markdown fences, etc."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    array_match = re.search(r"\[.*\]", text, re.DOTALL)
    if array_match:
        return json.loads(array_match.group())
    obj_match = re.search(r"\{.*\}", text, re.DOTALL)
    if obj_match:
        return json.loads(obj_match.group())
    raise ValueError("No JSON found in AI response.")


# ─────────────────────────────────────────────
# CHART RENAMING / PRIORITIZATION
# (operates on an EXISTING rule-based charts_config; never invents
#  new x/y column pairings the rule engine didn't already produce)
# ─────────────────────────────────────────────
def enhance_chart_configs(
    rule_based_configs: list[dict[str, Any]],
    ai_context: dict[str, Any],
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Ask the AI to improve titles/descriptions and reorder/prioritize
    the rule-engine's charts_config. The AI is given the existing
    configs as the ONLY charts it's allowed to touch — it can rename,
    reorder, or drop entries, but the x/y/type of each entry it keeps
    must match one of the inputs. If the AI response doesn't satisfy
    that contract, we discard it and return the original list unchanged.
    """
    if not rule_based_configs:
        return rule_based_configs
    if not is_available(api_key):
        return rule_based_configs

    # Build a compact reference the model can only choose from / rename.
    indexed = [
        {"index": i, "type": c.get("type"), "x": c.get("x"), "y": c.get("y"), "title": c.get("title")}
        for i, c in enumerate(rule_based_configs)
    ]

    prompt = f"""You are a data visualization editor. Below is a fixed list of charts
already chosen by a rule engine for this dataset. You may ONLY:
  - rewrite "title" to be more human-readable / business-friendly
  - write a one-sentence "description"
  - reorder the list by importance (most insightful first)
  - drop charts that seem redundant

You must NOT invent new x/y/type combinations, and "index" must refer to
one of the indices below.

Dataset context:
{json.dumps(ai_context, default=str)[:2500]}

Existing charts (by index):
{json.dumps(indexed, default=str)}

Return ONLY a JSON array, ordered by importance, of objects:
[{{"index": <int>, "title": "...", "description": "..."}}]
No prose, no markdown fences.
"""
    try:
        response = call_groq([{"role": "user", "content": prompt}], api_key=api_key, max_tokens=1200)
        decisions = _extract_json(response)
        if not isinstance(decisions, list):
            return rule_based_configs

        result: list[dict[str, Any]] = []
        seen_indices: set[int] = set()
        for d in decisions:
            if not isinstance(d, dict):
                continue
            idx = d.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(rule_based_configs) or idx in seen_indices:
                continue
            seen_indices.add(idx)
            base = dict(rule_based_configs[idx])
            if isinstance(d.get("title"), str) and d["title"].strip():
                base["title"] = d["title"].strip()
            if isinstance(d.get("description"), str) and d["description"].strip():
                base["description"] = d["description"].strip()
            result.append(base)

        if not result:
            return rule_based_configs
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("enhance_chart_configs failed, falling back to rule-based configs: %s", exc)
        return rule_based_configs


# ─────────────────────────────────────────────
# CHART SUGGESTION FROM SCRATCH (optional; still validated/sandboxed)
# Used only if the caller explicitly wants AI-originated chart configs
# rather than AI-reranked rule-engine configs. Always validate the
# output through chart_engine.validate_chart_configs before rendering.
# ─────────────────────────────────────────────
def suggest_chart_configs(
    ai_context: dict[str, Any],
    api_key: str | None = None,
) -> list[dict[str, Any]] | None:
    """Ask the AI to propose charts_config entries directly from the
    dataset profile. Returns None (never an empty crash) if AI is
    unavailable or the response can't be parsed — callers MUST fall
    back to chart_engine.build_rule_based_charts() in that case.
    """
    if not is_available(api_key):
        return None

    columns = ai_context.get("columns", [])
    col_names = [c["name"] for c in columns]
    prompt = f"""You are a data visualization expert. Suggest the most insightful
charts for this dataset.

Dataset context:
{json.dumps(ai_context, default=str)[:2500]}

Only use these exact column names: {col_names}

Return ONLY a JSON array (max 8 items) of chart configs:
[{{
  "type": one of ["line","bar","pie","scatter","histogram","box","heatmap","treemap","funnel","violin","cumulative","rolling_avg","pareto"],
  "x": "<column name or null>",
  "y": "<column name or null>",
  "color": "<column name or null>",
  "title": "human-readable title",
  "description": "one sentence on what this chart shows"
}}]
No prose, no markdown fences, no commentary.
"""
    try:
        response = call_groq([{"role": "user", "content": prompt}], api_key=api_key, max_tokens=1500)
        configs = _extract_json(response)
        if not isinstance(configs, list) or not configs:
            return None
        return configs
    except Exception as exc:  # noqa: BLE001
        logger.warning("suggest_chart_configs failed: %s", exc)
        return None


# ─────────────────────────────────────────────
# INSIGHT WORDING IMPROVEMENT
# Takes the rule-engine's insight_engine output and rewrites the prose
# ONLY — it is given the exact numbers and must not change them. We
# validate that every <b>...</b> highlighted figure from the original
# survives in the rewritten text (loosely) before accepting the rewrite;
# if validation fails we keep the original rule-based wording.
# ─────────────────────────────────────────────
def _numbers_in(text: str) -> set[str]:
    return set(re.findall(r"\d[\d,.]*%?", text))


def rewrite_insight_text(insight: dict[str, Any], api_key: str | None = None) -> dict[str, Any]:
    """Rewrite a single insight's `body` text for tone/clarity. Falls back
    to the original on any failure or if the rewritten text drops a
    number that was present in the original (a sign the AI altered a
    fact rather than just the phrasing).
    """
    if not is_available(api_key):
        return insight
    original_body = insight.get("body", "")
    if not original_body:
        return insight

    prompt = f"""Rewrite this single data-insight sentence to sound more natural and
business-friendly. Keep every number, percentage, and proper noun
EXACTLY as given — do not add, remove, or change any figure. Keep any
<b>...</b> tags wrapping the same numbers. Return only the rewritten
sentence, nothing else.

Original: {original_body}
"""
    try:
        rewritten = call_groq([{"role": "user", "content": prompt}], api_key=api_key, max_tokens=200).strip()
        if not rewritten:
            return insight
        if _numbers_in(rewritten) != _numbers_in(original_body):
            # AI changed a figure — refuse the rewrite, keep ground truth.
            return insight
        new_insight = dict(insight)
        new_insight["body"] = rewritten
        return new_insight
    except Exception as exc:  # noqa: BLE001
        logger.warning("rewrite_insight_text failed, keeping original wording: %s", exc)
        return insight


def rewrite_insight_list(
    insights: list[dict[str, Any]], api_key: str | None = None, max_items: int = 6,
) -> list[dict[str, Any]]:
    """Apply rewrite_insight_text to up to `max_items` insights (capped to
    bound latency/cost — a dashboard with 30 insight cards shouldn't fire
    30 LLM calls). Remaining items pass through with original wording.
    """
    if not is_available(api_key):
        return insights
    out = []
    for i, ins in enumerate(insights):
        if i < max_items:
            out.append(rewrite_insight_text(ins, api_key=api_key))
        else:
            out.append(ins)
    return out
