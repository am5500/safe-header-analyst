# Dynamic Dashboard — AI Analytics SaaS

A config-driven, AI-augmented dashboard generator. Upload a CSV/XLSX and it
profiles the data, then dynamically builds KPIs, charts, and business
insights — adapting names and chart choices to what's actually in the
file, with no hardcoded business assumptions.

## Setup

```bash
pip install -r requirements.txt
export GROQ_API_KEY=your_key_here   # optional — see below
streamlit run app.py
```

Get a free Groq key at https://console.groq.com. **The app works fully
without one** — every feature has a rule-based fallback. The key only
unlocks nicer chart titles, polished insight wording, and smarter chat
answers.

Users can also paste a personal key into the in-app "AI Settings" panel
instead of using the server's environment variable — useful for shared
deployments where you don't want one key to be the only path to AI
features.

## Architecture

```
app.py              Streamlit orchestration: upload -> profile -> render
theme.py             CSS, i18n (en/ar), session-state bootstrap
dataset_profiler.py  Schema detection + semantic role heuristics
chart_engine.py      charts_config-driven rendering + rule-based selection
kpi_engine.py        KPI cards adapted to detected semantic roles
insight_engine.py    Executive summary / risks / opportunities / trends
ai_engine.py         The Groq API client (the only module that calls an LLM)
chat_engine.py       Conversational analyst, grounded in real df stats
render_engine.py     Data-quality UI (health, missing, duplicates, etc.)
utils.py             Shared formatting, Plotly theme, safe-execution helper
```

### The hybrid system

Every chart, KPI, and insight is computed by a deterministic rule engine
first. The AI layer (`ai_engine.py`) is then optionally allowed to:

- rename and reorder the rule engine's chart list (never invent new
  column pairings)
- rewrite insight sentences for tone -- rejected automatically if it
  changes any number in the sentence
- answer chat questions, grounded in a compact JSON summary of the
  dataset (never the raw dataframe)

If the AI call fails, times out, or returns malformed output, every
caller falls back to the rule-based result. The dashboard never depends
on AI to produce *something* -- confirmed by tests that mock failure,
garbage, and hallucinated responses.

## What changed vs. the original file

- **`call_groq` now exists.** It was referenced twice in the original
  file but never defined -- every AI feature was non-functional.
- **The hardcoded Groq API key was removed.** It's now read from
  `GROQ_API_KEY` via `os.getenv`, with an optional in-app field for a
  personal key. Rotate/revoke the old key if it was ever real.
- **Fabricated KPI trends were removed.** The original added a made-up
  per-card offset (`[0,0,2.1,-1.3,...]`) to fake different trend
  percentages per KPI. Trends are now computed per-metric from real
  month-over-month deltas, or omitted when there isn't enough data.
- **`titlefont` deprecated Plotly kwarg removed** in favor of
  `title=dict(text=..., font=dict(...))`.
- **`use_container_width` deprecated Streamlit kwarg removed** in favor
  of `width="stretch"`.
- **`infer_datetime_format=True`** (removed in pandas 2.0+, would raise)
  removed from date coercion.
- **A column-name matching bug was fixed**: naive substring checks
  caused `"country"` to match the `"count"` keyword and `"valid"` to
  match `"id"`. Replaced with token/camelCase-boundary matching.
- **AI insight rewrites can't alter facts.** A rewritten sentence is
  only accepted if it contains the exact same numbers as the original.
- **PNG chart export added** (via `kaleido`), plus the existing
  CSV/Excel/print-to-PDF export.
- **Large-file handling**: schema detection and KPIs operate on full
  groupby/sum aggregations (fast even at 1M+ rows -- see perf notes
  below); only point-heavy charts (scatter) are sampled, capped at a
  few thousand points; data loading and profiling are
  `@st.cache_data`-cached so filtering/tab-switching doesn't re-parse
  the file.

## Performance notes

Tested against a synthetic 600,000-row file: schema detection, profiling,
KPI generation, and rendering 7 charts complete in under 1.5 seconds
combined. A 1.2M-row scatter chart renders in ~0.15s after sampling to
5,000 points.

## Known limitation

Semantic role detection (e.g. distinguishing an ID column from a
numeric measure) relies on column-name keywords plus a cardinality
threshold. A low-cardinality ID-like column without "id"/"code"/etc. in
its name, or one with many duplicate values, may be classified as a
plain numeric measure instead. This affects which column a KPI or
insight is computed from in ambiguous cases -- it doesn't cause errors,
but double-check KPI source columns on unusual schemas.
