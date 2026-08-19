#!/usr/bin/env python3
"""Full research-loop integration demo: PM -> 3 traders -> Risk -> Reporting -> PM -> Memory.

Runs the REAL compiled production graph (``graph.production.compile_production_workflow``)
with:

  * REAL Fundamental Trader  - agents.fundamental_trader (Aditi)
  * REAL Quant Trader        - agents.quant_trader (Shaurya) - no LLM required
  * REAL Risk Agent          - agents.risk_agent.RiskAgentImpl (Yutong)
  * REAL Reporting Agent     - agents.reporting_agent.ReportingAgentImpl (Emma)
  * STUBBED Technical Trader - see note below
  * SCRIPTED PM / Memory     - see note below

Why Technical Trader is stubbed here, not faked as "real"
------------------------------------------------------------
TechnicalTraderAgent.run() calls a real ``ModelClient.generate_structured(...)``
- there is currently no concrete ModelClient implementation anywhere in the
repo (verified: only the Protocol exists in
``agents/technical_trader/model_client.py``, and no test fake exists for it
either). Wiring a real one requires an actual LLM provider credential and
Arturo's own integration work; building a synthetic fake well enough to
faithfully exercise his ~400K-line staged pipeline is a separate, larger
task that isn't safe to improvise here. So this demo plugs in a clearly
labeled stub node for Technical Trader (same pattern the Risk agent's own
graph-integration test already uses for ALL THREE traders) - it returns a
realistic, schema-valid TraderStrategyPackage so the *topology* runs
end-to-end, without pretending Technical's actual LLM reasoning executed.

Everything downstream of the trader join (Risk, Reporting, PM decision,
Memory write) runs for real, against this mix of two real proposals + one
stub, exactly the same as it would against three real ones - the graph
doesn't know or care which trader nodes are real.

Why PM and Memory are scripted, not implemented
--------------------------------------------------
Portfolio Manager is deliberately the human's seat (see
``management/portfolio_manager.py`` - a Protocol for a future UI, not an
autonomous agent), and no persistence-backed Memory service exists yet.
Both are scripted stand-ins here purely so one round can complete without a
live human in the loop, matching the same pattern already established by
``tests/risk_agent/test_risk_agent_graph_integration.py``.

Run (offline, no network - uses the real 120-ticker ETF fixtures):

    python scripts/run_full_research_loop_demo.py
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

langgraph_missing = False
try:
    from graph.production import ProductionNodeSet, compile_production_workflow  # noqa: E402
    from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
except ImportError:
    langgraph_missing = True


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "full-loop-demo-run"
WORKFLOW_ID = "full-loop-demo-workflow"
TASK_ID = "full-loop-demo-task"


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
# Scripted PM / Memory nodes
# ---------------------------------------------------------------------------

def memory_read_node(state: Mapping[str, Any]) -> Mapping[str, Any]:
    del state
    return {
        "round_audit_summary_reference": "demo-audit-round-1",
        "round_history_reference": "demo-history-ref",
        "memory_context": None,
    }


def pm_intake_node(state: Mapping[str, Any]) -> Mapping[str, Any]:
    del state
    return {}


def pm_decision_node(state: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "pm_decision": PMDecision(
            decision_id=f"{state['workflow_id']}.decision-1",
            workflow_id=str(state["workflow_id"]),
            decision=PMDecisionType.REJECT,
            rationale="Demo run ends after one round (scripted PM, not a live human).",
        ).model_dump(mode="json"),
        "pending_human_action": None,
    }


def memory_write_node(state: Mapping[str, Any]) -> Mapping[str, Any]:
    del state
    return {"memory_record_id": "demo-memory-record-1"}


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

def _load_mandate(mandate_path: Path | None) -> PMMandate:
    """Load a dashboard-created mandate, or use the documented demo default."""

    if mandate_path is None:
        return PMMandate(
            workflow_id=WORKFLOW_ID,
            task_id=TASK_ID,
            as_of_date=OFFLINE_DATA_MAX_DATE,
            investment_objective=(
                "Full research-loop integration demo across the 120-ETF universe."
            ),
            permitted_asset_universe=list(PANEL),
        )

    payload = json.loads(mandate_path.read_text(encoding="utf-8"))
    raw_mandate = payload.get("pm_mandate", payload)
    mandate = PMMandate.model_validate(raw_mandate)
    if mandate.as_of_date > OFFLINE_DATA_MAX_DATE:
        raise ValueError(
            "The offline ETF fixture ends on "
            f"{OFFLINE_DATA_MAX_DATE.isoformat()}, but the PM mandate requested "
            f"{mandate.as_of_date.isoformat()}. Choose an available as-of date."
        )
    return mandate


async def main(mandate_path: Path | None = None) -> None:
    if langgraph_missing:
        print("langgraph is not installed - run: pip install -e '.[langgraph]'")
        return

    mandate = _load_mandate(mandate_path)

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

    # --- Stub Technical Trader (see docstring) ---
    def technical_trader_node(state: Mapping[str, Any]) -> dict[str, Any]:
        current_mandate = PMMandate.model_validate(state["pm_mandate"])
        package = _stub_technical_trader_package(
            current_mandate,
            int(state.get("round_number", 1)),
        )
        return {"technical_trader_package": package.model_dump(mode="json")}

    # --- Real Risk + Reporting ---
    risk_agent = RiskAgentImpl()
    reporting = RecordingReportingNode(ReportingAgentImpl())

    nodes = ProductionNodeSet(
        memory_read=memory_read_node,
        pm_intake=pm_intake_node,
        technical_trader=technical_trader_node,
        fundamental_trader=fundamental_trader_node,
        quant_trader=quant_trader_node,
        risk_review=make_risk_review_node(risk_agent),
        reporting=reporting,
        memory_write=memory_write_node,
        pm_decision=pm_decision_node,
    )
    compiled = compile_production_workflow(nodes, checkpointer=MemorySaver(), max_rounds=1)

    print("Running one full research-loop round...")
    print(f"  Real: Fundamental Trader, Quant Trader, Risk Agent, Reporting Agent")
    print(f"  Stubbed: Technical Trader (no ModelClient wired yet - see docstring)")
    print(f"  Scripted: PM intake/decision, Memory read/write")
    print()

    runner = WorkflowRunner(
        compiled_graph=compiled,
        snapshot_writer=write_dashboard_snapshot,
    )
    final_state = await runner.start_workflow(
        {"pm_mandate": mandate.model_dump(mode="json"), "run_id": mandate.workflow_id},
        publish_progress=True,
    )
    print("Dashboard snapshot written to dashboard/data/workflow_snapshot.json")

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
    print("=== PM decision ===")
    pm_decision = final_state.get("pm_decision")
    if pm_decision:
        print(f"decision: {pm_decision.get('decision')}, rationale: {pm_decision.get('rationale')}")

    print()
    print(f"memory_record_id: {final_state.get('memory_record_id')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the offline research loop with an optional PM mandate JSON file."
    )
    parser.add_argument(
        "--mandate-json",
        type=Path,
        help="Path to a PMMandate JSON file or a WorkflowInput JSON file.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.mandate_json))
