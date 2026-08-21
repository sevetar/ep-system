from datetime import UTC, datetime, timedelta

import httpx

from flowfix_agent.dispatch.adapters.java_http import JavaDispatchHttpAdapter
from flowfix_agent.dispatch.runtime.models import (
    AssignmentCommand,
    AssignmentOutcomeStatus,
    AssignmentReceiptStatus,
    RequestContext,
)

NOW = "2026-08-05T10:00:00+08:00"


def context() -> RequestContext:
    return RequestContext(
        trace_id="trace-1",
        tenant_id="default",
        event_id="event-1",
        permissions=["dispatch:read", "dispatch:write", "dispatch:audit"],
        deadline=datetime.now(UTC) + timedelta(minutes=1),
    )


def make_adapter(handler, tmp_path):
    client = httpx.AsyncClient(
        base_url="http://java/internal/dispatch/v1",
        transport=httpx.MockTransport(handler),
    )
    return JavaDispatchHttpAdapter(client, tmp_path / "audit.jsonl"), client


async def test_maps_java_snapshots_without_inventing_metrics(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/snapshot"):
            return httpx.Response(
                200,
                json={
                    "contractVersion": "dispatch-contract/v1",
                    "orderId": "92003",
                    "tenantId": "default",
                    "deviceId": "93001",
                    "maintenanceType": "ELECTRICAL",
                    "requiredSkills": ["ELECTRICAL"],
                    "priority": "HIGH",
                    "region": "EAST",
                    "status": "PENDING_DISPATCH",
                    "assignedWorkerId": None,
                    "version": 0,
                    "snapshotAt": NOW,
                },
            )
        return httpx.Response(
            200,
            json={
                "contractVersion": "dispatch-contract/v1",
                "workers": [
                    {
                        "contractVersion": "dispatch-contract/v1",
                        "workerId": "91001",
                        "tenantId": "default",
                        "skills": ["ELECTRICAL"],
                        "region": "EAST",
                        "shiftStatus": "ON_DUTY",
                        "available": True,
                        "currentLoad": 0,
                        "capacity": 3,
                        "snapshotAt": NOW,
                    }
                ],
            },
        )

    adapter, client = make_adapter(handler, tmp_path)
    try:
        order = await adapter.get_work_order_snapshot("92003", context())
        workers = await adapter.list_eligible_workers(order, context())
    finally:
        await client.aclose()

    assert order.work_order_id == "92003"
    assert order.required_skills == ["electrical"]
    assert workers[0].skills == {"electrical": 1.0}
    assert workers[0].distance_km is None
    assert workers[0].sla_readiness is None


async def test_maps_assignment_receipt_and_dispatch_outcome(tmp_path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "contractVersion": "dispatch-contract/v1",
                    "receiptStatus": "ACCEPTED",
                    "reasonCode": None,
                    "orderId": "92003",
                    "workerId": "91001",
                    "expectedVersion": 0,
                    "observedVersion": 1,
                    "traceId": "trace-1",
                    "eventId": "event-1",
                    "dispatchId": "dispatch-1",
                    "idempotencyKey": "assignment:default:event-1:92003:v0",
                },
            )
        return httpx.Response(
            200,
            json={
                "contractVersion": "dispatch-contract/v1",
                "outcomeStatus": "ASSIGNED",
                "reasonCode": None,
                "orderId": "92003",
                "assignedWorkerId": "91001",
                "orderStatus": "ASSIGNED",
                "version": 1,
                "traceId": "trace-1",
                "eventId": "event-1",
                "dispatchId": "dispatch-1",
                "idempotencyKey": "assignment:default:event-1:92003:v0",
                "verifiedAt": NOW,
            },
        )

    adapter, client = make_adapter(handler, tmp_path)
    command = AssignmentCommand(
        tenant_id="default",
        event_id="event-1",
        dispatch_id="dispatch-1",
        work_order_id="92003",
        worker_id="91001",
        expected_version=0,
        idempotency_key="assignment:default:event-1:92003:v0",
    )
    try:
        receipt = await adapter.create_assignment(command, context())
        outcome = await adapter.get_assignment_outcome("dispatch-1", context())
    finally:
        await client.aclose()

    assert receipt.status == AssignmentReceiptStatus.ACCEPTED
    assert outcome.status == AssignmentOutcomeStatus.ASSIGNED
    assert seen[0].headers["idempotency-key"] == command.idempotency_key
    assert seen[1].url.path.endswith("/assignments/dispatch-1/outcome")
