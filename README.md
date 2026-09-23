# MCP-Powered BI Ecosystem

A **generalist**, multi-agent business intelligence pipeline. Upload any
business dataset (CSV, Excel, JSON, TSV) and the system:

1. **Profiles** the data structurally — no assumptions about column
   names or use case.
2. **Computes** an adaptive set of KPIs (sums, means, period-over-period
   deltas, top-N shares, distinct counts).
3. **Designs and renders** an interactive Plotly dashboard with a
   balanced mix of trends, comparisons, distributions, and compositions.
4. **Writes a full BI report** as a self-contained HTML page (executive
   summary, methodology, KPI cards, schema table, findings,
   recommendations).

Everything is orchestrated by a **Model Context Protocol (MCP) server**
that exposes the underlying capabilities as discoverable, permissioned
tools, with seven specialist agents collaborating over those tools.

> Works on sales, logistics, HR, IoT, public-sector, finance — anything
> tabular. No hardcoded business logic.

---

## How it works

```
┌──────────────────────────────────────────────────────────────────────┐
│                          FastAPI Web UI                              │
│         (upload / live progress / dashboard / report)                │
└─────────────────────────────────┬────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         Pipeline runner                              │
│   runs each specialist agent in a fixed, well-tested sequence        │
└─────────────────────────────────┬────────────────────────────────────┘
                                  │
   ┌───────────────────────────┬──┴───┬───────────────────────────┐
   ▼                           ▼      ▼                           ▼
┌─────────────┐  ┌──────────────┐ ┌───────┐ ┌─────────────┐ ┌──────────┐
│ Ingestion   │  │ Data Prep    │ │ KPI   │ │ Dashboard   │ │ Reporter │
│ Orchestrator│  │              │ │       │ │ Publishing  │ │          │
└──────┬──────┘  └──────┬───────┘ └───┬───┘ └──────┬──────┘ └────┬─────┘
       │                │             │            │             │
       └────────────────┴─────────────┴────────────┴─────────────┘
                                  │
                                  ▼
                      ┌───────────────────────┐
                      │     MCP server        │
                      │  - load_dataset       │
                      │  - profile_dataset    │
                      │  - clean_dataset      │
                      │  - suggest_kpis       │
                      │  - compute_kpis       │
                      │  - suggest_charts     │
                      │  - build_chart        │
                      │  - build_dashboard    │
                      │  - publish_artifacts  │
                      │  - generate_report    │
                      │  - get/set_run_state  │
                      │  ↳ permission-gated   │
                      │    per agent role     │
                      └───────────┬───────────┘
                                  │
                                  ▼
                    ┌──────────────────────────┐
                    │   Artifact store         │
                    │   runs/<run_id>/         │
                    │     ├ dashboard.html     │
                    │     ├ report.html        │
                    │     └ state.json         │
                    └──────────────────────────┘
```

### Why deterministic engine + LLM agents?

A generalist BI tool can't be pure LLM ("look at this 50-column
dataset and decide what to do") — that hallucinates column names and
misses obvious aggregations. It also can't be pure rules — those
produce dull, formulaic reports.

This system splits the work:

- **Deterministic engine** ([src/core/](src/core/)) profiles every
  column into a role (measure / dimension / datetime / identifier /
  text / boolean) and generates a rich shortlist of candidate KPIs and
  chart specs from those roles alone.
- **LLM agents** curate, prioritize, and narrate that shortlist using
  business judgment: which KPIs actually matter for *this* dataset,
  which charts tell the clearest story, and what the findings mean.

Every numeric value in the final report comes from the engine, not the
LLM. The LLM never invents data.

### Agents and their permissions

Defined in [config.yaml](config.yaml). The MCP server enforces these as
deny-by-default allowlists per role.

| Agent          | Tools allowed                                                     |
| -------------- | ----------------------------------------------------------------- |
| Orchestrator   | `list_agents`, `get_run_state`, `set_run_state`                   |
| Ingestion      | `load_dataset`, `validate_dataset`                                |
| Data Prep      | `profile_dataset`, `clean_dataset`                                |
| KPI            | `profile_dataset`, `suggest_kpis`, `compute_kpis`                 |
| Dashboard      | `profile_dataset`, `suggest_charts`, `build_chart`                |
| Publishing     | `build_dashboard`, `publish_artifacts`                            |
| Reporter       | `get_run_state`, `generate_report`                                |

---

## Installation

Requires **Python 3.10+**.

```bash
# 1. Clone and enter
cd "MCP-Powered BI Ecosystem"

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env
# edit .env (see "Configuration" below)
```

---

## Configuration

Open `.env` and pick **one** LLM provider.

### Option A — Groq (recommended for speed)

```dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...               # from https://console.groq.com/keys
GROQ_MODEL=llama-3.3-70b-versatile # any tool-capable Groq model
```

### Option B — Ollama (fully local, no API key)

```bash
# Install Ollama from https://ollama.com/, then:
ollama pull llama3.1:8b
```

```dotenv
LLM_PROVIDER=ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b           # must support tool calling
```

Other knobs in `.env`:

| Variable             | Default                  | Meaning                                |
| -------------------- | ------------------------ | -------------------------------------- |
| `AGENT_MAX_STEPS`    | `12`                     | Safety bound on LLM tool-call rounds.  |
| `AGENT_TEMPERATURE`  | `0.2`                    | Lower = more deterministic agents.     |
| `MAX_KPIS`           | `12`                     | Max KPIs the KPI agent will keep.      |
| `MAX_CHARTS`         | `10`                     | Max charts on the dashboard.           |
| `ARTIFACT_ROOT`      | `./runs`                 | Where per-run output folders go.       |

Adaptive engine thresholds (column role inference) live in
[config.yaml](config.yaml) under `engine:`. Tune those if your data
domain has, say, lots of low-cardinality categoricals.

---

## Running it

### Quickest path: end-to-end demo

```bash
./scripts/run_demo.sh
```

This:

1. Generates a 4 000-row synthetic sales CSV at `data/sample_sales.csv`
   (mixed types — datetime strings, identifiers, measures, a boolean,
   free-text notes, some missing values and duplicates so the pipeline
   has real work to do).
2. Runs the pipeline against it from the command line.
3. Prints the run id and the paths to `dashboard.html` and
   `report.html` inside `runs/<run_id>/`.

### Interactive web UI

```bash
uvicorn src.ui.app:app --reload
```

Open <http://127.0.0.1:8000/>:

- Upload any CSV / Excel / JSON file.
- Watch each agent's stage update live.
- When the run finishes, click **Open dashboard →** or **Open BI report →**.

### Pipeline only, on your own dataset

```bash
python -m src.pipeline /path/to/your_data.csv
```

### Expose the MCP server over stdio

The same tool registry can be driven by any MCP client (Claude Desktop,
the `mcp` CLI, custom code). Each tool is namespaced by role
(e.g. `kpi__compute_kpis`) so clients can see exactly which agent owns
each capability.

```bash
python -m src.mcp_server.server
```

Then point your MCP client at the resulting stdio process.

---

## Project layout

```
.
├── README.md
├── requirements.txt
├── .env.example
├── config.yaml                # agent permissions + engine thresholds
├── data/                      # input datasets (sample lives here)
├── runs/                      # per-run artifact directories
├── scripts/
│   ├── generate_sample_data.py
│   └── run_demo.sh
├── src/
│   ├── core/                  # deterministic adaptive engine
│   │   ├── profiler.py
│   │   ├── kpi_engine.py
│   │   └── dashboard_builder.py
│   ├── llm/                   # provider-agnostic LLM client
│   │   └── client.py
│   ├── mcp_server/            # tool registry + MCP server
│   │   ├── tools.py
│   │   └── server.py
│   ├── agents/                # seven specialist agents
│   │   ├── base.py
│   │   ├── orchestrator.py
│   │   ├── ingestion.py
│   │   ├── data_prep.py
│   │   ├── kpi.py
│   │   ├── dashboard.py
│   │   ├── publishing.py
│   │   └── reporter.py
│   ├── ui/                    # FastAPI app + templates + static
│   │   ├── app.py
│   │   ├── render.py          # final BI report HTML
│   │   ├── templates/
│   │   └── static/
│   └── pipeline.py            # end-to-end runner
└── tests/
    └── test_engine.py         # smoke tests (LLM-free)
```

---

## Per-run artifacts

Each run creates `runs/<run_id>/` containing:

| File             | Description                                                                           |
| ---------------- | ------------------------------------------------------------------------------------- |
| `dashboard.html` | Self-contained interactive HTML dashboard (Plotly, no build step).                    |
| `report.html`    | Styled BI report (executive summary, schema, KPIs, findings, recommendations).        |
| `state.json`     | Full snapshot of the run (profile, KPI specs + values, chart specs, agent transcript).|

These are everything you need to share the analysis — no environment
required to view them.

---

## Testing

```bash
pip install pytest
pytest -q
```

The default test suite is LLM-free: it validates the profiler, KPI
engine, chart builder, dashboard HTML assembly, and the MCP server's
permission enforcement.

---

## Adapting the system

- **Change the agent permission matrix:** edit `agents:` in
  [config.yaml](config.yaml). Adds and removes take effect on the next
  pipeline run; the registry verifies them on every call.
- **Add a new tool:** register it in
  [src/mcp_server/tools.py](src/mcp_server/tools.py) and grant it to
  the agent(s) that should call it.
- **Change which roles a column gets assigned:** tune the thresholds in
  the `engine:` section of `config.yaml`. The profiler rereads these on
  every run.
- **Add a new chart kind:** extend `_build_figure` in
  [src/core/dashboard_builder.py](src/core/dashboard_builder.py) and
  emit specs of that kind from `suggest_charts`.
- **Swap the LLM provider:** drop a new subclass of `LLMClient` into
  [src/llm/client.py](src/llm/client.py) and wire it into
  `get_llm_client`.

---

## Troubleshooting

| Symptom                                                                 | Fix                                                                                                                |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `GROQ_API_KEY is not set`                                               | Put a real key in `.env`, or switch `LLM_PROVIDER=ollama`.                                                         |
| `Tool 'X' is not permitted for role 'Y'`                                | Expected — the MCP server is enforcing config.yaml. Add `X` to that role's allowlist if intentional.               |
| Ollama: model "doesn't support tools"                                   | Pull a tool-capable model: `ollama pull llama3.1:8b` (or `qwen2.5:7b`, `mistral-nemo`).                            |
| Dashboard renders but is missing a chart                                | Check the run's `state.json` — failed chart specs are recorded with their error. Often a column type mismatch.     |
| Agent step budget exhausted                                             | Raise `AGENT_MAX_STEPS` in `.env`, or simplify the agent prompt. The profile may also be unusually large.          |

---

## License

MIT.
