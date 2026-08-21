from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flowfix_agent.api.routes import router
from flowfix_agent.core.models import RequestScope
from flowfix_agent.qa.models import QAResult, ValidationResult
from flowfix_agent.retrieval.models import EvidenceBundle, RetrievalMode


class FakeQA:
    async def run(self, question, scope, options, **kwargs):
        return QAResult(
            trace_id="qa-api-trace",
            question=question,
            answer="派单成功后必须核验 Java 最终 outcome。",
            refused=False,
            citations=[],
            evidence=[],
            retrieval=EvidenceBundle(
                trace_id="qa-api-trace",
                original_query=question,
                retrieval_query=question,
                mode=RetrievalMode.HYBRID,
                scope=scope,
                candidates=[],
                selected_evidence=[],
                budget_used=0,
                sufficient=True,
                latency_ms=1,
            ),
            validation=ValidationResult(valid=True),
            generator_model="fake-model",
        )


def test_qa_api_serializes_workflow_result_without_500():
    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(qa=FakeQA())

    with TestClient(app) as client:
        response = client.post(
            "/v1/qa/query",
            headers={"X-Tenant-Id": "public"},
            json={
                "query": "Java 派单成功后如何核验？",
                "scope": RequestScope().model_dump(mode="json"),
                "options": {},
            },
        )

    assert response.status_code == 200
    assert response.json()["trace_id"] == "qa-api-trace"
    assert response.json()["answer"] == "派单成功后必须核验 Java 最终 outcome。"
