from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import BaseModel, ValidationError
from protocols import (
    BacktestPlanDraft,
    BacktestInterpretationDraft,
    CandidateProposalDraft,
    DataResponse,
    PMMandate,
    ResearchExecutionContext,
    SpecialistId,
    TaskLineage,
    TraderTask,
    TraderResearchPlanDraft,
    ValidationSplit,
)

from agents.technical_trader import (
    AgentOutputValidationError,
    AnthropicTechnicalModelClient,
    ExecutionPolicy,
    MULTI_ASSET_PORTFOLIO_EXECUTOR_ID,
    ModelRequestContext,
    OpenAITechnicalModelClient,
    OpportunityCandidateProposalDraft,
    OpportunitySleeveParametersDraft,
    StructuredOutputValidationError,
    JsonFileTechnicalDiagnosticsSink,
    TechnicalCandidateDiagnostic,
    StagedTraderAgent,
    TechnicalTraderAgent,
    TechnicalModelConfigurationError,
    compact_horizon_technical_report,
    create_technical_model_client_from_env,
    create_technical_trader_runtime,
)
from agents.technical_trader.prompts import (
    CandidatePromptScope,
    OpportunityBinding,
    build_opportunity_prompt_report,
    redact_opportunity_references,
    TECHNICAL_TRADER_SYSTEM_PROMPT,
)
from agents.technical_trader.adapters._common import (
    strict_response_schema,
    validate_json_output,
)
from agents.technical_trader.executors import (
    MULTI_ASSET_PORTFOLIO_EXECUTOR_ID as CATALOG_PORTFOLIO_EXECUTOR_ID,
    TECHNICAL_EXECUTOR_SPEC_BY_ID,
    render_executor_catalog,
    validate_technical_portfolio_parameters,
)
from scripts.full_test_identity import derive_demo_identifiers
from scripts.horizon_matched_validation import (
    HorizonMatchedValidationSplitPolicy,
)


class SampleOutput(BaseModel):
    answer: int


class FakeOpenAIResponses:
    def __init__(self, *, status: str = "completed") -> None:
        self.status = status
        self.request = None

    async def create(self, **request):
        self.request = request
        return SimpleNamespace(
            id="resp-openai-test",
            model="openai-test-model",
            status=self.status,
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
            output_text='{"answer": 7}',
            usage=SimpleNamespace(
                input_tokens=11,
                output_tokens=4,
                total_tokens=15,
                input_tokens_details=SimpleNamespace(cached_tokens=2),
                output_tokens_details=SimpleNamespace(reasoning_tokens=1),
            ),
        )


class FakeAnthropicMessages:
    def __init__(self, *, stop_reason: str = "end_turn") -> None:
        self.stop_reason = stop_reason
        self.request = None

    async def create(self, **request):
        self.request = request
        return SimpleNamespace(
            id="msg-anthropic-test",
            model="anthropic-test-model",
            stop_reason=self.stop_reason,
            service_tier="standard",
            content=[SimpleNamespace(type="text", text='{"answer": 9}')],
            usage=SimpleNamespace(
                input_tokens=13,
                cache_creation_input_tokens=3,
                cache_read_input_tokens=2,
                output_tokens=5,
            ),
        )


def _context() -> ModelRequestContext:
    return ModelRequestContext(
        agent_id="technical_trader_agent",
        operation="adapter_contract_check",
        workflow_id="workflow-test",
        task_id="task-test",
        model_call_id="call-test",
        attempt=2,
    )


def test_openai_adapter_validates_output_and_normalizes_usage() -> None:
    responses = FakeOpenAIResponses()
    client = OpenAITechnicalModelClient(
        api_key="not-a-real-key",
        model="openai-test-model",
        client=SimpleNamespace(responses=responses),
    )

    result = asyncio.run(
        client.generate_structured(
            system_prompt="system",
            user_prompt="user",
            response_model=SampleOutput,
            context=_context(),
        )
    )

    assert isinstance(result.output, SampleOutput)
    assert result.output.answer == 7
    assert result.usage.provider == "openai"
    assert result.usage.total_tokens == 15
    submitted_request = responses.request
    assert submitted_request is not None
    assert submitted_request["text"]["format"]["type"] == "json_schema"
    assert submitted_request["text"]["format"]["strict"] is True
    assert (
        submitted_request["text"]["format"]["schema"][
            "additionalProperties"
        ]
        is False
    )
    assert submitted_request["store"] is False
    assert "not-a-real-key" not in repr(submitted_request)


def test_anthropic_adapter_validates_output_and_normalizes_cache_usage() -> None:
    messages = FakeAnthropicMessages()
    transformed_schemas: list[dict[str, Any]] = []

    def transform_schema(schema):
        transformed = {**schema, "description": "transformed-for-test"}
        transformed_schemas.append(transformed)
        return transformed

    client = AnthropicTechnicalModelClient(
        api_key="not-a-real-key",
        model="anthropic-test-model",
        client=SimpleNamespace(messages=messages),
        schema_transform=transform_schema,
    )

    result = asyncio.run(
        client.generate_structured(
            system_prompt="system",
            user_prompt="user",
            response_model=SampleOutput,
            context=_context(),
        )
    )

    assert isinstance(result.output, SampleOutput)
    assert result.output.answer == 9
    assert result.usage.provider == "anthropic"
    assert result.usage.input_tokens == 18
    assert result.usage.total_tokens == 23
    submitted_request = messages.request
    assert submitted_request is not None
    assert (
        submitted_request["output_config"]["format"]["type"]
        == "json_schema"
    )
    submitted_schema = submitted_request["output_config"]["format"]["schema"]
    assert submitted_schema == transformed_schemas[0]
    assert submitted_schema["description"] == "transformed-for-test"
    assert "not-a-real-key" not in repr(messages.request)


def test_anthropic_sdk_transforms_all_real_technical_response_schemas() -> None:
    anthropic = pytest.importorskip("anthropic")

    for response_model in (
        TraderResearchPlanDraft,
        OpportunityCandidateProposalDraft,
        BacktestInterpretationDraft,
    ):
        original = response_model.model_json_schema(mode="validation")
        transformed = anthropic.transform_schema(original)
        assert isinstance(transformed, dict)
        assert transformed
        assert transformed != original


def test_all_openai_technical_response_schemas_are_closed_and_strict() -> None:
    def assert_closed(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                assert_closed(child)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") == "object" or "properties" in node:
            assert node.get("additionalProperties") is False
            assert set(node.get("required", ())) == set(
                node.get("properties", {})
            )
        for child in node.values():
            assert_closed(child)

    for response_model in (
        TraderResearchPlanDraft,
        OpportunityCandidateProposalDraft,
        BacktestInterpretationDraft,
    ):
        assert_closed(strict_response_schema(response_model))


def test_validation_error_preserves_the_parsed_provider_payload() -> None:
    raw = '{"answer": "not-an-integer", "unexpected": true}'
    with pytest.raises(StructuredOutputValidationError) as raised:
        validate_json_output(raw, SampleOutput, provider="test-provider")

    assert raised.value.raw_payload == {
        "answer": "not-an-integer",
        "unexpected": True,
    }


@pytest.mark.parametrize(
    ("provider", "api_key_name", "expected_type", "fake_client"),
    [
        (
            "openai",
            "OPENAI_API_KEY",
            OpenAITechnicalModelClient,
            SimpleNamespace(responses=FakeOpenAIResponses()),
        ),
        (
            "anthropic",
            "ANTHROPIC_API_KEY",
            AnthropicTechnicalModelClient,
            SimpleNamespace(messages=FakeAnthropicMessages()),
        ),
    ],
)
def test_environment_factory_selects_provider(
    provider,
    api_key_name,
    expected_type,
    fake_client,
) -> None:
    selected = create_technical_model_client_from_env(
        execution_policy=ExecutionPolicy(),
        environ={
            "TECHNICAL_TRADER_MODEL_PROVIDER": provider,
            "TECHNICAL_TRADER_MODEL": f"{provider}-test-model",
            api_key_name: "not-a-real-key",
            **(
                {
                    "TECHNICAL_TRADER_ANTHROPIC_NATIVE_STRUCTURED_OUTPUTS": (
                        "false"
                    )
                }
                if provider == "anthropic"
                else {}
            ),
        },
        client=fake_client,
    )

    assert isinstance(selected, expected_type)


def test_environment_factory_fails_closed_without_selected_api_key() -> None:
    with pytest.raises(
        TechnicalModelConfigurationError,
        match="OPENAI_API_KEY",
    ):
        create_technical_model_client_from_env(
            execution_policy=ExecutionPolicy(),
            environ={
                "TECHNICAL_TRADER_MODEL_PROVIDER": "openai",
                "TECHNICAL_TRADER_MODEL": "openai-test-model",
            },
            client=SimpleNamespace(responses=FakeOpenAIResponses()),
        )


def test_provider_incomplete_responses_fail_before_local_validation() -> None:
    openai_client = OpenAITechnicalModelClient(
        api_key="not-a-real-key",
        model="openai-test-model",
        client=SimpleNamespace(
            responses=FakeOpenAIResponses(status="incomplete")
        ),
    )
    with pytest.raises(RuntimeError, match="status was incomplete"):
        asyncio.run(
            openai_client.generate_structured(
                system_prompt="system",
                user_prompt="user",
                response_model=SampleOutput,
                context=_context(),
            )
        )

    anthropic_client = AnthropicTechnicalModelClient(
        api_key="not-a-real-key",
        model="anthropic-test-model",
        client=SimpleNamespace(
            messages=FakeAnthropicMessages(stop_reason="max_tokens")
        ),
        schema_transform=lambda schema: schema,
    )
    with pytest.raises(RuntimeError, match="stop_reason=max_tokens"):
        asyncio.run(
            anthropic_client.generate_structured(
                system_prompt="system",
                user_prompt="user",
                response_model=SampleOutput,
                context=_context(),
            )
        )


def test_full_universe_prompt_is_bounded_without_mutating_full_report() -> None:
    assets = []
    opportunities = []
    for index in range(25):
        symbol = f"ETF{index:02d}"
        evidence_id = f"ma-{symbol}"
        assets.append(
            {
                "symbol": symbol,
                "support_resistance_levels": [],
                "chart_patterns": [],
                "moving_averages": [
                    {"moving_average_id": evidence_id},
                    {"moving_average_id": f"unused-{symbol}"},
                ],
                "moving_average": {"moving_average_id": evidence_id},
                "volume_observation": None,
            }
        )
        opportunities.append(
            {
                "opportunity_id": f"opportunity-{symbol}",
                "rank": index + 1,
                "symbol": symbol,
                "executor_id": "technical.horizon_adaptive_trend.v1",
                "evidence_ids": [evidence_id],
                "score": 1 - index / 100,
            }
        )
    full_report = {
        "assets": assets,
        "horizon_opportunities": opportunities,
    }

    compact = compact_horizon_technical_report(full_report)

    assert len(compact["assets"]) == 20
    assert len(compact["horizon_opportunities"]) == 20
    assert compact["assets"][0]["symbol"] == "ETF00"
    assert len(compact["assets"][0]["moving_averages"]) == 1
    assert len(full_report["assets"]) == 25
    assert compact["prompt_screening_summary"]["source_asset_count"] == 25


def test_factory_rejects_openai_output_mode_typo_consistently() -> None:
    with pytest.raises(
        TechnicalModelConfigurationError,
        match="TECHNICAL_TRADER_OPENAI_OUTPUT_MODE",
    ):
        create_technical_model_client_from_env(
            execution_policy=ExecutionPolicy(),
            environ={
                "TECHNICAL_TRADER_MODEL_PROVIDER": "openai",
                "TECHNICAL_TRADER_MODEL": "openai-test-model",
                "OPENAI_API_KEY": "not-a-real-key",
                "TECHNICAL_TRADER_OPENAI_OUTPUT_MODE": "json-scehma",
            },
            client=SimpleNamespace(responses=FakeOpenAIResponses()),
        )


def test_factory_rejects_retry_budget_that_exceeds_agent_deadline() -> None:
    with pytest.raises(
        TechnicalModelConfigurationError,
        match="provider timeout/retry budget",
    ):
        create_technical_model_client_from_env(
            execution_policy=ExecutionPolicy(),
            environ={
                "TECHNICAL_TRADER_MODEL_PROVIDER": "openai",
                "TECHNICAL_TRADER_MODEL": "openai-test-model",
                "OPENAI_API_KEY": "not-a-real-key",
                "TECHNICAL_TRADER_PROVIDER_TIMEOUT_SECONDS": "50",
                "TECHNICAL_TRADER_PROVIDER_MAX_RETRIES": "1",
            },
            client=SimpleNamespace(responses=FakeOpenAIResponses()),
        )


def test_factory_uses_the_actual_custom_execution_policy_deadline() -> None:
    policy = ExecutionPolicy(model_call_timeout_seconds=20)
    with pytest.raises(
        TechnicalModelConfigurationError,
        match="provider timeout/retry budget",
    ):
        create_technical_model_client_from_env(
            execution_policy=policy,
            environ={
                "TECHNICAL_TRADER_MODEL_PROVIDER": "openai",
                "TECHNICAL_TRADER_MODEL": "openai-test-model",
                "OPENAI_API_KEY": "not-a-real-key",
            },
            client=SimpleNamespace(responses=FakeOpenAIResponses()),
        )


def _candidate_proposal(
    *,
    symbol: str,
    evidence_id: str,
    child_executor_id: str,
) -> CandidateProposalDraft:
    return CandidateProposalDraft.model_validate(
        {
            "rule": {
                "strategy_name": "Scope validation test",
                "hypothesis": "The submitted technical evidence is actionable.",
                "rule_summary": "Run one evidence-bound sleeve.",
                "executor_id": MULTI_ASSET_PORTFOLIO_EXECUTOR_ID,
                "asset_eligibility_logic": "Use the submitted shortlist.",
                "signal_logic": "Use the cited deterministic observation.",
                "position_logic": "Use one long sleeve.",
                "entry_logic": "Enter on the registered signal.",
                "exit_logic": "Exit under registered risk rules.",
                "rebalancing_logic": "Review on the registered cadence.",
                "parameters": {
                    "sleeves": [
                        {
                            "symbol": symbol,
                            "executor_id": child_executor_id,
                            "evidence_ids": [evidence_id],
                        }
                    ]
                },
                "specialty_evidence_ids": [evidence_id],
                "specialty_evidence_usage": {
                    evidence_id: "Defines the sleeve signal."
                },
            },
            "backtest_plan": {"frequency": "daily"},
        }
    )


def test_candidate_scope_rejects_unsubmitted_symbols_and_evidence() -> None:
    full_report = {
        "assets": [
            {
                "symbol": "AAA",
                "support_resistance_levels": [],
                "chart_patterns": [],
                "moving_averages": [{"moving_average_id": "aaa.ma.1"}],
                "moving_average": {"moving_average_id": "aaa.ma.1"},
                "volume_observation": None,
            },
            {
                "symbol": "BBB",
                "support_resistance_levels": [],
                "chart_patterns": [],
                "moving_averages": [{"moving_average_id": "bbb.ma.1"}],
                "moving_average": {"moving_average_id": "bbb.ma.1"},
                "volume_observation": None,
            },
        ],
        "horizon_opportunities": [
            {
                "opportunity_id": "opportunity-AAA",
                "rank": 1,
                "symbol": "AAA",
                "executor_id": "technical.horizon_adaptive_trend.v1",
                "evidence_ids": ["aaa.ma.1"],
            },
            {
                "opportunity_id": "opportunity-BBB",
                "rank": 2,
                "symbol": "BBB",
                "executor_id": "technical.horizon_adaptive_trend.v1",
                "evidence_ids": ["bbb.ma.1"],
            },
        ],
    }
    compact = compact_horizon_technical_report(full_report, max_assets=10)
    scope = CandidatePromptScope.from_compacted_report(compact)
    valid = _candidate_proposal(
        symbol="AAA",
        evidence_id="aaa.ma.1",
        child_executor_id="technical.horizon_adaptive_trend.v1",
    )
    scope.validate_proposal(valid)

    outside_symbol = _candidate_proposal(
        symbol="ZZZ",
        evidence_id="aaa.ma.1",
        child_executor_id="technical.horizon_adaptive_trend.v1",
    )
    with pytest.raises(ValueError, match="symbol outside"):
        scope.validate_proposal(outside_symbol)

    outside_evidence = _candidate_proposal(
        symbol="AAA",
        evidence_id="zzz.ma.1",
        child_executor_id="technical.horizon_adaptive_trend.v1",
    )
    with pytest.raises(ValueError, match="evidence outside"):
        scope.validate_proposal(outside_evidence)


def _opportunity_proposal(
    *opportunity_refs: str,
    parameters_by_ref: dict[str, dict[str, float]] | None = None,
) -> OpportunityCandidateProposalDraft:
    sleeves = [
        {
            "opportunity_ref": opportunity_ref,
            "expected_return_rationale": (
                f"{opportunity_ref} has favorable training-period evidence."
            ),
            "parameters": (parameters_by_ref or {}).get(opportunity_ref, {}),
        }
        for opportunity_ref in opportunity_refs
    ]
    return OpportunityCandidateProposalDraft.model_validate(
        {
            "rule": {
                "strategy_name": "Atomic opportunity selection",
                "hypothesis": "Selected opportunities may have positive return.",
                "rule_summary": "Execute the selected Technical opportunities.",
                "asset_eligibility_logic": "Use only the submitted catalog.",
                "signal_logic": "Use each selected deterministic signal family.",
                "position_logic": "Hold one long sleeve per ETF.",
                "entry_logic": "Enter under the registered child executor.",
                "exit_logic": "Exit under the registered child executor.",
                "rebalancing_logic": "Rebalance on the requested cadence.",
                "portfolio": {
                    "portfolio_target_gross_weight": 1.0,
                    "omission_rationale": (
                        "Fewer than ten qualifying ETFs were supplied."
                        if len(sleeves) < 10
                        else ""
                    ),
                    "sleeves": sleeves,
                },
            },
            "backtest_plan": {
                "transaction_cost_assumptions": {
                    "initial_capital": 100_000.0,
                    "commission_bps": 1.0,
                    "slippage_bps": 1.0,
                    "fill_price_field": "open",
                    "signal_delay_bars": 1,
                    "liquidate_at_end": True,
                    "annualization_factor": 252,
                }
            },
        }
    )


def test_catalog_and_system_prompt_make_parameter_ownership_explicit() -> None:
    spec = TECHNICAL_EXECUTOR_SPEC_BY_ID[CATALOG_PORTFOLIO_EXECUTOR_ID]
    rendered = render_executor_catalog((CATALOG_PORTFOLIO_EXECUTOR_ID,))
    forbidden = {
        "target_asset_count",
        "selected_asset_count",
        "allocation_method",
        "selection_threshold",
        "common_risk_parameters",
    }

    assert set(spec.model_authored_parameters) == {
        "portfolio_target_gross_weight",
        "omission_rationale",
        "sleeves",
    }
    assert forbidden == set(spec.code_owned_parameters)
    assert "Code-owned parameters (do not author)" in rendered
    assert "Those fields are code-owned" in TECHNICAL_TRADER_SYSTEM_PROMPT
    assert "Include `max_holding_bars`" not in TECHNICAL_TRADER_SYSTEM_PROMPT


def test_paid_run_extra_portfolio_fields_remain_rejected() -> None:
    payload = _opportunity_proposal("O001").model_dump(mode="python")
    payload["rule"]["portfolio"].update(
        {
            "target_asset_count": 10,
            "selected_asset_count": 1,
            "allocation_method": "equal_weight",
            "selection_threshold": "hostile-model-value",
            "common_risk_parameters": {"max_holding_bars": 9999},
        }
    )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        OpportunityCandidateProposalDraft.model_validate(payload)

    payload = _opportunity_proposal("O001").model_dump(mode="python")
    payload["rule"]["portfolio"]["unknown_sixth_field"] = True
    with pytest.raises(ValidationError, match="unknown_sixth_field"):
        OpportunityCandidateProposalDraft.model_validate(payload)


def test_atomic_opportunity_ref_expands_without_prompt_aliases() -> None:
    report = {
        "assets": [
            {
                "symbol": "AAA",
                "support_resistance_levels": [],
                "chart_patterns": [],
                "moving_averages": [
                    {
                        "moving_average_id": "aaa.ma.1",
                        "relationship": "above",
                    }
                ],
                "moving_average": {"moving_average_id": "aaa.ma.1"},
                "volume_observation": None,
            }
        ],
        "horizon_opportunities": [
            {
                "opportunity_id": "opportunity-AAA-trend",
                "rank": 1,
                "symbol": "AAA",
                "executor_id": "technical.horizon_adaptive_trend.v1",
                "evidence_ids": ["aaa.ma.1"],
                "score": 0.8,
            }
        ],
    }
    compact = compact_horizon_technical_report(report, max_assets=10)
    scope = CandidatePromptScope.from_compacted_report(compact)
    prompt_report = build_opportunity_prompt_report(compact, scope)

    serialized_prompt = json.dumps(prompt_report)
    assert "O001" in serialized_prompt
    assert "aaa.ma.1" not in serialized_prompt
    assert "opportunity-AAA-trend" not in serialized_prompt

    expanded = scope.expand_opportunity_proposal(
        _opportunity_proposal("O001")
    )
    sleeve = expanded.rule.parameters["sleeves"][0]
    assert sleeve["symbol"] == "AAA"
    assert sleeve["executor_id"] == "technical.horizon_adaptive_trend.v1"
    assert sleeve["evidence_ids"] == ["aaa.ma.1"]
    assert "O001" not in expanded.model_dump_json()


def test_unknown_opportunity_ref_is_rejected_with_sleeve_number() -> None:
    scope = CandidatePromptScope(
        symbols=frozenset({"AAA"}),
        evidence_ids=frozenset({"aaa.ma.1"}),
        opportunity_keys=frozenset(
            {
                (
                    "AAA",
                    "technical.horizon_adaptive_trend.v1",
                    ("aaa.ma.1",),
                )
            }
        ),
        opportunity_by_ref={
            "O001": OpportunityBinding(
                opportunity_ref="O001",
                opportunity_id="opportunity-AAA-trend",
                symbol="AAA",
                executor_id="technical.horizon_adaptive_trend.v1",
                evidence_ids=("aaa.ma.1",),
                rank=1,
                score=0.8,
            )
        },
    )
    with pytest.raises(
        ValueError,
        match="sleeve 1 selected unknown opportunity reference 'O999'",
    ):
        scope.expand_opportunity_proposal(_opportunity_proposal("O999"))
    with pytest.raises(ValueError, match="malformed opportunity reference"):
        scope.expand_opportunity_proposal(_opportunity_proposal("O1"))
    lowercase = scope.expand_opportunity_proposal(
        _opportunity_proposal("o001")
    )
    assert lowercase.rule.parameters["sleeves"][0]["symbol"] == "AAA"
    package_message = redact_opportunity_references(
        "Candidate sleeve selected unknown O999."
    )
    assert "O999" not in package_message
    assert "prompt-local opportunity reference" in package_message


def test_family_parameters_must_match_the_atomic_opportunity_executor() -> None:
    scope = CandidatePromptScope(
        symbols=frozenset({"AAA"}),
        evidence_ids=frozenset({"aaa.ma.1"}),
        opportunity_keys=frozenset(
            {
                (
                    "AAA",
                    "technical.horizon_adaptive_trend.v1",
                    ("aaa.ma.1",),
                )
            }
        ),
        opportunity_by_ref={
            "O001": OpportunityBinding(
                opportunity_ref="O001",
                opportunity_id="opportunity-AAA-trend",
                symbol="AAA",
                executor_id="technical.horizon_adaptive_trend.v1",
                evidence_ids=("aaa.ma.1",),
                rank=1,
                score=0.8,
            )
        },
    )

    with pytest.raises(ValueError, match="unexpected entry_buffer_percent"):
        scope.expand_opportunity_proposal(
            _opportunity_proposal(
                "O001",
                parameters_by_ref={"O001": {"entry_buffer_percent": 0.01}},
            )
        )


def test_model_authored_numeric_limits_match_child_executors() -> None:
    valid = OpportunitySleeveParametersDraft.model_validate(
        {
            "entry_buffer_percent": 0.25,
            "support_entry_floor_buffer_percent": 0.25,
            "technical_invalidation_buffer_percent": 0.25,
            "minimum_relative_volume": 10.0,
            "breakout_buffer_percent": 0.25,
        }
    )
    assert valid.technical_invalidation_buffer_percent == 0.25

    for field, invalid_value in (
        ("entry_buffer_percent", 0.250001),
        ("support_entry_floor_buffer_percent", 0.250001),
        ("technical_invalidation_buffer_percent", 0.250001),
        ("breakout_buffer_percent", 0.250001),
        ("minimum_relative_volume", 10.000001),
        ("minimum_relative_volume", 0.999999),
    ):
        with pytest.raises(ValidationError, match=field):
            OpportunitySleeveParametersDraft.model_validate(
                {field: invalid_value}
            )


def _rolling_portfolio_parameters(
    *,
    invalidation_buffer: float,
) -> dict[str, Any]:
    return {
        "target_asset_count": 10,
        "selected_asset_count": 1,
        "portfolio_target_gross_weight": 1.0,
        "allocation_method": "equal_weight",
        "selection_threshold": (
            "positive_expected_return_from_training_evidence"
        ),
        "omission_rationale": "Only one qualifying ETF was supplied.",
        "common_risk_parameters": {
            "max_holding_bars": 504,
            "volatility_lookback_bars": 63,
            "profit_target_sigma_multiple": 2.0,
            "stop_loss_sigma_multiple": 1.75,
        },
        "sleeves": [
            {
                "symbol": "AAA",
                "executor_id": "technical.rolling_resistance_breakout.v1",
                "evidence_ids": ["aaa.resistance.1"],
                "opportunity_id": "opportunity-AAA-resistance",
                "opportunity_rank": 1,
                "opportunity_score": 0.9,
                "expected_return_rationale": "Reliable resistance is nearby.",
                "parameters": {
                    "review_interval_bars": 21,
                    "rolling_level_lookback_bars": 504,
                    "pivot_window": 5,
                    "merge_tolerance_percent": 0.01,
                    "min_touches": 2,
                    "maximum_level_distance_percent": 20.0,
                    "entry_buffer_percent": 0.25,
                    "technical_invalidation_buffer_percent": (
                        invalidation_buffer
                    ),
                },
            }
        ],
    }


def test_bound_portfolio_is_validated_before_backtest_execution() -> None:
    valid = validate_technical_portfolio_parameters(
        _rolling_portfolio_parameters(invalidation_buffer=0.25)
    )
    assert valid.sleeves[0].symbol == "AAA"

    with pytest.raises(
        ValueError,
        match=(
            r"sleeves\[1\] 'AAA'.*"
            "technical_invalidation_buffer_percent must be at most 0.25"
        ),
    ):
        validate_technical_portfolio_parameters(
            _rolling_portfolio_parameters(invalidation_buffer=0.5)
        )


def test_atomic_expansion_rejects_two_opportunities_for_one_etf() -> None:
    executor_id = "technical.horizon_adaptive_trend.v1"
    scope = CandidatePromptScope(
        symbols=frozenset({"AAA"}),
        evidence_ids=frozenset({"aaa.ma.1", "aaa.ma.2"}),
        opportunity_keys=frozenset(
            {
                ("AAA", executor_id, ("aaa.ma.1",)),
                ("AAA", executor_id, ("aaa.ma.2",)),
            }
        ),
        opportunity_by_ref={
            reference: OpportunityBinding(
                opportunity_ref=reference,
                opportunity_id=f"opportunity-AAA-{index}",
                symbol="AAA",
                executor_id=executor_id,
                evidence_ids=(f"aaa.ma.{index}",),
                rank=index,
                score=0.9 - index / 10,
            )
            for index, reference in enumerate(("O001", "O002"), start=1)
        },
    )

    with pytest.raises(ValueError, match="would reuse ETF symbol 'AAA'"):
        scope.expand_opportunity_proposal(
            _opportunity_proposal("O001", "O002")
        )


def test_ten_sleeve_atomic_expansion_is_canonical_and_valid() -> None:
    assets = []
    opportunities = []
    for index in range(10):
        symbol = f"ETF{index:02d}"
        evidence_id = f"{symbol}.moving-average.20-50"
        assets.append(
            {
                "symbol": symbol,
                "support_resistance_levels": [],
                "chart_patterns": [],
                "moving_averages": [
                    {
                        "moving_average_id": evidence_id,
                        "relationship": "bullish",
                    }
                ],
                "moving_average": {"moving_average_id": evidence_id},
                "volume_observation": None,
            }
        )
        opportunities.append(
            {
                "opportunity_id": f"opportunity-{symbol}",
                "rank": index + 1,
                "symbol": symbol,
                "executor_id": "technical.horizon_adaptive_trend.v1",
                "evidence_ids": [evidence_id],
                "score": 1.0 - index / 20,
            }
        )
    compact = compact_horizon_technical_report(
        {
            "assets": assets,
            "horizon_opportunities": opportunities,
        },
        max_assets=10,
    )
    scope = CandidatePromptScope.from_compacted_report(compact)

    expanded = scope.expand_opportunity_proposal(
        _opportunity_proposal(*scope.opportunity_by_ref)
    )
    scope.validate_proposal(expanded)

    sleeves = expanded.rule.parameters["sleeves"]
    assert len(sleeves) == 10
    assert len({sleeve["symbol"] for sleeve in sleeves}) == 10
    assert set(expanded.rule.specialty_evidence_ids) == scope.evidence_ids
    assert "O00" not in expanded.model_dump_json()


def test_rejected_candidate_diagnostic_writes_separate_json(tmp_path) -> None:
    sink = JsonFileTechnicalDiagnosticsSink(tmp_path)
    diagnostic = TechnicalCandidateDiagnostic(
        diagnostic_id="task.candidate_proposal.attempt-1",
        workflow_id="workflow-test",
        task_id="task-test",
        attempt=1,
        stage="candidate_proposal",
        error_type="ValueError",
        error_message="Unknown opportunity reference O999.",
        raw_proposal={"rule": {"portfolio": {"sleeves": []}}},
        opportunity_catalog=[{"opportunity_ref": "O001"}],
    )

    sink.record(diagnostic)

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["stage"] == "candidate_proposal"
    assert payload["raw_proposal"] == {
        "rule": {"portfolio": {"sleeves": []}}
    }


def test_diagnostics_sink_failure_remains_non_fatal() -> None:
    class RaisingSink:
        def record(self, diagnostic: TechnicalCandidateDiagnostic) -> None:
            del diagnostic
            raise OSError("diagnostic storage unavailable")

    agent = TechnicalTraderAgent(
        model_client=cast(Any, object()),
        data_service=cast(Any, object()),
        backtest_engine=cast(Any, object()),
        available_executors=[MULTI_ASSET_PORTFOLIO_EXECUTOR_ID],
        validation_split_policy=CapturingValidationSplitPolicy(),
        benchmark_symbol="IVV",
        diagnostics_sink=RaisingSink(),
    )

    agent._record_candidate_diagnostic(
        request=_technical_task(),
        stage="candidate_proposal",
        error=StructuredOutputValidationError(
            "invalid provider output",
            raw_payload={"safe": "model output only"},
        ),
        raw_proposal={"safe": "model output only"},
        expanded_proposal=None,
        scope=None,
    )


def test_full_test_identity_is_fresh_and_coherent() -> None:
    first = derive_demo_identifiers(
        {"FULL_TEST_WORKFLOW_ID": "full-loop-local-first"}
    )
    second = derive_demo_identifiers(
        {"FULL_TEST_WORKFLOW_ID": "full-loop-local-second"}
    )

    assert first == (
        "full-loop-local-first.run",
        "full-loop-local-first",
        "full-loop-local-first.task",
    )
    assert second != first
    with pytest.raises(ValueError, match="must be non-empty"):
        derive_demo_identifiers({"FULL_TEST_WORKFLOW_ID": "   "})


def test_scope_violating_review_retains_validated_initial_proposal() -> None:
    scope = CandidatePromptScope(
        symbols=frozenset({"AAA"}),
        evidence_ids=frozenset({"aaa.ma.1"}),
        opportunity_keys=frozenset(
            {
                (
                    "AAA",
                    "technical.horizon_adaptive_trend.v1",
                    ("aaa.ma.1",),
                )
            }
        ),
    )
    initial = _candidate_proposal(
        symbol="AAA",
        evidence_id="aaa.ma.1",
        child_executor_id="technical.horizon_adaptive_trend.v1",
    )
    reviewed = _candidate_proposal(
        symbol="ZZZ",
        evidence_id="aaa.ma.1",
        child_executor_id="technical.horizon_adaptive_trend.v1",
    )

    selected, review_applied, error = (
        StagedTraderAgent._select_reviewed_candidate(
            initial_proposal=initial,
            reviewed_proposal=reviewed,
            scope=scope,
        )
    )

    assert selected is initial
    assert review_applied is False
    assert isinstance(error, AgentOutputValidationError)
    assert "symbol outside" in str(error)


@pytest.mark.parametrize(
    "client",
    [
        OpenAITechnicalModelClient(
            api_key="not-a-real-key",
            model="openai-test-model",
            client=SimpleNamespace(responses=FakeOpenAIResponses()),
        ),
        AnthropicTechnicalModelClient(
            api_key="not-a-real-key",
            model="anthropic-test-model",
            native_structured_outputs=False,
            client=SimpleNamespace(messages=FakeAnthropicMessages()),
        ),
    ],
    ids=["openai", "anthropic"],
)
def test_runtime_rejects_adapter_budget_incompatible_with_its_policy(
    client: Any,
) -> None:
    with pytest.raises(ValueError, match="provider timeout/retry budget"):
        create_technical_trader_runtime(
            model_client=client,
            data_service=cast(Any, object()),
            backtest_engine=cast(Any, object()),
            available_executors=[MULTI_ASSET_PORTFOLIO_EXECUTOR_ID],
            validation_split_policy=cast(Any, object()),
            execution_policy=ExecutionPolicy(model_call_timeout_seconds=20),
        )


class CapturingValidationSplitPolicy:
    def __init__(self) -> None:
        self.plan: BacktestPlanDraft | None = None

    def resolve(self, *, task, plan, data_response):
        self.plan = plan
        return ValidationSplit(
            test_start_date=date(2026, 7, 1),
            test_end_date=date(2026, 7, 29),
        )


class CalendarInputAdapter:
    def __init__(self, dates: list[date]) -> None:
        self._dates = dates

    def extract(self, response: DataResponse):
        del response
        return [
            SimpleNamespace(
                bars=[
                    SimpleNamespace(
                        timestamp=datetime(
                            session.year,
                            session.month,
                            session.day,
                            tzinfo=timezone.utc,
                        )
                    )
                    for session in self._dates
                ]
            )
        ]


def _trailing_weekdays(*, end: date, count: int) -> list[date]:
    result: list[date] = []
    current = end
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current -= timedelta(days=1)
    return list(reversed(result))


def _technical_task() -> TraderTask:
    context = ResearchExecutionContext(
        run_id="workflow-test",
        round_number=1,
    )
    lineage = TaskLineage(
        workflow_id="workflow-test",
        task_id="task-test.round-1.technical.trader",
        parent_task_id="task-test",
        source_task_id="task-test",
        attempt=1,
    )
    mandate = PMMandate(
        workflow_id="workflow-test",
        task_id="task-test",
        as_of_date=date(2026, 7, 31),
        investment_objective="Seek short-horizon appreciation.",
        investment_horizon={"trading_days": 21},
        permitted_asset_universe=["IVV"],
    )
    return TraderTask(
        mandate=mandate,
        lineage=lineage,
        trader_id=SpecialistId.TECHNICAL_TRADER,
        execution_context=context,
    )


@pytest.mark.parametrize(
    ("investment_horizon", "expected_sessions"),
    [
        (None, 63),
        ({"trading_days": 21}, 21),
        ({"weeks": 2}, 10),
        ({"months": 6}, 126),
        ({"years": 2}, 504),
    ],
)
def test_horizon_matched_policy_supports_any_mandate_horizon(
    investment_horizon: Any,
    expected_sessions: int,
) -> None:
    as_of_date = date(2026, 7, 31)
    dates = _trailing_weekdays(end=as_of_date, count=900)
    task = _technical_task()
    task = task.model_copy(
        update={
            "mandate": task.mandate.model_copy(
                update={
                    "as_of_date": as_of_date,
                    "investment_horizon": investment_horizon,
                }
            )
        }
    )
    response = DataResponse(
        response_id="data-response-horizon-test",
        request_id="data-request-horizon-test",
        lineage=task.lineage.child("data"),
        as_of_date=as_of_date,
        complete=True,
    )
    policy = HorizonMatchedValidationSplitPolicy(
        input_adapter=cast(Any, CalendarInputAdapter(dates))
    )

    split = policy.resolve(
        task=task,
        plan=BacktestPlanDraft(frequency="daily"),
        data_response=response,
    )

    assert split.test_start_date == dates[-expected_sessions]
    assert split.test_end_date == dates[-1]


def test_horizon_policy_uses_benchmark_calendar_and_ignores_future_bars() -> None:
    as_of_date = date(2026, 7, 31)
    benchmark_dates = _trailing_weekdays(end=as_of_date, count=300)
    unrelated_dates = [
        *benchmark_dates,
        date(2026, 8, 3),
        date(2026, 8, 4),
    ]

    class NamedCalendarInputAdapter:
        def extract(self, response: DataResponse):
            del response

            def series(symbol: str, dates: list[date]) -> SimpleNamespace:
                return SimpleNamespace(
                    symbol=symbol,
                    bars=[
                        SimpleNamespace(
                            timestamp=datetime(
                                session.year,
                                session.month,
                                session.day,
                                tzinfo=timezone.utc,
                            )
                        )
                        for session in dates
                    ],
                )

            return [
                series("IVV", benchmark_dates),
                series("LATE", unrelated_dates),
            ]

    task = _technical_task()
    response = DataResponse(
        response_id="data-response-calendar-test",
        request_id="data-request-calendar-test",
        lineage=task.lineage.child("data"),
        as_of_date=as_of_date,
        complete=True,
    )
    policy = HorizonMatchedValidationSplitPolicy(
        input_adapter=cast(Any, NamedCalendarInputAdapter())
    )
    split = policy.resolve(
        task=task,
        plan=BacktestPlanDraft(frequency="daily", benchmark="IVV"),
        data_response=response,
    )

    assert split.test_start_date == benchmark_dates[-21]
    assert split.test_end_date == as_of_date


def test_validation_policy_is_required_and_receives_meaningful_plan() -> None:
    with pytest.raises(ValueError, match="validation_split_policy is required"):
        TechnicalTraderAgent(
            model_client=cast(Any, object()),
            data_service=cast(Any, object()),
            backtest_engine=cast(Any, object()),
            available_executors=[MULTI_ASSET_PORTFOLIO_EXECUTOR_ID],
            validation_split_policy=cast(Any, None),
        )

    with pytest.raises(ValueError, match="benchmark_symbol is required"):
        TechnicalTraderAgent(
            model_client=cast(Any, object()),
            data_service=cast(Any, object()),
            backtest_engine=cast(Any, object()),
            available_executors=[MULTI_ASSET_PORTFOLIO_EXECUTOR_ID],
            validation_split_policy=CapturingValidationSplitPolicy(),
        )

    policy = CapturingValidationSplitPolicy()
    agent = TechnicalTraderAgent(
        model_client=cast(Any, object()),
        data_service=cast(Any, object()),
        backtest_engine=cast(Any, object()),
        available_executors=[MULTI_ASSET_PORTFOLIO_EXECUTOR_ID],
        validation_split_policy=policy,
        benchmark_symbol="IVV",
    )
    task = _technical_task()
    response = DataResponse(
        response_id="data-response-test",
        request_id="data-request-test",
        lineage=task.lineage.child("data"),
        as_of_date=task.mandate.as_of_date,
        complete=True,
    )

    split = agent._resolve_validation_split(
        request=task,
        data_response=response,
    )

    assert split.test_end_date == date(2026, 7, 29)
    captured_plan = policy.plan
    assert captured_plan is not None
    assert captured_plan.requested_end_date == task.mandate.as_of_date
    assert captured_plan.frequency == "daily"
    assert captured_plan.benchmark == "IVV"
    assert captured_plan.held_out_evaluation_required is True
    assert "total_return" in captured_plan.requested_metrics
    assert "horizon_matched_evaluation" in captured_plan.validation_requirements
