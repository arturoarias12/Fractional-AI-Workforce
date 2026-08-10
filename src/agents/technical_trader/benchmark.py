"""Deterministic benchmark-selection policy owned by the Technical Trader."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Mapping

from protocols import BacktestResult

from .errors import ServiceContractError


@dataclass(frozen=True, slots=True)
class BenchmarkComparison:
    benchmark_symbol: str
    metric_name: str
    technical_value: float
    benchmark_value: float
    minimum_excess_return: float
    technical_outperformed: bool
    fallback_required: bool
    technical_metric_section: str
    benchmark_metric_section: str = "benchmark_metrics"
    benchmark_result_id: str | None = None
    comparison_basis: str = "shared_engine_benchmark_reference"

    def as_mapping(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BenchmarkSelectionPolicy:
    """Select the benchmark unless Technical strictly outperforms it.

    Total return is intentionally the prototype default because "beat the
    benchmark" is otherwise ambiguous. The policy is injectable so the team
    can later adopt a shared risk-adjusted or mandate-specific rule without
    changing the agent workflow.
    """

    metric_name: str = "total_return"
    minimum_excess_return: float = 0.0
    require_out_of_sample_metrics: bool = True

    def __post_init__(self) -> None:
        if not self.metric_name.strip():
            raise ValueError("metric_name must be non-empty")
        if (
            isinstance(self.minimum_excess_return, bool)
            or not isinstance(self.minimum_excess_return, (int, float))
            or not isfinite(float(self.minimum_excess_return))
            or self.minimum_excess_return < 0
        ):
            raise ValueError("minimum_excess_return must be finite and non-negative")

    def compare(
        self,
        *,
        result: BacktestResult,
        benchmark_symbol: str | None,
        executable_benchmark_result: BacktestResult | None = None,
    ) -> BenchmarkComparison:
        symbol = str(benchmark_symbol or "").strip()
        if not symbol:
            raise ServiceContractError(
                "Technical benchmark selection requires a benchmark symbol."
            )
        technical_section: Mapping[str, float | int | None]
        section_name: str
        if result.out_of_sample_metrics:
            technical_section = result.out_of_sample_metrics
            section_name = "out_of_sample_metrics"
        elif self.require_out_of_sample_metrics:
            raise ServiceContractError(
                "Technical benchmark selection requires out-of-sample metrics."
            )
        else:
            technical_section = result.metrics
            section_name = "metrics"

        technical_value = self._metric(
            technical_section,
            label=f"Technical {section_name}",
        )
        benchmark_result_id: str | None = None
        if executable_benchmark_result is not None:
            benchmark_section, benchmark_section_name = self._result_section(
                executable_benchmark_result,
                label="Executable benchmark",
            )
            benchmark_value = self._metric(
                benchmark_section,
                label=f"Executable benchmark {benchmark_section_name}",
            )
            benchmark_result_id = executable_benchmark_result.result_id
            comparison_basis = "executable_benchmark_backtest"
        else:
            benchmark_section_name = "benchmark_metrics"
            benchmark_value = self._metric(
                result.benchmark_metrics,
                label="benchmark_metrics",
            )
            comparison_basis = "shared_engine_benchmark_reference"
        outperformed = (
            technical_value
            > benchmark_value + float(self.minimum_excess_return)
        )
        return BenchmarkComparison(
            benchmark_symbol=symbol,
            metric_name=self.metric_name,
            technical_value=technical_value,
            benchmark_value=benchmark_value,
            minimum_excess_return=float(self.minimum_excess_return),
            technical_outperformed=outperformed,
            fallback_required=not outperformed,
            technical_metric_section=section_name,
            benchmark_metric_section=benchmark_section_name,
            benchmark_result_id=benchmark_result_id,
            comparison_basis=comparison_basis,
        )

    def _result_section(
        self,
        result: BacktestResult,
        *,
        label: str,
    ) -> tuple[Mapping[str, float | int | None], str]:
        if result.out_of_sample_metrics:
            return result.out_of_sample_metrics, "out_of_sample_metrics"
        if self.require_out_of_sample_metrics:
            raise ServiceContractError(
                f"{label} requires out-of-sample metrics."
            )
        return result.metrics, "metrics"

    def _metric(
        self,
        metrics: Mapping[str, float | int | None],
        *,
        label: str,
    ) -> float:
        value = metrics.get(self.metric_name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(float(value))
        ):
            raise ServiceContractError(
                f"{label} did not provide a finite '{self.metric_name}'."
            )
        return float(value)


__all__ = ["BenchmarkComparison", "BenchmarkSelectionPolicy"]
