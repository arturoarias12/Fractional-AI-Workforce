"""Grade a finished research run from its operational-event ledger.

Usage
-----
Grade the snapshot the dashboard already exports::

    .venv/bin/python scripts/run_evaluation_harness.py

Grade a specific exported state, under the risk-approval reading of Success %::

    .venv/bin/python scripts/run_evaluation_harness.py \\
        --state dashboard/data/workflow_snapshot.json \\
        --success-metric risk_approval

Both readings of Success % are printed for every agent regardless of which one
``--success-metric`` selects, because that choice is still an open team ruling
and the report should not imply it has been settled.  See
``evaluation.harness`` for what each reading means and why it matters.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from evaluation import HarnessReport, SuccessMetric, grade_events  # noqa: E402


DEFAULT_STATE_PATH = REPO_ROOT / "dashboard" / "data" / "workflow_snapshot.json"


def load_events(path: Path) -> list[object]:
    """Read an event ledger from an exported snapshot or a raw graph state."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise SystemExit(f"{path} is not a workflow state or event ledger.")
    events = payload.get("operational_events")
    if events is None:
        raise SystemExit(
            f"{path} has no 'operational_events' key. Run a workflow first — "
            "an empty ledger means nothing emitted, not that grading failed."
        )
    return list(events)


def render(report: HarnessReport) -> str:
    summary = report.summary_metrics()
    lines = [
        "",
        f"Evaluation report · workflow {report.workflow_id or 'unknown'}",
        f"Success % reading in the 'success' column: {report.success_metric.value}",
        "",
        f"  rounds observed          : {summary['rounds_observed']}",
        f"  agents observed          : {summary['agents_observed']}",
        f"  total agent time         : {summary['research_completion_time']}",
        f"  total API cost           : {summary['total_api_cost']}",
        "",
        f"  {'agent':26s} {'success':>8s} {'exec':>6s} {'risk':>6s} "
        f"{'time':>10s} {'fail':>5s} {'retry':>6s} {'cost':>10s}",
        f"  {'-' * 26} {'-' * 8} {'-' * 6} {'-' * 6} {'-' * 10} {'-' * 5} "
        f"{'-' * 6} {'-' * 10}",
    ]
    for agent_id, metrics in report.dashboard_metrics().items():
        lines.append(
            f"  {agent_id:26s} {metrics['success_rate']:>8s} "
            f"{metrics['execution_success_rate']:>6s} "
            f"{metrics['risk_approval_rate']:>6s} "
            f"{metrics['task_completion_time']:>10s} "
            f"{str(metrics['failed_count']):>5s} "
            f"{str(metrics['retry_count']):>6s} "
            f"{metrics['api_cost']:>10s}"
        )
    lines.extend(
        [
            "",
            "  exec = share of tasks that ran without erroring.",
            "  risk = share of proposals Risk approved; N/A for agents that",
            "         propose nothing, and for a run that crashed before review.",
            "  Cost reads N/A until a real ModelClient reports tokens. That is a",
            "  missing measurement, not a free agent.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help="Exported workflow state or raw event ledger (JSON).",
    )
    parser.add_argument(
        "--success-metric",
        choices=[metric.value for metric in SuccessMetric],
        default=SuccessMetric.EXECUTION.value,
        help="Which reading fills the 'success' column (default: execution).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable metrics instead of the table.",
    )
    args = parser.parse_args()

    if not args.state.exists():
        raise SystemExit(f"No such state file: {args.state}")

    events = load_events(args.state)
    report = grade_events(
        events, success_metric=SuccessMetric(args.success_metric)
    )

    if args.json:
        print(
            json.dumps(
                {
                    "workflow_id": report.workflow_id,
                    "success_metric": report.success_metric.value,
                    "summary": report.summary_metrics(),
                    "agents": report.dashboard_metrics(),
                },
                indent=2,
            )
        )
    else:
        print(render(report))

    if not report.agents:
        print(
            "  No agent activity in this ledger. If a workflow did run, its "
            "nodes are not emitting operational events.\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
