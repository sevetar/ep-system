from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flowfix_agent.api.routes import router
from flowfix_agent.knowledge.models import (
    WorkOrderKnowledgeRecord,
    WorkOrderKnowledgeStatus,
)


class FakeWorkOrderKnowledgeService:
    def __init__(self) -> None:
        self.revocations = []

    async def get_status(self, event_id):
        if event_id == "missing":
            return None
        return WorkOrderKnowledgeRecord(
            event_id=event_id,
            tenant_id="tenant-a",
            work_order_id="88",
            work_order_version=2,
            source_id="work-order/tenant-a/88",
            source_version="v2-abc",
            content_hash="abc",
            status=WorkOrderKnowledgeStatus.INDEXED,
            quality_score=90,
            chunks=3,
            indexed_at=datetime.now(UTC),
        )

    async def revoke(self, tenant_id, work_order_id, reason):
        self.revocations.append((tenant_id, work_order_id, reason))
        return 3

    @staticmethod
    def source_id(tenant_id, work_order_id):
        return f"work-order/{tenant_id}/{work_order_id}"


def _client():
    app = FastAPI()
    app.include_router(router)
    service = FakeWorkOrderKnowledgeService()
    app.state.container = SimpleNamespace(
        settings=SimpleNamespace(app_env="test", api_auth_token=None),
        work_order_knowledge_ingestion=service,
    )
    return TestClient(app), service


def test_get_work_order_knowledge_status_is_tenant_scoped():
    client, _ = _client()
    with client:
        response = client.get(
            "/v1/knowledge/work-orders/events/event-88",
            headers={
                "X-Tenant-Id": "tenant-a",
                "X-Principal-Permissions": "knowledge:read",
            },
        )
        forbidden = client.get(
            "/v1/knowledge/work-orders/events/event-88",
            headers={
                "X-Tenant-Id": "tenant-b",
                "X-Principal-Permissions": "knowledge:read",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "indexed"
    assert forbidden.status_code == 403


def test_admin_can_revoke_work_order_knowledge():
    client, service = _client()
    with client:
        response = client.post(
            "/v1/knowledge/work-orders/88/revoke",
            headers={
                "X-Tenant-Id": "public",
                "X-Principal-Permissions": "knowledge:write,knowledge:admin",
            },
            json={"tenant_id": "tenant-a", "reason": "工单重新打开"},
        )

    assert response.status_code == 200
    assert response.json()["deleted_chunks"] == 3
    assert service.revocations == [("tenant-a", "88", "工单重新打开")]
