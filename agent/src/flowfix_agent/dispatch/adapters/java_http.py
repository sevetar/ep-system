from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from flowfix_agent.core.errors import DependencyUnavailableError
from flowfix_agent.dispatch.domain.models import (
    WorkerSnapshot,
    WorkOrderPriority,
    WorkOrderSnapshot,
    WorkOrderStatus,
)
from flowfix_agent.dispatch.runtime.errors import ToolContractError
from flowfix_agent.dispatch.runtime.models import (
    AssignmentCommand,
    AssignmentOutcome,
    AssignmentOutcomeStatus,
    AssignmentReceipt,
    AssignmentReceiptStatus,
    AuditPublishResult,
    PolicyEvidence,
    RequestContext,
)

CONTRACT_VERSION = "dispatch-contract/v1"


class JavaDispatchHttpAdapter:
    """将 Agent 工具合同映射到 Java dispatch-contract/v1 HTTP 接口。"""

    # 保存 HTTP 客户端与审计日志路径，初始化负载缓存；幂等发布集合首次发布时惰性加载。
    def __init__(self, client: httpx.AsyncClient, audit_path: Path) -> None:
        self.client = client
        self.audit_path = audit_path
        self._audit_lock = asyncio.Lock()
        self._known_loads: dict[str, int] = {}
        self._published_dispatches: set[str] | None = None

    # 探测 Java 派单服务的健康状态。
    async def health(self) -> bool:
        try:
            payload = await self._request("GET", "/health", trace_id="health-check")
            return payload.get("status") == "UP"
        except (DependencyUnavailableError, ToolContractError):
            return False

    # 拉取工单快照并映射为领域模型，校验合同版本。
    async def get_work_order_snapshot(
        self, work_order_id: str, context: RequestContext
    ) -> WorkOrderSnapshot:
        payload = await self._request(
            "GET", f"/orders/{work_order_id}/snapshot", trace_id=context.trace_id
        )
        self._check_contract(payload)
        return WorkOrderSnapshot(
            work_order_id=payload["orderId"],
            tenant_id=payload["tenantId"],
            device_id=payload["deviceId"],
            region=payload["region"],
            required_skills=payload["requiredSkills"],
            priority=WorkOrderPriority(payload["priority"].lower()),
            status=WorkOrderStatus(payload["status"].lower()),
            version=payload["version"],
            assigned_worker_id=payload.get("assignedWorkerId"),
            captured_at=payload["snapshotAt"],
        )

    # 拉取合格 Worker 列表并更新本地的负载缓存。
    async def list_eligible_workers(
        self, work_order: WorkOrderSnapshot, context: RequestContext
    ) -> list[WorkerSnapshot]:
        payload = await self._request(
            "GET",
            f"/orders/{work_order.work_order_id}/workers",
            trace_id=context.trace_id,
        )
        self._check_contract(payload)
        workers = [self._worker(item) for item in payload["workers"]]
        self._known_loads.update(
            {worker.worker_id: worker.current_load for worker in workers}
        )
        return workers

    # 从本地缓存返回指定 Worker 的当前负载。
    async def get_worker_loads(
        self, worker_ids: list[str], context: RequestContext
    ) -> dict[str, int]:
        return {
            worker_id: self._known_loads[worker_id]
            for worker_id in worker_ids
            if worker_id in self._known_loads
        }

    # 检索派单策略证据；Java v1 无此接口，策略由 Skill 注册表提供，返回空列表。
    async def search_dispatch_policy(
        self, query: str, context: RequestContext
    ) -> list[PolicyEvidence]:
        # Java v1 没有策略检索接口；策略由 Agent 的版本化 Skill 注册表提供。
        return []

    # 创建派单分配并返回带幂等键的回执。
    async def create_assignment(
        self, command: AssignmentCommand, context: RequestContext
    ) -> AssignmentReceipt:
        payload = await self._request(
            "POST",
            "/assignments",
            trace_id=context.trace_id,
            headers={"Idempotency-Key": command.idempotency_key},
            json={
                "contractVersion": CONTRACT_VERSION,
                "traceId": context.trace_id,
                "eventId": command.event_id,
                "dispatchId": command.dispatch_id,
                "idempotencyKey": command.idempotency_key,
                "tenantId": command.tenant_id,
                "orderId": command.work_order_id,
                "workerId": command.worker_id,
                "expectedVersion": command.expected_version,
            },
            accept_business_error=True,
        )
        self._check_contract(payload)
        if "receiptStatus" not in payload:
            raise ToolContractError(
                f"Java assignment error: {payload.get('reasonCode', 'UNKNOWN')}"
            )
        return AssignmentReceipt(
            status=AssignmentReceiptStatus(payload["receiptStatus"].lower()),
            idempotency_key=payload["idempotencyKey"],
            work_order_id=payload["orderId"],
            worker_id=payload.get("workerId"),
            observed_version=payload.get("observedVersion"),
            reason_code=payload.get("reasonCode"),
            message=payload.get("reasonCode") or payload["receiptStatus"],
        )

    # 查询派单的最终分配结果。
    async def get_assignment_outcome(
        self, dispatch_id: str, context: RequestContext
    ) -> AssignmentOutcome:
        payload = await self._request(
            "GET", f"/assignments/{dispatch_id}/outcome", trace_id=context.trace_id
        )
        self._check_contract(payload)
        return AssignmentOutcome(
            status=AssignmentOutcomeStatus(payload["outcomeStatus"].lower()),
            idempotency_key=payload.get("idempotencyKey") or "unknown",
            work_order_id=payload.get("orderId") or "unknown",
            assigned_worker_id=payload.get("assignedWorkerId"),
            work_order_version=payload.get("version"),
            reason_code=payload.get("reasonCode"),
            message=payload.get("reasonCode") or payload["outcomeStatus"],
        )

    # 幂等发布派单审计事件，避免同一派单重复落盘。
    async def publish_dispatch_audit(
        self, dispatch_id: str, payload: dict[str, Any], context: RequestContext
    ) -> AuditPublishResult:
        async with self._audit_lock:
            if self._published_dispatches is None:
                self._published_dispatches = await asyncio.to_thread(self._load_audit_ids)
            if dispatch_id in self._published_dispatches:
                return AuditPublishResult(
                    status="already_published", dispatch_id=dispatch_id
                )
            event = {
                "timestamp": datetime.now(UTC).isoformat(),
                "dispatchId": dispatch_id,
                "traceId": context.trace_id,
                "eventId": context.event_id,
                "tenantId": context.tenant_id,
                "payload": payload,
            }
            await asyncio.to_thread(self._append_audit, event)
            self._published_dispatches.add(dispatch_id)
            return AuditPublishResult(status="published", dispatch_id=dispatch_id)

    # 将 Java Worker 载荷映射为领域 WorkerSnapshot。
    def _worker(self, payload: dict[str, Any]) -> WorkerSnapshot:
        self._check_contract(payload)
        return WorkerSnapshot(
            worker_id=payload["workerId"],
            tenant_id=payload["tenantId"],
            region=payload["region"],
            # Java 的 skills 仅表示资格，不表示熟练度；1.0 代表“具备该技能”。
            skills={skill: 1.0 for skill in payload["skills"]},
            shift_active=payload["shiftStatus"] == "ON_DUTY",
            available=payload["available"],
            current_load=payload["currentLoad"],
            capacity=payload["capacity"],
            distance_km=None,
            sla_readiness=None,
            captured_at=payload["snapshotAt"],
        )

    # 统一执行 HTTP 请求，将网络/服务端错误映射为领域异常。
    async def _request(
        self,
        method: str,
        path: str,
        *,
        trace_id: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        accept_business_error: bool = False,
    ) -> dict[str, Any]:
        request_headers = {"X-Trace-Id": trace_id, **(headers or {})}
        try:
            response = await self.client.request(
                method, path, headers=request_headers, json=json
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise DependencyUnavailableError(f"Java dispatch unavailable: {exc}") from exc
        if response.status_code >= 500:
            raise DependencyUnavailableError(
                f"Java dispatch returned HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ToolContractError("Java dispatch returned non-JSON response") from exc
        if response.is_error and not accept_business_error:
            raise ToolContractError(
                f"Java dispatch HTTP {response.status_code}: "
                f"{payload.get('reasonCode', 'UNKNOWN')}"
            )
        return payload

    # 校验响应中的合同版本，不匹配则抛出合同错误。
    @staticmethod
    def _check_contract(payload: dict[str, Any]) -> None:
        if payload.get("contractVersion") != CONTRACT_VERSION:
            raise ToolContractError("unsupported Java dispatch contractVersion")

    # 从审计日志文件加载已发布的派单 ID 集合。
    def _load_audit_ids(self) -> set[str]:
        if not self.audit_path.exists():
            return set()
        result: set[str] = set()
        for line in self.audit_path.read_text(encoding="utf-8").splitlines():
            try:
                dispatch_id = json.loads(line).get("dispatchId")
            except json.JSONDecodeError:
                continue
            if dispatch_id:
                result.add(dispatch_id)
        return result

    # 将一条审计事件以 JSON 行追加写入日志文件。
    def _append_audit(self, event: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
