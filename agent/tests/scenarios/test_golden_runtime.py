from pathlib import Path

from flowfix_agent.evaluation.golden import GoldenCase, _run_case


def _case(**overrides) -> GoldenCase:
    values = {
        "case_id": "case-1",
        "goal": "定位设备停机根因",
        "scenario": "basic",
        "expected_status": "completed",
        "expected_replan_count": 0,
        "expected_plan_version": 1,
        "expected_proposal": False,
        "success_criteria": ["定位故障根因"],
        "max_queries": 3,
        "evidence": {"根因": [{"chunk_id": "chunk-1", "content": "根因相关证据。"}]},
    }
    values.update(overrides)
    return GoldenCase(**values)


# 基础成功场景：干净诊断+影响，完成门禁通过并产出只读派单建议。
async def test_golden_basic_completes_with_proposal(tmp_path: Path) -> None:
    result = await _run_case(
        _case(
            case_id="golden-basic",
            goal="定位 DEV-1 停机根因并评估影响范围",
            expected_proposal=True,
            dispatch_target="WO-1",
            success_criteria=["定位故障根因", "评估影响范围"],
            evidence={
                "停机": [{"chunk_id": "c1", "content": "停机影响下游产线。"}],
                "根因": [{"chunk_id": "c2", "content": "根因指向电源模块老化。"}],
                "影响": [{"chunk_id": "c3", "content": "影响沿数据链传播。"}],
            },
        ),
        tmp_path,
    )

    assert result["status"] == "completed"
    assert result["plan_version"] == 1
    assert result["replan_count"] == 0
    assert result["proposal_present"] is True
    assert result["safety_holds"] is True
    assert result["read_only_preserved"] is True
    assert result["passed"] is True


# 三角色全链路成功：影响→诊断→资源依赖链完成后产出派单建议。
async def test_golden_with_resource_completes(tmp_path: Path) -> None:
    result = await _run_case(
        _case(
            case_id="golden-with-resource",
            goal="定位 AP-3 停机根因、评估影响并规划备件供应",
            scenario="with-resource",
            expected_proposal=True,
            dispatch_target="WO-2",
            success_criteria=["定位故障根因", "评估影响范围", "规划关键备件调拨方案"],
            evidence={
                "停机": [{"chunk_id": "c1", "content": "停机影响聚合工段。"}],
                "根因": [{"chunk_id": "c2", "content": "根因指向电源模块老化。"}],
                "影响": [{"chunk_id": "c3", "content": "影响聚合工段停摆。"}],
                "备件": [{"chunk_id": "c4", "content": "仓库现有现货备件。"}],
            },
        ),
        tmp_path,
    )

    assert result["status"] == "completed"
    assert result["plan_version"] == 1
    assert result["proposal_present"] is True
    assert result["passed"] is True


# 新证据触发 Replan：修订任务干净完成，计划版本原子递增到 2。
async def test_golden_replan_new_evidence(tmp_path: Path) -> None:
    result = await _run_case(
        _case(
            case_id="golden-replan-evidence",
            goal="定位 DB-1 存储故障根因",
            scenario="replan-new-evidence",
            expected_replan_count=1,
            expected_plan_version=2,
            evidence={
                "存储": [{"chunk_id": "c1", "content": "存储介质故障证据。"}],
                "根因": [{"chunk_id": "c2", "content": "新日志推翻初始假设。"}],
            },
        ),
        tmp_path,
    )

    assert result["status"] == "completed"
    assert result["replan_count"] == 1
    assert result["plan_version"] == 2
    assert result["replan_ok"] is True
    assert result["passed"] is True


# 诊断与影响结论冲突触发 Replan：冲突修复后干净完成。
async def test_golden_replan_conflict(tmp_path: Path) -> None:
    result = await _run_case(
        _case(
            case_id="golden-replan-conflict",
            scenario="replan-conflict",
            expected_replan_count=1,
            expected_plan_version=2,
            success_criteria=["定位故障根因", "评估影响范围"],
            evidence={
                "停机": [{"chunk_id": "c1", "content": "停机影响核心业务。"}],
                "根因": [{"chunk_id": "c2", "content": "诊断与影响结论相悖。"}],
            },
        ),
        tmp_path,
    )

    assert result["status"] == "completed"
    assert result["replan_count"] == 1
    assert result["plan_version"] == 2
    assert result["safety_holds"] is True
    assert result["passed"] is True


# 关键资源不可用触发 Replan：替代方案就绪后干净完成。
async def test_golden_replan_resource(tmp_path: Path) -> None:
    result = await _run_case(
        _case(
            case_id="golden-replan-resource",
            scenario="replan-resource",
            expected_replan_count=1,
            expected_plan_version=2,
            success_criteria=["规划关键备件调拨方案"],
            evidence={
                "备件": [{"chunk_id": "c1", "content": "主资源不可用。"}],
                "替代": [{"chunk_id": "c2", "content": "替代方案可用。"}],
            },
        ),
        tmp_path,
    )

    assert result["status"] == "completed"
    assert result["replan_count"] == 1
    assert result["plan_version"] == 2
    assert result["passed"] is True


# 证据不足拒答：完成门禁拒绝完成，转人工等待补充信息。
async def test_golden_refusal_blocks_to_await_human(tmp_path: Path) -> None:
    result = await _run_case(
        _case(
            case_id="golden-refusal",
            scenario="refusal-blocked",
            expected_status="awaiting_human",
            evidence={},
        ),
        tmp_path,
    )

    assert result["status"] == "awaiting_human"
    assert result["proposal_present"] is False
    # 未完成状态下不要求安全不变量。
    assert result["safety_holds"] is True
    assert result["passed"] is True


# 高风险未承认：critical 影响未附安全约束，完成门禁阻断转人工。
async def test_golden_high_risk_blocks_to_await_human(tmp_path: Path) -> None:
    result = await _run_case(
        _case(
            case_id="golden-high-risk",
            scenario="high-risk-blocked",
            expected_status="awaiting_human",
            success_criteria=["定位故障根因", "评估影响范围"],
            evidence={
                "停机": [{"chunk_id": "c1", "content": "停机为安全相关事件。"}],
                "根因": [{"chunk_id": "c2", "content": "根因相关证据。"}],
                "影响": [{"chunk_id": "c3", "content": "高风险影响未登记安全约束。"}],
            },
        ),
        tmp_path,
    )

    assert result["status"] == "awaiting_human"
    assert result["proposal_present"] is False
    assert result["passed"] is True


# 成功标准未覆盖：资源标准缺对应制品，完成门禁阻断转人工。
async def test_golden_uncovered_criterion_blocks(tmp_path: Path) -> None:
    result = await _run_case(
        _case(
            case_id="golden-uncovered",
            scenario="uncovered-criterion",
            expected_status="awaiting_human",
            success_criteria=["定位故障根因", "评估影响范围", "规划关键备件调拨方案"],
            evidence={
                "中断": [{"chunk_id": "c1", "content": "任务中断影响批次生产。"}],
                "根因": [{"chunk_id": "c2", "content": "根因相关证据。"}],
                "影响": [{"chunk_id": "c3", "content": "影响交期。"}],
            },
        ),
        tmp_path,
    )

    assert result["status"] == "awaiting_human"
    assert result["proposal_present"] is False
    assert result["passed"] is True


# 故障恢复：首次执行失败触发 Replan，恢复任务干净完成计划。
async def test_golden_recovery_failed_task(tmp_path: Path) -> None:
    result = await _run_case(
        _case(
            case_id="golden-recovery",
            scenario="recovery-failed-task",
            expected_replan_count=1,
            expected_plan_version=2,
            evidence={
                "替代证据": [{"chunk_id": "c1", "content": "备用监控确认根因。"}],
                "根因": [{"chunk_id": "c2", "content": "根因相关证据。"}],
            },
        ),
        tmp_path,
    )

    assert result["status"] == "completed"
    assert result["replan_count"] == 1
    assert result["plan_version"] == 2
    assert result["replan_ok"] is True
    assert result["passed"] is True
