from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import BaseModel
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
    StagedTraderAgent,
    TechnicalTraderAgent,
    TechnicalModelConfigurationError,
    compact_horizon_technical_report,
    create_technical_model_client_from_env,
    create_technical_trader_runtime,
)
from agents.technical_trader.prompts import CandidatePromptScope


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
        CandidateProposalDraft,
        BacktestInterpretationDraft,
    ):
        original = response_model.model_json_schema(mode="validation")
        transformed = anthropic.transform_schema(original)
        assert isinstance(transformed, dict)
        assert transformed
        assert transformed != original


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
                "TECHNICAL_TRADER_PROVIDER_TIMEOUT_SECONDS": "20",
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
                "rank": 1,
                "symbol": "AAA",
                "executor_id": "technical.horizon_adaptive_trend.v1",
                "evidence_ids": ["aaa.ma.1"],
            },
            {
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


def test_validation_policy_is_required_and_receives_meaningful_plan() -> None:
    with pytest.raises(ValueError, match="validation_split_policy is required"):
        TechnicalTraderAgent(
            model_client=cast(Any, object()),
            data_service=cast(Any, object()),
            backtest_engine=cast(Any, object()),
            available_executors=[MULTI_ASSET_PORTFOLIO_EXECUTOR_ID],
            validation_split_policy=cast(Any, None),
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
