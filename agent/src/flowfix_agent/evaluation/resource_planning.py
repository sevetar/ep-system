from __future__ import annotations

import platform
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from flowfix_agent.evaluation.common import (
    boolean_rate,
    load_jsonl_dataset,
    write_json_report,
)
from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.memory.task_artifact import SQLiteTaskArtifactStore
from flowfix_agent.planning.controller import PlanController
from flowfix_agent.planning.models import IncidentContext, PlanDraft, TaskSpec
from flowfix_agent.planning.registry import WorkerRegistry
from flowfix_agent.planning.runtime import PlanningRuntime
from flowfix_agent.planning.validation import PlanValidator
from flowfix_agent.planning.workers.resource_planning import (
    ResourceAlternative,
    ResourceCandidate,
    ResourceConflict,
    ResourcePlanningResult,
    ResourcePlanningWorker,
)
from flowfix_agent.retrieval.models import (
    Evidence,
    EvidenceBundle,
    RetrievalMode,
)
from flowfix_agent.tools import ToolGateway, ToolRegistry, ToolResolver
from flowfix_agent.tools.models import ToolContext
from flowfix_agent.tools.providers import (
    RetrievalCapabilityClient,
    RetrievalToolProvider,
    knowledge_search_spec,
)


# 描述一条固定知识证据，门禁内以确定性方式返回。
class CannedEvidenceItem(BaseModel):
    chunk_id: str
    title: str = ""
    section_path: str | None = None
    content: str


# 表示一条 ResourcePlanning 评测用例：目标、成功标准与固定证据表。
class ResourcePlanningEvaluationCase(BaseModel):
    case_id: str
    goal: str
    success_criteria: list[str] = Field(default_factory=list)
    max_queries: int = Field(default=3, ge=1, le=10)
    expect_primary_available: bool = True
    expected_min_candidates: int = Field(default=1, ge=0)
    evidence: dict[str, list[CannedEvidenceItem]] = Field(default_factory=dict)


# 确定性检索：按关键词返回固定证据，未知查询返回空包，不访问 ES。
class CannedRetrieval:
    def __init__(self, table: dict[str, list[Evidence]]) -> None:
        self.table = table

    # 命中首个关键词即返回对应证据，未命中返回空证据包。
    async def retrieve(self, query, scope, options, trace_id=None):
        matched: list[Evidence] = []
        for keyword, evidence in self.table.items():
            if keyword in query:
                matched = evidence
                break
        return EvidenceBundle(
            trace_id=trace_id or "canned",
            original_query=query,
            retrieval_query=query,
            mode=RetrievalMode.HYBRID,
            scope=scope,
            candidates=[],
            selected_evidence=matched,
            budget_used=0,
            sufficient=bool(matched),
            latency_ms=0.0,
        )


# 记录每次工具调用上下文，供只读链路断言使用。
class CapturingRetrievalProvider(RetrievalToolProvider):
    def __init__(self, retrieval) -> None:
        super().__init__(retrieval)
        self.contexts: list[ToolContext] = []

    # 记录上下文后交给父类执行真实调用。
    async def invoke(self, capability, arguments, context):
        self.contexts.append(context)
        return await super().invoke(capability, arguments, context)


# 确定性生成器：按期望可用性返回引用首个证据的合法资源规划结果。
class DeterministicResourcePlanningGenerator:
    model = "deterministic"

    # 配置主资源可用性与候选数量。
    def __init__(self, primary_available: bool, candidates: int = 1) -> None:
        self.primary_available = primary_available
        self.candidates = candidates

    # 引用重排后的首个证据编号，产出候选、冲突与替代方案。
    async def generate(self, incident, task, evidence):
        first = evidence[0].citation_id
        return ResourcePlanningResult(
            primary_available=self.primary_available,
            confidence=0.8,
            candidates=[
                ResourceCandidate(
                    candidate_id=f"c{i}",
                    kind="spare_part",
                    name=f"备件 {i}",
                    description="仓库现有可用备件。",
                    available=self.primary_available,
                    supporting_evidence=[first],
                )
                for i in range(1, self.candidates + 1)
            ],
            conflicts=(
                [
                    ResourceConflict(
                        conflict_id="cf1",
                        resource_id="r1",
                        reason="关键备件库存不足，无法满足处置需求。",
                        supporting_evidence=[first],
                    )
                ]
                if not self.primary_available
                else []
            ),
            alternatives=(
                [
                    ResourceAlternative(
                        alternative_id="a1",
                        resource_id="r1",
                        alternative_name="同型号替代备件",
                        description="可从邻近仓库调拨同型号备件。",
                        supporting_evidence=[first],
                    )
                ]
                if not self.primary_available
                else []
            ),
            missing_info=["备件到货时间"],
        )


# 固定 Planner：每个事故只产出一条 resource_planning 任务。
class FakeResourcePlanningPlanner:
    # 根据事故目标生成资源规划任务草稿。
    async def plan(self, incident):
        return PlanDraft(
            plan_id=f"plan-{incident.incident_id}",
            tasks=[
                TaskSpec(
                    task_id="resource",
                    description=incident.goal,
                    required_role="resource_planning",
                    allowed_capabilities={"knowledge.search"},
                )
            ],
        )


# 使用通用 JSONL 加载器读取 ResourcePlanning 评测数据集。
def load_resource_planning_dataset(path: Path) -> list[ResourcePlanningEvaluationCase]:
    return load_jsonl_dataset(path, ResourcePlanningEvaluationCase, "resource_planning")


# 在固定数据集上运行 ResourcePlanning Worker 并汇总质量门禁指标。
async def run_resource_planning_evaluation(dataset_path: Path) -> dict:
    """只使用固定证据与确定性生成器，不访问真实模型或 ES。"""
    cases = load_resource_planning_dataset(dataset_path)
    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="flowfix-resource-eval-") as temp_dir:
        for case in cases:
            rows.append(await _run_case(case, Path(temp_dir)))
    passed = sum(row["passed"] for row in rows)
    item_sourced_rate = boolean_rate(rows, "items_sourced")
    citation_valid_rate = boolean_rate(rows, "citations_valid")
    read_only_preserved = all(row["read_only_preserved"] for row in rows)
    no_reservation_preserved = all(row["no_reservation"] for row in rows)
    query_budget_respected = all(row["query_budget_respected"] for row in rows)
    artifact_persisted = all(row["artifact_persisted"] for row in rows)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "milestone": "D14",
        "dataset": str(dataset_path),
        "runtime": {"python": platform.python_version(), "external_services_used": []},
        "metrics": {
            "total": len(rows),
            "passed": passed,
            "scenario_pass_rate": round(passed / len(rows), 4),
            "item_sourced_rate": item_sourced_rate,
            "citation_valid_rate": citation_valid_rate,
        },
        "gate": {
            "passed": (
                passed == len(rows)
                and item_sourced_rate == 1.0
                and citation_valid_rate == 1.0
                and read_only_preserved
                and no_reservation_preserved
                and query_budget_respected
                and artifact_persisted
            ),
            "criteria": {
                "scenario_pass_rate": 1.0,
                "item_sourced_rate": 1.0,
                "citation_valid_rate": 1.0,
                "read_only_preserved": True,
                "no_reservation_preserved": True,
                "query_budget_respected": True,
                "artifact_persisted": True,
            },
        },
        "cases": rows,
    }


# 运行单个评测用例：装配真实网关与 Worker，在 PlanningRuntime 中执行。
async def _run_case(case: ResourcePlanningEvaluationCase, temp_dir: Path) -> dict:
    store = SQLiteTaskArtifactStore(temp_dir / f"{case.case_id}.db")
    provider = CapturingRetrievalProvider(CannedRetrieval(_build_table(case.evidence)))
    registry = ToolRegistry()
    registry.register(knowledge_search_spec(), provider)
    generator = DeterministicResourcePlanningGenerator(
        primary_available=case.expect_primary_available,
        candidates=case.expected_min_candidates,
    )
    worker = ResourcePlanningWorker(
        RetrievalCapabilityClient(ToolGateway(ToolResolver(registry))),
        generator,
        max_queries=case.max_queries,
    )
    workers = WorkerRegistry()
    workers.register("resource_planning", worker)
    runtime = PlanningRuntime(
        FakeResourcePlanningPlanner(),
        PlanController(store, PlanValidator()),
        workers,
        store,
    )
    incident = IncidentContext(
        incident_id=case.case_id,
        tenant_id="tenant-eval",
        thread_id=f"thread-{case.case_id}",
        goal=case.goal,
        trace_id=f"eval-{case.case_id}",
        success_criteria=case.success_criteria,
    )
    result = await runtime.run(incident)
    return _evaluate_result(case, result, provider, store)


# 汇总单个用例的断言并计算是否通过。
def _evaluate_result(case, result, provider, store) -> dict:
    artifact = next(
        (item for item in result.artifacts if item.worker_id == "resource_planning"),
        None,
    )
    planning = (
        ResourcePlanningResult.model_validate(artifact.payload["resource_planning"])
        if artifact is not None
        else None
    )
    items = (
        [
            *planning.candidates,
            *planning.conflicts,
            *planning.alternatives,
        ]
        if planning
        else []
    )
    allowed_ids = {
        item["citation_id"] for item in (artifact.payload["evidence"] if artifact else [])
    }
    cited = {citation_id for item in items for citation_id in item.supporting_evidence}
    items_sourced = all(bool(item.supporting_evidence) for item in items)
    citations_valid = cited <= allowed_ids
    availability_matched = (
        planning is not None
        and planning.primary_available == case.expect_primary_available
    )
    candidates_covered = (
        len(planning.candidates) >= case.expected_min_candidates if planning else False
    )
    confidence_valid = planning is not None and 0 <= planning.confidence <= 1
    missing_info_present = bool(artifact and artifact.payload.get("missing_info"))
    # 只产出规划制品、不做任何资源预留/写入：上下文必须是 investigation 只读，
    # 且不得出现任何写能力调用。
    read_only_preserved = bool(provider.contexts) and all(
        context.chain == "investigation"
        and context.role == "resource-planning-worker"
        and context.permissions == {"tool:read"}
        for context in provider.contexts
    )
    no_reservation = all(
        "create" not in str(context.allowed_capabilities).lower()
        and "reserve" not in str(context.allowed_capabilities).lower()
        and "assignment" not in str(context.allowed_capabilities).lower()
        for context in provider.contexts
    )
    query_budget_respected = len(provider.contexts) <= case.max_queries
    persisted = store.list_plan(
        "tenant-eval", f"thread-{case.case_id}", f"plan-{case.case_id}"
    )
    artifact_persisted = any(record.kind == "artifact" for record in persisted)
    passed = (
        result.status == "completed"
        and availability_matched
        and candidates_covered
        and items_sourced
        and citations_valid
        and confidence_valid
        and missing_info_present
        and read_only_preserved
        and no_reservation
        and query_budget_respected
        and artifact_persisted
    )
    return {
        "case_id": case.case_id,
        "status": result.status,
        "primary_available": planning.primary_available if planning else False,
        "candidates": len(planning.candidates) if planning else 0,
        "items_sourced": items_sourced,
        "citations_valid": citations_valid,
        "availability_matched": availability_matched,
        "read_only_preserved": read_only_preserved,
        "no_reservation": no_reservation,
        "query_budget_respected": query_budget_respected,
        "retrieval_calls": len(provider.contexts),
        "artifact_persisted": artifact_persisted,
        "passed": passed,
    }


# 将数据集证据表转换为固定关键词到证据列表的映射。
def _build_table(
    raw: dict[str, list[CannedEvidenceItem]],
) -> dict[str, list[Evidence]]:
    table: dict[str, list[Evidence]] = {}
    for keyword, items in raw.items():
        table[keyword] = [
            Evidence(
                citation_id=1,
                chunk_id=item.chunk_id,
                source_id=item.chunk_id,
                source_type=SourceType.PLATFORM_DOC,
                source_version="1.0.0",
                title=item.title,
                section_path=item.section_path or "",
                content=item.content,
                score=0.9,
                estimated_tokens=len(item.content),
            )
            for item in items
        ]
    return table


# 使用通用报告写入器保存 ResourcePlanning 评测结果。
def write_resource_planning_report(report: dict, path: Path) -> None:
    write_json_report(report, path)
