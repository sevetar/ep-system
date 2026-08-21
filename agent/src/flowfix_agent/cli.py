from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from flowfix_agent.bootstrap.container import build_container
from flowfix_agent.core.config import get_settings
from flowfix_agent.core.models import RequestScope
from flowfix_agent.evaluation.completion import (
    run_completion_evaluation,
    write_completion_report,
)
from flowfix_agent.evaluation.diagnosis import (
    run_diagnosis_evaluation,
    write_diagnosis_report,
)
from flowfix_agent.evaluation.dispatch import (
    run_dispatch_evaluation,
    write_dispatch_report,
)
from flowfix_agent.evaluation.fairness import (
    run_fairness_evaluation,
    write_fairness_report,
)
from flowfix_agent.evaluation.foundation import (
    evaluate_router,
    write_foundation_report,
)
from flowfix_agent.evaluation.golden import (
    run_golden_evaluation,
    write_golden_report,
)
from flowfix_agent.evaluation.impact_safety import (
    run_impact_safety_evaluation,
    write_impact_safety_report,
)
from flowfix_agent.evaluation.qa import run_l2_evaluation, write_report
from flowfix_agent.evaluation.replanning import (
    run_replanning_evaluation,
    write_replanning_report,
)
from flowfix_agent.evaluation.resource_planning import (
    run_resource_planning_evaluation,
    write_resource_planning_report,
)
from flowfix_agent.evaluation.runtime import (
    run_runtime_evaluation,
    write_runtime_report,
)
from flowfix_agent.knowledge.models import SourceType
from flowfix_agent.observability.replay import (
    _format_ts,
    build_replay_view,
    load_dispatch_audit,
    load_trace_events,
)
from flowfix_agent.retrieval.models import RetrievalMode, RetrievalOptions

app = typer.Typer(no_args_is_help=True, help="FlowFix Advanced RAG Agent")


# 在一次异步任务执行期间统一启动并关闭应用依赖容器。
async def _with_container(callback):
    container = build_container(get_settings())
    await container.start()
    try:
        return await callback(container)
    finally:
        await container.close()


# 从 Markdown 文件摄取并索引知识内容。
@app.command(help="摄取并索引 Markdown 知识源。")
def ingest(
    paths: Annotated[
        list[str] | None, typer.Argument(help="Paths relative to KNOWLEDGE_ROOT")
    ] = None,
    recreate_index: Annotated[
        bool, typer.Option(help="Recreate the Elasticsearch index")
    ] = False,
) -> None:
    # 在已启动的容器中执行知识摄取。
    async def run(container):
        return await container.ingestion.ingest(
            paths or ["."], SourceType.PLATFORM_DOC, recreate_index
        )

    report = asyncio.run(_with_container(run))
    typer.echo(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    if report.failed_sources:
        raise typer.Exit(code=1)


# 运行固定数据集上的 L2 检索与问答评测。
@app.command(help="运行固定数据集上的 L2 检索与问答评测。")
def evaluate(
    dataset: Annotated[
        Path, typer.Option(exists=True, readable=True)
    ] = Path("evals/datasets/flowfix_l2.jsonl"),
    output: Annotated[Path, typer.Option()] = Path("evals/reports/l2-evaluation.json"),
    with_qa: Annotated[bool, typer.Option(help="Also call the chat model")] = True,
) -> None:
    # 解析为绝对路径，供下方异步闭包安全捕获。
    resolved_dataset = dataset.resolve()

    # 在已启动的容器中执行离线评测。
    async def run(container):
        # 以容器为入参运行 L2 检索与问答评测；with_qa 控制是否额外调用 chat 模型。
        return await run_l2_evaluation(container, resolved_dataset, with_qa)

    # 由 _with_container 负责容器生命周期，同步等待评测报告返回。
    report = asyncio.run(_with_container(run))
    # 将评测报告 JSON 落盘到 output 路径（默认 evals/reports/l2-evaluation.json）。
    write_report(report, output)
    # 终端打印格式化报告，便于人工核对指标。
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


# 运行 M3 自动派单固定场景与 Skill 对照评测。
@app.command(help="运行 M3 自动派单固定场景与 Skill 对照评测。")
def evaluate_dispatch(
    dataset: Annotated[
        Path, typer.Option(exists=True, readable=True)
    ] = Path("evals/datasets/dispatch_m3.jsonl"),
    output: Annotated[Path, typer.Option()] = Path(
        "evals/reports/dispatch-m3-evaluation.json"
    ),
) -> None:
    builtin = Path("src/flowfix_agent/dispatch/skills/builtin")
    report = asyncio.run(run_dispatch_evaluation(dataset.resolve(), builtin.resolve()))
    write_dispatch_report(report, output)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["gate"]["passed"]:
        raise typer.Exit(code=1)


# 运行 M4 状态图、人工审批、工具防护和恢复场景评测。
@app.command(help="运行 M4 StateGraph、HITL、Tool Guard 与恢复固定场景评测。")
def evaluate_runtime(
    dataset: Annotated[
        Path, typer.Option(exists=True, readable=True)
    ] = Path("evals/datasets/dispatch_m4.jsonl"),
    output: Annotated[Path, typer.Option()] = Path(
        "evals/reports/dispatch-m4-runtime-evaluation.json"
    ),
) -> None:
    builtin = Path("src/flowfix_agent/dispatch/skills/builtin")
    report = asyncio.run(run_runtime_evaluation(dataset.resolve(), builtin.resolve()))
    write_runtime_report(report, output)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["gate"]["passed"]:
        raise typer.Exit(code=1)


# 运行 Diagnosis 真实只读 Worker 固定门禁。
@app.command(help="运行 Diagnosis 真实只读 Worker 固定门禁。")
def evaluate_diagnosis(
    dataset: Annotated[
        Path, typer.Option(exists=True, readable=True)
    ] = Path("evals/datasets/planning_diagnosis.jsonl"),
    output: Annotated[Path, typer.Option()] = Path(
        "evals/reports/planning-diagnosis-evaluation.json"
    ),
) -> None:
    report = asyncio.run(run_diagnosis_evaluation(dataset.resolve()))
    write_diagnosis_report(report, output)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["gate"]["passed"]:
        raise typer.Exit(code=1)


# 运行 ImpactSafety 真实只读 Worker 固定门禁。
@app.command(help="运行 ImpactSafety 真实只读 Worker 固定门禁。")
def evaluate_impact_safety(
    dataset: Annotated[
        Path, typer.Option(exists=True, readable=True)
    ] = Path("evals/datasets/planning_impact_safety.jsonl"),
    output: Annotated[Path, typer.Option()] = Path(
        "evals/reports/planning-impact-safety-evaluation.json"
    ),
) -> None:
    report = asyncio.run(run_impact_safety_evaluation(dataset.resolve()))
    write_impact_safety_report(report, output)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["gate"]["passed"]:
        raise typer.Exit(code=1)


# 运行 ResourcePlanning 真实只读 Worker 固定门禁。
@app.command(help="运行 ResourcePlanning 真实只读 Worker 固定门禁。")
def evaluate_resource_planning(
    dataset: Annotated[
        Path, typer.Option(exists=True, readable=True)
    ] = Path("evals/datasets/planning_resource_planning.jsonl"),
    output: Annotated[Path, typer.Option()] = Path(
        "evals/reports/planning-resource-planning-evaluation.json"
    ),
) -> None:
    report = asyncio.run(run_resource_planning_evaluation(dataset.resolve()))
    write_resource_planning_report(report, output)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["gate"]["passed"]:
        raise typer.Exit(code=1)


# 运行三类内容触发 Replan 固定门禁。
@app.command(help="运行三类内容触发 Replan 固定门禁。")
def evaluate_replanning(
    dataset: Annotated[
        Path, typer.Option(exists=True, readable=True)
    ] = Path("evals/datasets/planning_replanning.jsonl"),
    output: Annotated[Path, typer.Option()] = Path(
        "evals/reports/planning-replanning-evaluation.json"
    ),
) -> None:
    report = asyncio.run(run_replanning_evaluation(dataset.resolve()))
    write_replanning_report(report, output)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["gate"]["passed"]:
        raise typer.Exit(code=1)


# 运行完成门禁与只读派单建议固定门禁。
@app.command(help="运行完成门禁与只读派单建议固定门禁。")
def evaluate_completion(
    dataset: Annotated[
        Path, typer.Option(exists=True, readable=True)
    ] = Path("evals/datasets/planning_completion.jsonl"),
    output: Annotated[Path, typer.Option()] = Path(
        "evals/reports/planning-completion-evaluation.json"
    ),
) -> None:
    report = asyncio.run(run_completion_evaluation(dataset.resolve()))
    write_completion_report(report, output)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["gate"]["passed"]:
        raise typer.Exit(code=1)


# 运行 Golden Set 全场景门禁：成功/三类 Replan/安全失败/故障恢复。
@app.command(help="运行 Golden Set 全场景门禁：成功/三类 Replan/安全失败/故障恢复。")
def evaluate_golden(
    dataset: Annotated[
        Path, typer.Option(exists=True, readable=True)
    ] = Path("evals/datasets/planning_golden.jsonl"),
    output: Annotated[Path, typer.Option()] = Path(
        "evals/reports/planning-golden-evaluation.json"
    ),
) -> None:
    report = asyncio.run(run_golden_evaluation(dataset.resolve()))
    write_golden_report(report, output)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["gate"]["passed"]:
        raise typer.Exit(code=1)


# 运行单/多 Agent 公平评测与故障注入门禁。
@app.command(help="运行单/多 Agent 公平评测与故障注入门禁。")
def evaluate_fairness(
    dataset: Annotated[
        Path, typer.Option(exists=True, readable=True)
    ] = Path("evals/datasets/fairness_planning.jsonl"),
    output: Annotated[Path, typer.Option()] = Path(
        "evals/reports/planning-fairness-evaluation.json"
    ),
) -> None:
    report = asyncio.run(run_fairness_evaluation(dataset.resolve()))
    write_fairness_report(report, output)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["gate"]["passed"]:
        raise typer.Exit(code=1)


# 运行 Phase A Router 固定集并生成门禁报告。
@app.command(help="运行 Phase A Router 固定集并生成门禁报告。")
def evaluate_foundation(
    dataset: Annotated[
        Path, typer.Option(exists=True, readable=True)
    ] = Path("evals/datasets/router_phase_a.jsonl"),
    output: Annotated[Path, typer.Option()] = Path(
        "evals/reports/phase-a-foundation.json"
    ),
) -> None:
    # 在指定固定评测集上运行 Phase A Router 评测，返回含门禁结果的报告。
    report = evaluate_router(dataset.resolve())
    # 将报告 JSON 落盘到 output 路径（默认 evals/reports/phase-a-foundation.json）。
    write_foundation_report(report, output)
    # 终端打印格式化报告，便于人工核对各链路 P/R/F1 与混淆矩阵。
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    # 门禁未通过（准确率 < 1.0 或存在危险误派）则以非零码退出。
    if not report["gate"]["passed"]:
        raise typer.Exit(code=1)


# 执行一次完整的检索、生成、引用和校验流程。
@app.command(help="运行完整的检索、答案生成、引用和校验流程。")
def query(
    question: Annotated[str, typer.Argument(help="Question grounded in indexed knowledge")],
    mode: Annotated[RetrievalMode, typer.Option()] = RetrievalMode.HYBRID,
    rerank: Annotated[bool, typer.Option(help="Enable the configured reranker")] = True,
) -> None:
    # 在已启动的容器中发起受知识证据约束的问答。
    async def run(container):
        return await container.qa.run(
            question,
            RequestScope(),
            RetrievalOptions(mode=mode, rerank=rerank),
        )

    result = asyncio.run(_with_container(run))
    payload = {
        "trace_id": result.trace_id,
        "answer": result.answer,
        "refused": result.refused,
        "citations": [item.model_dump(mode="json") for item in result.citations],
        "validation": result.validation.model_dump(mode="json"),
        "retrieval": {
            "mode": result.retrieval.mode,
            "candidate_count": len(result.retrieval.candidates),
            "selected_count": len(result.evidence),
            "fallbacks": result.retrieval.fallbacks,
            "latency_ms": result.retrieval.latency_ms,
        },
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


# 回放 JSONL Trace 与派单审计日志，输出按链路分组的时间线与汇总。
@app.command(help="回放本地 JSONL Trace 与派单审计日志。")
def trace_replay(
    trace_path: Annotated[
        Path, typer.Option(help="Trace JSONL 路径，默认 .runtime/traces.jsonl")
    ] = Path(".runtime/traces.jsonl"),
    audit_path: Annotated[
        Path,
        typer.Option(help="派单审计 JSONL 路径，默认 .runtime/dispatch-audit.jsonl"),
    ] = Path(".runtime/dispatch-audit.jsonl"),
) -> None:
    events = load_trace_events(trace_path)
    view = build_replay_view(events)
    typer.echo(json.dumps(view, ensure_ascii=False, indent=2))
    audit = load_dispatch_audit(audit_path)
    if audit:
        typer.echo("\n=== 派单审计 ===")
        for record in audit:
            typer.echo(
                f"[{_format_ts(record['timestamp'])}] "
                f"{record['dispatch_id']} "
                f"runtime={record['runtime_status']} "
                f"outcome={record['decision_outcome']} "
                f"worker={record['selected_worker_id']} "
                f"receipt={record['assignment_receipt']} "
                f"reason={record['reason_code'] or '-'}"
            )


# 启动对外提供接口的 FastAPI 服务。
@app.command(help="启动 FlowFix Agent 的 FastAPI 服务。")
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8000,
    reload: Annotated[bool, typer.Option()] = False,
) -> None:
    import uvicorn

    uvicorn.run("flowfix_agent.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
