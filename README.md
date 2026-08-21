# Fractional AI Workforce

Fractional AI Workforce is a multi-agent ETF research system. A Portfolio
Manager mandate is evaluated in parallel by Technical, Fundamental, and Quant
Traders; a Risk Agent reviews their strategy packages; a Reporting Agent
prepares the comparison; and the workflow pauses for a human Portfolio Manager
decision. Strategy evaluation uses the shared deterministic Backtest Engine.

The project is an educational research prototype. It does not execute live
trades, manage real capital, or provide investment advice.

## Requirements

- Python 3.11 or newer;
- the two team-supplied offline workbooks described below; and
- an OpenAI or Anthropic API key to run the real Technical Trader.

## Install

From the repository root, create a virtual environment and install the full
demo plus its test dependencies.

PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[full-demo,dev]"
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[full-demo,dev]'
```

## Configure the model

Copy `.env.example` to `.env`, then add your own key. The example selects
OpenAI. To use Anthropic, set `TECHNICAL_TRADER_MODEL_PROVIDER=anthropic`, set
`TECHNICAL_TRADER_MODEL` to a supported Claude model, and populate
`ANTHROPIC_API_KEY` instead. The Technical Trader code and workflow do not need
to change when the provider changes.

`.env` is ignored by Git. Never commit credentials.

The repository also contains an optional shared Gemini adapter used by a
manual Reporting Agent check. Install it with
`python -m pip install -e ".[gemini-models]"` and configure `GEMINI_API_KEY`
only when running that check; it is not required by the default full loop.

## Supply the offline data

The full-loop demo uses these team-provided files, which are intentionally not
versioned in this repository:

```text
ETF_historical_prices.xlsx
ETF_info.xlsx
```

Place them in the repository root, or set `ETF_HISTORICAL_PRICES_PATH` and
`ETF_INFO_PATH` in `.env`. Relative paths are resolved from the repository
root. The fixture is historical research data, not a live market feed.

## Verify and run

Check dependencies, data paths, and model configuration without making a paid
model call or displaying the API key:

```bash
python scripts/check_setup.py
```

Run the automated suite, also without making paid model calls:

```bash
python -m pytest -q
```

Start the full research loop:

```bash
python scripts/run_full_research_loop_demo.py
```

The graph runs one research round and pauses at a durable human Portfolio
Manager decision. The terminal prints the exact resume command and required
workflow ID. Resume that run rather than starting it again. To begin a separate
attempt after a checkpoint exists, set a fresh `FULL_TEST_WORKFLOW_ID` in
`.env`. If no Technical Trader provider is configured, the script labels that
branch as stubbed while still exercising the graph; an incomplete or invalid
provider configuration fails clearly instead of silently using the stub.

To use the dashboard, install its UI dependency and launch Streamlit:

```bash
python -m pip install -r dashboard/requirements.txt
streamlit run dashboard/app.py
```

More detailed component documentation is under `docs/` and
`src/agents/technical_trader/docs/`.
