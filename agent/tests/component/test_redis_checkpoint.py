import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from flowfix_agent.dispatch.adapters.decision_repository import InMemoryDispatchDecisionRepository
from flowfix_agent.dispatch.adapters.fake_tools import FakeDispatchToolAdapter
from flowfix_agent.dispatch.adapters.skill_registry import FileDispatchSkillRegistry
from flowfix_agent.dispatch.application.service import DispatchDecisionService
from flowfix_agent.dispatch.domain.models import (
    DispatchRequest,
    WorkerSnapshot,
    WorkOrderPriority,
    WorkOrderSnapshot,
)
from flowfix_agent.dispatch.runtime.graph import DispatchAgentRuntime
from flowfix_agent.dispatch.runtime.middleware import DispatchToolGateway
from flowfix_agent.dispatch.runtime.models import (
    ApprovalDecision,
    DispatchRuntimeInput,
    RequestContext,
    RuntimeStatus,
)
from flowfix_agent.dispatch.skills.loader import DispatchSkillLoader

BUILTIN = Path("src/flowfix_agent/dispatch/skills/builtin")
NOW = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)


# 构造到达人工审批中断的派单运行时（HIGH 优先级触发 MANUAL 决策）。
def build_runtime(checkpointer: AsyncRedisSaver, tmp_path: Path) -> DispatchAgentRuntime:
    order = WorkOrderSnapshot(
        work_order_id="wo-1",
        tenant_id="tenant-1",
        device_id="device-1",
        region="east",
        required_skills=["plc"],
        version=3,
        captured_at=NOW,
        priority=WorkOrderPriority.HIGH,
    )
    workers = [
        WorkerSnapshot(
            worker_id="w1",
            tenant_id="tenant-1",
            region="east",
            skills={"plc": 0.9},
            current_load=1,
            capacity=5,
            distance_km=8,
            sla_readiness=0.8,
            captured_at=NOW,
        ),
        WorkerSnapshot(
            worker_id="w2",
            tenant_id="tenant-1",
            region="east",
            skills={"plc": 0.8},
            current_load=1,
            capacity=5,
            distance_km=3,
            sla_readiness=0.9,
            captured_at=NOW,
        ),
    ]
    registry = FileDispatchSkillRegistry(tmp_path / "registry.json")
    for skill in DispatchSkillLoader().load_directory(BUILTIN):
        registry.register(skill)
    registry.activate("balanced", "1.0.0")
    return DispatchAgentRuntime(
        DispatchDecisionService(registry, InMemoryDispatchDecisionRepository()),
        DispatchToolGateway(FakeDispatchToolAdapter([order], workers)),
        checkpointer=checkpointer,
    )


# 验证 Redis 检查点可以在全新运行时实例间恢复中断线程。
@pytest.mark.integration
async def test_redis_checkpoint_resumes_across_runtime_instances(tmp_path: Path):
    url = os.getenv("REDIS_TEST_URL")
    if not url:
        pytest.skip("set REDIS_TEST_URL to run the Redis component test")

    event_id = f"e-{uuid.uuid4().hex[:8]}"
    checkpointer = AsyncRedisSaver(redis_url=url)
    await checkpointer.asetup()
    try:
        first = build_runtime(checkpointer, tmp_path)
        result = await first.start(
            DispatchRuntimeInput(
                request=DispatchRequest(
                    dispatch_id=f"dispatch-{event_id}",
                    event_id=event_id,
                    tenant_id="tenant-1",
                    requested_at=NOW,
                ),
                work_order_id="wo-1",
                context=RequestContext(
                    trace_id=f"trace-{event_id}",
                    tenant_id="tenant-1",
                    event_id=event_id,
                    permissions=["dispatch:read", "dispatch:write", "dispatch:audit"],
                    deadline=datetime.now(UTC) + timedelta(minutes=2),
                ),
            )
        )
        assert result.status == RuntimeStatus.AWAITING_APPROVAL
        assert result.interrupted

        # 使用全新运行时实例恢复同一线程，验证状态从 Redis 读出。
        second = build_runtime(checkpointer, tmp_path)
        resumed = await second.resume(
            f"dispatch:tenant-1:dispatch-{event_id}",
            ApprovalDecision(
                approved=True,
                worker_id="w1",
                reviewer_id="reviewer-1",
                reason="approved in test",
            ),
        )
        assert resumed.status == RuntimeStatus.AUDITED
        history = await second.state_history(
            f"dispatch:tenant-1:dispatch-{event_id}"
        )
        assert len(history) > 0
    finally:
        await checkpointer.adelete_thread(
            f"dispatch:tenant-1:dispatch-{event_id}"
        )
        await checkpointer.__aexit__(None, None, None)
