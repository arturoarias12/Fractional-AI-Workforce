"""
手动探索脚本（不是正式的自动化测试，所以不用 test_ 开头命名）：
串联 technical/fundamental/quant（用假数据模拟）-> risk -> reporting

存放位置：tests/reporting_agent/manual_chain_check.py
（跟 tests/risk_agent/ 平级）

运行方法：
    在项目根目录、激活了 .venv 的终端里运行：
        python tests/reporting_agent/manual_chain_check.py
"""

import asyncio
import sys
from pathlib import Path

# 这个脚本在 tests/reporting_agent/ 里，
# risk_fixtures.py 在旁边的 tests/risk_agent/ 里，所以用 parent.parent 找过去
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "risk_agent"))

from risk_fixtures import (
    three_clean_candidates,
    build_request,
)  # noqa: E402

from agents.risk_agent import RiskAgentImpl  # noqa: E402
from agents.reporting_agent.reporting_agent_impl import ReportingAgentImpl  # noqa: E402
from protocols.reporting import ReportingRequest  # noqa: E402


async def main() -> None:
    # 1. 伪造 technical / fundamental / quant 三个trader的产出（不需要真代码）
    candidates = three_clean_candidates()
    risk_request = build_request(candidates)

    # 2. 真正跑一遍 Risk Agent（队友已经写完的真实实现）
    risk_agent = RiskAgentImpl()
    risk_response = await risk_agent.review(risk_request)

    print("=== Risk 的裁决结果 ===")
    for decision in risk_response.decisions:
        print(f"  {decision.candidate_id}: {decision.verdict}")

    # 3. 只把 Risk 批准通过的候选策略，交给 Reporting
    surviving_ids = set(risk_response.approved_candidate_ids())
    surviving_candidates = [
        candidate
        for candidate in candidates
        if str(candidate.candidate_id) in surviving_ids
    ]

    reporting_request = ReportingRequest(
        request_id=f"{risk_request.request_id}.reporting",
        mandate_task_id=risk_request.mandate_task_id,
        surviving_candidates=surviving_candidates,
        risk_response=risk_response,
    )

    # 4. 真正跑你写的 Reporting Agent
    reporting_agent = ReportingAgentImpl()  # 先不传 model_client 也能跑
    output = await reporting_agent.report(reporting_request)

    print("\n=== 你的 Reporting Agent 输出 ===")
    print(output)


if __name__ == "__main__":
    asyncio.run(main())
