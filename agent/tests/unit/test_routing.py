from flowfix_agent.routing import RequestRouter, RouteType
from flowfix_agent.routing.models import ExtractedEntities, RouteDecision


class FakeClassifier:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls = 0

    async def classify(self, text, *, trace_id, thread_id=None):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result.model_copy(update={"trace_id": trace_id, "thread_id": thread_id})


def test_router_distinguishes_three_chains_and_clarification():
    router = RequestRouter()

    assert router.route("手册里如何操作？").route_type is RouteType.KNOWLEDGE_QA
    assert router.route("把工单 WO-1 派给维修员").route_type is RouteType.DIRECT_DISPATCH
    assert (
        router.route("调查设备 DEV-7 的停机根因").route_type
        is RouteType.INCIDENT_INVESTIGATION
    )
    dispatch_without_order = router.route("帮我派单")
    assert dispatch_without_order.route_type is RouteType.DIRECT_DISPATCH
    assert dispatch_without_order.missing_fields == []


def test_router_only_classifies_incident_intent_without_validating_device():
    result = RequestRouter().route("为什么停机？", thread_id="thread-1")

    assert result.route_type is RouteType.INCIDENT_INVESTIGATION
    assert result.thread_id == "thread-1"
    assert result.missing_fields == []


def test_incident_with_dispatch_proposal_stays_on_investigation_chain():
    result = RequestRouter().route("调查设备 DEV-9 的故障，必要时给出派单建议")

    assert result.route_type is RouteType.INCIDENT_INVESTIGATION
    assert result.reason_code == "INCIDENT_WITH_DISPATCH_PROPOSAL"
    assert result.extracted_entities.device_id == "DEV-9"


def test_router_clarifies_only_when_intent_is_unclear():
    result = RequestRouter().route("帮我处理一下", thread_id="thread-1")

    assert result.route_type is RouteType.NEEDS_CLARIFICATION
    assert result.missing_fields == ["intent"]


async def test_llm_classifier_is_only_used_for_unclear_intent():
    classifier = FakeClassifier(
        RouteDecision(
            route_type=RouteType.KNOWLEDGE_QA,
            confidence=0.8,
            reason_code="LLM_KNOWLEDGE",
            extracted_entities=ExtractedEntities(),
            trace_id="placeholder",
        )
    )
    router = RequestRouter(classifier)

    deterministic = await router.route_async("如何操作？")
    fallback = await router.route_async("帮我看看这个")

    assert deterministic.reason_code == "KNOWLEDGE_QUESTION"
    assert fallback.route_type is RouteType.KNOWLEDGE_QA
    assert classifier.calls == 1


async def test_llm_classifier_failure_degrades_to_clarification():
    result = await RequestRouter(FakeClassifier(error=TimeoutError())).route_async(
        "帮我看看这个"
    )

    assert result.route_type is RouteType.NEEDS_CLARIFICATION
    assert result.reason_code == "LLM_FALLBACK_UNAVAILABLE"
