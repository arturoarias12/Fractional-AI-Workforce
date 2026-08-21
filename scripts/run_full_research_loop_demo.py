#!/usr/bin/env python3
"""Full research-loop integration demo: PM -> 3 traders -> Risk -> Reporting -> PM -> Memory.

Runs the REAL compiled production graph (``graph.production.compile_production_workflow``)
with:

  * REAL Fundamental Trader  - agents.fundamental_trader (Aditi)
  * REAL Quant Trader        - agents.quant_trader (Shaurya) - no LLM required
  * REAL/STUBBED Technical Trader - see note below
  * REAL Risk Agent          - agents.risk_agent.RiskAgentImpl (Yutong)
  * REAL Reporting Agent     - agents.reporting_agent.ReportingAgentImpl (Emma)
  * REAL PM decision         - a durable LangGraph interrupt, resumable via --resume
  * REAL Memory              - services.file_memory_store.FileBackedMemoryStore

Technical Trader: real when credentials are configured, stubbed otherwise
----------------------------------------------------------------------------
TechnicalTraderAgent.run() calls a real ``ModelClient.generate_structured(...)``.
A concrete OpenAI/Anthropic implementation now exists
(``agents.technical_trader.adapters``), gated behind environment variables -
see ``agents/technical_trader/docs/integration.md``. This script constructs
the real runtime whenever ``TECHNICAL_TRADER_MODEL_PROVIDER`` (and the
matching model + API key) are set; otherwise it falls back to a clearly
labeled stub node so the graph topology still runs end-to-end.

Verified in the environment this integration was written in: imports, model
client construction, engine/executor registration (``TECHNICAL_STRATEGY_EXECUTORS``),
and runtime construction all succeed; with a placeholder API key, the full
graph runs and Technical Trader settles as a real (non-stub) failed package
when the provider call itself is rejected, exactly as the contract expects -
no crash, no silently-swallowed error. A live smoke test with a real API key
was not possible without provider network access in that environment; that
is the one thing left for whoever runs this with real credentials.

Everything downstream of the trader join (Risk, Reporting, PM decision,
Memory write) runs for real regardless of which trader nodes are real vs
stubbed - the graph doesn't know or care.

Why PM decisions use a durable interrupt, and Memory persists to disk
--------------------------------------------------------------------------
Portfolio Manager is deliberately the human's seat (see
``management/portfolio_manager.py``). The graph's own
``human_pm_decision_node`` (not overridden here) pauses on a real LangGraph
interrupt and waits for ``--resume --decision-json ...``. Because the
dashboard launches each round as a fresh subprocess, both the paused
interrupt and recorded Memory need to survive a process exiting - hence
``AsyncSqliteSaver`` (checkpoints) and ``FileBackedMemoryStore`` (Memory),
both backed by files under ``dashboard/data/``, instead of the in-process
``MemorySaver``/``InMemoryMemoryStore`` this script used previously.

Run (offline, no network for data/backtesting - uses the real 120-ticker
ETF fixtures; Technical Trader's own model call, if configured, does use
the network):

    python scripts/run_full_research_loop_demo.py
    python scripts/run_full_research_loop_demo.py --resume --run-id <id> --decision-json <path>
"""

from __future__ import annotations

import asyncio
import argparse
import json
import pickle
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocols import (  # noqa: E402
    BacktestRequest,
    DataArtifact,
    DataCategory,
    DataProvenance,
    DataRequest,
    DataResponse,
    PMDecision,
    PMDecisionType,
    PMMandate,
    RunStatus,
    SpecialistId,
    TaskLineage,
    TraderStrategyPackage,
)
from tools import DeterministicBacktestEngine, PriceBar, ResolvedBacktestData  # noqa: E402

from agents.fundamental_trader import (  # noqa: E402
    FundamentalTraderRuntime,
    category_deviation_executor,
)
from agents.fundamental_trader.agent import FundamentalTraderAgent  # noqa: E402
from agents.fundamental_trader.examples.static_data_service import _load_etf_metadata  # noqa: E402
from agents.fundamental_trader.examples.validation_split import (  # noqa: E402
    PercentileValidationSplitPolicy,
)
from agents.quant_trader import (  # noqa: E402
    QuantTraderAgent,
    QuantTraderRuntime,
    cross_asset_spread_executor,
)
from agents.risk_agent import RiskAgentImpl, make_risk_review_node  # noqa: E402
from agents.reporting_agent import ReportingAgentImpl  # noqa: E402
from protocols.reporting import ReportingRequest  # noqa: E402
from dashboard.workflow_adapter import write_dashboard_snapshot  # noqa: E402
from integration import WorkflowRunner  # noqa: E402
from services.file_memory_store import FileBackedMemoryStore  # noqa: E402
from protocols.research_contracts import MemoryRecord  # noqa: E402

# Real Technical Trader is optional at import time: only constructed in main()
# if TECHNICAL_TRADER_MODEL_PROVIDER etc. are actually set (see
# _build_technical_trader_node below). Importing the package itself never
# reads credentials - see agents/technical_trader/docs/integration.md.
from agents.technical_trader import (  # noqa: E402
    ExecutionPolicy as TechnicalExecutionPolicy,
    TECHNICAL_STRATEGY_EXECUTORS,
    TechnicalModelConfigurationError,
    create_technical_model_client_from_env,
    create_technical_trader_runtime,
)

# A ticker present in the offline 120-ETF fixture, used as Technical Trader's
# PM-approved shared benchmark (see integration.md - required for its
# out-of-sample "must beat the benchmark" gate).
TECHNICAL_TRADER_BENCHMARK_SYMBOL = "IVV"

langgraph_missing = False
try:
    from graph.production import ProductionNodeSet, compile_production_workflow  # noqa: E402
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: E402
except ImportError:
    langgraph_missing = True


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "full-loop-demo-run"
WORKFLOW_ID = "full-loop-demo-workflow"
TASK_ID = "full-loop-demo-task"

# Both persist to disk (not in-process only) because the dashboard launches
# each round as a fresh subprocess: a paused PM-decision interrupt and any
# recorded Memory must survive that process exiting. See
# docs/fundamental_trader.md and this script's module docstring.
CHECKPOINT_DB_PATH = REPO_ROOT / "dashboard" / "data" / "workflow_checkpoints.sqlite"
MEMORY_STORE_DIR = REPO_ROOT / "dashboard" / "data" / "memory"


# ---------------------------------------------------------------------------
# Offline data fixtures (real 120-ticker ETF data, no network)
# ---------------------------------------------------------------------------

def _load_offline_panel() -> dict[str, tuple[PriceBar, ...]]:
    cache = Path("/tmp/price_panel.pkl")
    if cache.exists():
        with cache.open("rb") as f:
            return pickle.load(f)

    from openpyxl import load_workbook

    prices_path = REPO_ROOT / "ETF_historical_prices.xlsx"
    if not prices_path.exists():
        raise FileNotFoundError(
            f"{prices_path} not found - copy your ETF_historical_prices.xlsx "
            "into the repo root before running this demo."
        )
    wb = load_workbook(str(prices_path), read_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    idx = {h: i for i, h in enumerate(header)}
    panel: dict[str, list[PriceBar]] = {}
    for r in rows:
        ticker, dt, close = r[idx["ticker"]], r[idx["date"]], r[idx["close"]]
        if ticker is None or dt is None or close is None:
            continue
        panel.setdefault(ticker, []).append(PriceBar(
            symbol=ticker,
            timestamp=dt.replace(tzinfo=timezone.utc),
            open=r[idx["open"]] or close, high=r[idx["high"]] or close,
            low=r[idx["low"]] or close, close=close,
        ))
    return {k: tuple(v) for k, v in panel.items()}


PANEL = _load_offline_panel()
METADATA = _load_etf_metadata(REPO_ROOT / "ETF_info.xlsx")
OFFLINE_DATA_MAX_DATE = max(
    bar.timestamp.date() for bars in PANEL.values() for bar in bars
)


class OfflineDataService:
    """Serves PRICE_VOLUME + ETF_METADATA from the real fixtures - no network."""

    async def fetch(self, request: DataRequest) -> DataResponse:
        symbols = (
            request.asset_universe
            if isinstance(request.asset_universe, list) and request.asset_universe
            else list(PANEL)
        )
        now = datetime.now(timezone.utc)
        artifacts = []

        price_payload = {s: PANEL[s] for s in symbols if s in PANEL}
        if price_payload:
            artifacts.append(DataArtifact(
                artifact_id=f"{request.request_id}.prices",
                category=DataCategory.PRICE_VOLUME,
                description="Offline fixture prices (real ETF_historical_prices.xlsx)",
                data_reference="offline_fixture::prices",
                asset_scope=sorted(price_payload),
                provenance=[DataProvenance(
                    provenance_id=f"{request.request_id}.prices.prov", provider="offline_fixture",
                    source_reference="ETF_historical_prices.xlsx", retrieved_at=now,
                    point_in_time_verified=False,
                )],
                analysis_payload=price_payload,
            ))

        meta_payload = {
            s: {"category": METADATA[s]["category"], "fund_family": METADATA[s]["fund_family"],
                "issuer_tier": METADATA[s]["issuer_tier"]}
            for s in symbols if s in METADATA
        }
        if meta_payload:
            artifacts.append(DataArtifact(
                artifact_id=f"{request.request_id}.meta",
                category=DataCategory.ETF_METADATA,
                description="Offline fixture ETF metadata (real ETF_info.xlsx)",
                data_reference="offline_fixture::etf_metadata",
                asset_scope=sorted(meta_payload),
                provenance=[DataProvenance(
                    provenance_id=f"{request.request_id}.meta.prov", provider="offline_fixture",
                    source_reference="ETF_info.xlsx", retrieved_at=now,
                    point_in_time_verified=False,
                )],
                analysis_payload=meta_payload,
            ))

        return DataResponse(
            response_id=f"{request.request_id}.response", request_id=request.request_id,
            lineage=request.lineage, as_of_date=request.as_of_date,
            complete=True, artifacts=artifacts,
        )


class OfflineBacktestResolver:
    """Resolves backtest bars from the real fixture panel - no network.

    Handles both single-ticker candidates (Quant Trader: ticker_a/ticker_b)
    and Fundamental Trader's ticker + benchmark_tickers list - see
    docs/fundamental_trader.md for why the shared resolver alone isn't
    enough for the latter.
    """

    async def resolve(self, request: BacktestRequest) -> ResolvedBacktestData:
        params = request.candidate.parameters
        symbols: list[str] = []
        for key in ("ticker_a", "ticker_b", "symbol", "ticker"):
            value = params.get(key)
            if value:
                symbols.append(str(value))
        symbols.extend(str(s) for s in params.get("benchmark_tickers", []))
        bars = tuple(bar for s in dict.fromkeys(symbols) if s in PANEL for bar in PANEL[s])
        return ResolvedBacktestData(data_references=("offline_fixture",), bars=bars)


# ---------------------------------------------------------------------------
# Stub Technical Trader node (see module docstring for why)
# ---------------------------------------------------------------------------

def _stub_technical_trader_package(
    mandate: PMMandate,
    round_number: int,
) -> TraderStrategyPackage:
    """A realistic, schema-valid stand-in - NOT a real model call.

    Fills the graph's technical_trader slot so the full topology (3 trader
    branches -> join -> Risk -> Reporting -> PM) can be exercised end-to-end.
    Values are illustrative, not the output of Arturo's real staged pipeline.
    """
    from protocols import (
        CandidateRuleSpecification,
        ConstraintCheckStatus,
        MandateConstraintAssessment,
    )

    lineage = TaskLineage(
        workflow_id=mandate.workflow_id,
        task_id=f"{mandate.task_id}.round-{round_number}.technical.trader",
        parent_task_id=mandate.task_id,
        source_task_id=mandate.task_id,
        attempt=1,
    )
    candidate = CandidateRuleSpecification(
        strategy_name="[STUB] SMA crossover on QQQ",
        hypothesis="[STUB - not a real model call] Illustrative placeholder only.",
        rule_summary="[STUB] 20/50-day SMA crossover, long-only.",
        executor_id="technical_trader.stub_demo.v0",
        asset_eligibility_logic="[STUB]",
        signal_logic="[STUB]",
        position_logic="[STUB]",
        entry_logic="[STUB]",
        exit_logic="[STUB]",
        rebalancing_logic="[STUB]",
        parameters={"ticker": "QQQ", "short_window": 20, "long_window": 50},
        specialty_evidence_ids=["technical_trader.stub_demo"],
        specialty_evidence_usage={"technical_trader.stub_demo": "[STUB placeholder evidence]"},
        candidate_id=f"{lineage.task_id}.candidate",
        trader_id=SpecialistId.TECHNICAL_TRADER,
        lineage=lineage.child("candidate"),
    )
    return TraderStrategyPackage(
        package_id=f"{lineage.task_id}.package",
        candidate_id=candidate.candidate_id,
        trader_id=SpecialistId.TECHNICAL_TRADER,
        lineage=lineage,
        mandate_reference=mandate.reference(),
        status=RunStatus.FAILED,  # honestly not eligible - it's a stub, not a real result
        candidate_rule=candidate,
        constraint_assessment=MandateConstraintAssessment(
            status=ConstraintCheckStatus.NOT_EVALUATED,
            requires_risk_validation=False,
        ),
        failures=[{
            "stage": "technical_trader.stub_demo",
            "message": (
                "This demo run stubs Technical Trader because no ModelClient "
                "implementation exists yet in the repo. Not eligible for Risk "
                "review - see scripts/run_full_research_loop_demo.py."
            ),
            "retryable": False,
        }],
        eligible_for_risk_review=False,
    )


# ---------------------------------------------------------------------------
# PM intake (Memory read/write are now real - see main(); PM decision is
# no longer scripted here at all - omitting it from ProductionNodeSet makes
# the graph default to its own real human_pm_decision_node, a durable
# LangGraph interrupt. See this module's docstring for why that requires a
# persistent (SQLite) checkpointer instead of the in-process MemorySaver
# this script used previously.)
# ---------------------------------------------------------------------------

def pm_intake_node(state: Mapping[str, Any]) -> Mapping[str, Any]:
    del state
    return {}


class RecordingReportingNode:
    def __init__(self, reporting_agent: ReportingAgentImpl) -> None:
        self._agent = reporting_agent
        self.requests: list[ReportingRequest] = []

    async def __call__(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        request = ReportingRequest.model_validate(state.get("reporting_request"))
        self.requests.append(request)
        output = await self._agent.report(request)
        return {"reporting_output": output.model_dump(mode="json")}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _load_mandate_and_payload(mandate_path: Path | None) -> tuple[PMMandate, dict[str, Any]]:
    """Load a dashboard-created mandate, or use the documented demo default.

    Returns both the validated mandate and the raw payload dict, since the
    payload may also carry ``active_specialists`` (staffing) for this run -
    a sibling key to ``pm_mandate``, not part of the mandate itself.
    """

    if mandate_path is None:
        mandate = PMMandate(
            workflow_id=WORKFLOW_ID,
            task_id=TASK_ID,
            as_of_date=OFFLINE_DATA_MAX_DATE,
            investment_objective=(
                "Full research-loop integration demo across the 120-ETF universe."
            ),
            permitted_asset_universe=list(PANEL),
        )
        return mandate, {}

    payload = json.loads(mandate_path.read_text(encoding="utf-8"))
    raw_mandate = payload.get("pm_mandate", payload)
    mandate = PMMandate.model_validate(raw_mandate)
    if mandate.as_of_date > OFFLINE_DATA_MAX_DATE:
        raise ValueError(
            "The offline ETF fixture ends on "
            f"{OFFLINE_DATA_MAX_DATE.isoformat()}, but the PM mandate requested "
            f"{mandate.as_of_date.isoformat()}. Choose an available as-of date."
        )
    return mandate, payload


def _build_nodes(memory_store: FileBackedMemoryStore) -> "ProductionNodeSet":
    """Build the ProductionNodeSet shared by both start and resume paths."""

    async def memory_read_node(state: Mapping[str, Any]) -> dict[str, Any]:
        # memory_read runs first in the graph, before the "prepare" node
        # that derives a top-level "workflow_id" key from the mandate - so
        # fall back to the mandate itself, which is always present.
        workflow_id = str(state.get("workflow_id") or state["pm_mandate"]["workflow_id"])
        context = await memory_store.load_context(workflow_id)
        return {
            "memory_context": context.model_dump(mode="json"),
            "round_audit_summary_reference": f"{workflow_id}.round-{state.get('round_number', 1)}.audit",
            "round_history_reference": f"{workflow_id}.history",
        }

    async def memory_write_node(state: Mapping[str, Any]) -> dict[str, Any]:
        pm_decision = PMDecision.model_validate(state["pm_decision"])
        reporting_output = state.get("reporting_output") or {}
        risk_response = state.get("risk_review_response") or {}
        mandate_lessons = state.get("pm_mandate", {}).get("prior_round_lessons", [])
        pivot_lessons = (
            [str(lesson) for lesson in mandate_lessons]
            if isinstance(mandate_lessons, list)
            else []
        )
        lessons = list(dict.fromkeys(
            ([pm_decision.rationale] if pm_decision.rationale else [])
            + pivot_lessons
        ))
        record = MemoryRecord(
            record_id=f"{state['workflow_id']}.round-{state.get('round_number', 1)}.record",
            workflow_id=str(state.get("workflow_id") or state["pm_mandate"]["workflow_id"]),
            mandate_task_id=str(state["pm_mandate"]["task_id"]),
            result_references=list(reporting_output.get("surviving_candidate_ids") or []),
            critiques=[
                str(c) for c in (risk_response.get("critiques") or [])
            ] if isinstance(risk_response.get("critiques"), list) else [],
            pm_decision=pm_decision,
            lessons_for_future_rounds=lessons,
        )
        record_id = await memory_store.record(record)
        return {"memory_record_id": record_id}

    # --- Real Fundamental Trader ---
    fundamental_agent = FundamentalTraderAgent(
        data_service=OfflineDataService(),
        backtest_engine=DeterministicBacktestEngine(
            data_resolver=OfflineBacktestResolver(),
            strategy_executors=[category_deviation_executor],
        ),
        validation_split_policy=PercentileValidationSplitPolicy(train_fraction=0.9),
    )
    fundamental_runtime = FundamentalTraderRuntime(agent=fundamental_agent)

    async def fundamental_trader_node(state: Mapping[str, Any]) -> dict[str, Any]:
        current_mandate = PMMandate.model_validate(state["pm_mandate"])
        package = await fundamental_runtime.research(current_mandate, execution_context={
            "run_id": RUN_ID, "round_number": state.get("round_number", 1), "attempt": 1,
        })
        return {"fundamental_trader_package": package.model_dump(mode="json")}

    # --- Real Quant Trader (Shaurya's) ---
    quant_agent = QuantTraderAgent(
        data_service=OfflineDataService(),
        backtest_engine=DeterministicBacktestEngine(
            data_resolver=OfflineBacktestResolver(),
            strategy_executors=[cross_asset_spread_executor],
        ),
        validation_split_policy=PercentileValidationSplitPolicy(train_fraction=0.9),
    )
    quant_runtime = QuantTraderRuntime(agent=quant_agent)

    async def quant_trader_node(state: Mapping[str, Any]) -> dict[str, Any]:
        current_mandate = PMMandate.model_validate(state["pm_mandate"])
        package = await quant_runtime.research(current_mandate, execution_context={
            "run_id": RUN_ID, "round_number": state.get("round_number", 1), "attempt": 1,
        })
        return {"quant_trader_package": package.model_dump(mode="json")}

    # --- Technical Trader: real if credentials are configured, else stubbed ---
    # No API key was available to verify a live model call end-to-end in the
    # environment this integration was written in - see this module's
    # docstring. Everything up to the actual provider call (imports, model
    # client construction, engine/executor registration, runtime
    # construction) has been verified to wire together correctly; a live
    # smoke test with real credentials is the one thing left for whoever
    # runs this with a real TECHNICAL_TRADER_MODEL_PROVIDER / API key set.
    try:
        technical_execution_policy = TechnicalExecutionPolicy()
        technical_model_client = create_technical_model_client_from_env(
            execution_policy=technical_execution_policy,
        )
        technical_backtest_engine = DeterministicBacktestEngine(
            data_resolver=OfflineBacktestResolver(),
            strategy_executors=list(TECHNICAL_STRATEGY_EXECUTORS),
        )
        technical_runtime = create_technical_trader_runtime(
            model_client=technical_model_client,
            data_service=OfflineDataService(),
            backtest_engine=technical_backtest_engine,
            available_executors=[e.executor_id for e in TECHNICAL_STRATEGY_EXECUTORS],
            validation_split_policy=PercentileValidationSplitPolicy(train_fraction=0.9),
            benchmark_symbol=TECHNICAL_TRADER_BENCHMARK_SYMBOL,
            execution_policy=technical_execution_policy,
        )
        print(
            "Technical Trader: REAL - "
            f"{technical_model_client.__class__.__name__} configured from environment."
        )

        async def technical_trader_node(state: Mapping[str, Any]) -> dict[str, Any]:
            current_mandate = PMMandate.model_validate(state["pm_mandate"])
            package = await technical_runtime.research(current_mandate, execution_context={
                "run_id": RUN_ID, "round_number": state.get("round_number", 1), "attempt": 1,
            })
            return {"technical_trader_package": package.model_dump(mode="json")}

    except TechnicalModelConfigurationError as config_error:
        print(
            "Technical Trader: STUBBED - no model provider configured "
            f"({config_error}). Set TECHNICAL_TRADER_MODEL_PROVIDER, "
            "TECHNICAL_TRADER_MODEL, and the matching API key to use the "
            "real agent - see agents/technical_trader/docs/integration.md."
        )

        def technical_trader_node(state: Mapping[str, Any]) -> dict[str, Any]:
            current_mandate = PMMandate.model_validate(state["pm_mandate"])
            package = _stub_technical_trader_package(
                current_mandate,
                int(state.get("round_number", 1)),
            )
            return {"technical_trader_package": package.model_dump(mode="json")}

    # --- Real Risk + Reporting ---
    risk_agent = RiskAgentImpl()
    # Reporting can write a Gemini memo when the runner is launched in an
    # environment that has Emma's GEMINI_API_KEY.  The deterministic
    # comparison remains available without credentials, so classmates can
    # still run the complete offline loop locally.
    try:
        from services.gemini_model_client import GeminiModelClient

        reporting_agent = ReportingAgentImpl(model_client=GeminiModelClient())
        print("Reporting Agent: Gemini memo generation enabled.")
    except (ImportError, KeyError):
        reporting_agent = ReportingAgentImpl()
        print(
            "Reporting Agent: structured comparison only. Set GEMINI_API_KEY "
            "to enable the optional narrative memo."
        )
    reporting = RecordingReportingNode(reporting_agent)

    return ProductionNodeSet(
        memory_read=memory_read_node,
        pm_intake=pm_intake_node,
        technical_trader=technical_trader_node,
        fundamental_trader=fundamental_trader_node,
        quant_trader=quant_trader_node,
        risk_review=make_risk_review_node(risk_agent),
        reporting=reporting,
        memory_write=memory_write_node,
        # pm_decision intentionally omitted: the graph defaults to its own
        # real human_pm_decision_node (a durable LangGraph interrupt), which
        # is what makes an actual live PM decision - via the dashboard,
        # resumed by this script's --resume mode - possible instead of a
        # scripted stand-in.
    )


def _print_state_summary(final_state: Mapping[str, Any]) -> None:
    print("=== Trader packages ===")
    for key in ("technical_trader_package", "fundamental_trader_package", "quant_trader_package"):
        pkg = final_state.get(key)
        if pkg:
            print(f"{key}: status={pkg['status']} eligible_for_risk_review={pkg['eligible_for_risk_review']}")

    print()
    print("=== Risk review ===")
    risk_response = final_state.get("risk_review_response")
    if risk_response:
        print(f"approved candidates: {risk_response.get('approved_candidate_ids', risk_response)}")

    print()
    print("=== Reporting output ===")
    reporting_output = final_state.get("reporting_output")
    if reporting_output:
        print(f"surviving_candidate_ids: {reporting_output.get('surviving_candidate_ids')}")

    print()
    if final_state.get("pending_human_action"):
        print("=== Awaiting PM decision ===")
        print(
            "The graph paused at a durable interrupt for round "
            f"{final_state.get('round_number', 1)}. Resume with:\n"
            "  python scripts/run_full_research_loop_demo.py --resume "
            f"--run-id {final_state.get('workflow_id')} --decision-json <path>"
        )
        return

    print("=== PM decision ===")
    pm_decision = final_state.get("pm_decision")
    if pm_decision:
        print(f"decision: {pm_decision.get('decision')}, rationale: {pm_decision.get('rationale')}")

    print()
    print(f"memory_record_id: {final_state.get('memory_record_id')}")


async def main(
    mandate_path: Path | None = None,
    *,
    resume: bool = False,
    run_id: str | None = None,
    decision_path: Path | None = None,
) -> None:
    if langgraph_missing:
        print("langgraph is not installed - run: pip install -e '.[langgraph]'")
        return

    CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    memory_store = FileBackedMemoryStore(MEMORY_STORE_DIR)

    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB_PATH)) as checkpointer:
        nodes = _build_nodes(memory_store)
        # Keep the workflow aligned with Risk's three-round validation-touch
        # budget. The PM can request another round through round two; round
        # three requires a select or reject decision.
        compiled = compile_production_workflow(nodes, checkpointer=checkpointer, max_rounds=3)
        runner = WorkflowRunner(compiled_graph=compiled, snapshot_writer=write_dashboard_snapshot)

        if resume:
            if not run_id or not decision_path:
                print("--resume requires both --run-id and --decision-json")
                return
            decision_payload = json.loads(decision_path.read_text(encoding="utf-8"))
            pm_decision = decision_payload.get("pm_decision", decision_payload)
            state_update = decision_payload.get("state_update")
            print(f"Resuming workflow {run_id} with decision "
                  f"{pm_decision.get('decision')!r}...")
            final_state = await runner.resume_workflow(
                run_id, pm_decision, state_update=state_update,
            )
        else:
            mandate, payload = _load_mandate_and_payload(mandate_path)
            workflow_input: dict[str, Any] = {
                "pm_mandate": mandate.model_dump(mode="json"),
                "run_id": mandate.workflow_id,
            }
            if payload.get("active_specialists"):
                workflow_input["active_specialists"] = payload["active_specialists"]

            print("Running one research-loop round (or resuming to the next PM decision)...")
            print("  Real: Fundamental Trader, Quant Trader, Risk Agent, Reporting Agent, Memory")
            print("  Real (durable interrupt): PM decision")
            print()
            final_state = await runner.start_workflow(workflow_input, publish_progress=True)

        print("Dashboard snapshot written to dashboard/data/workflow_snapshot.json")
        _print_state_summary(final_state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run or resume the offline research loop, optionally driven by dashboard JSON files."
    )
    parser.add_argument(
        "--mandate-json",
        type=Path,
        help="Path to a PMMandate JSON file or a WorkflowInput JSON file (start mode only).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a paused PM-decision interrupt instead of starting a new run.",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        help="workflow_id of the run to resume (required with --resume).",
    )
    parser.add_argument(
        "--decision-json",
        type=Path,
        help=(
            "Path to a JSON file with {\"pm_decision\": {...}, "
            "\"state_update\": {...}} (required with --resume)."
        ),
    )
    args = parser.parse_args()
    asyncio.run(main(
        args.mandate_json,
        resume=args.resume,
        run_id=args.run_id,
        decision_path=args.decision_json,
    ))
