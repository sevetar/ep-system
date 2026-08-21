from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# Trace 事件类型归属的链路：用于回放时按链路分组汇总。
CHAIN_BY_EVENT: dict[str, str] = {
    "ingestion.source_indexed": "知识",
    "ingestion.source_failed": "知识",
    "ingestion.completed": "知识",
    "retrieval.completed": "知识检索",
    "qa.completed": "知识问答",
    "dispatch.decision": "派单",
}


# 从 Trace 文件解析全部事件并按时间戳排序，返回扁平事件列表。
def load_trace_events(trace_path: Path) -> list[dict[str, Any]]:
    if not trace_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    events.sort(key=lambda e: e.get("timestamp", ""))
    return events


# 将事件按键归属链路；未知事件类型归入“其他”。
def chain_of(event: dict[str, Any]) -> str:
    return CHAIN_BY_EVENT.get(event.get("event_type", ""), "其他")


# 汇总一次回放中各链路的事件数与去重 trace_id 数。
def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    per_chain: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "trace_ids": set()})
    for event in events:
        chain = chain_of(event)
        per_chain[chain]["count"] += 1
        trace_id = event.get("trace_id")
        if trace_id:
            per_chain[chain]["trace_ids"].add(trace_id)
    return {
        chain: {
            "events": stats["count"],
            "traces": len(stats["trace_ids"]),
        }
        for chain, stats in sorted(per_chain.items())
    }


# 生成按链路分组、按时间正序排列的回放视图，供 Trace 回放命令输出。
def build_replay_view(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_chain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_chain[chain_of(event)].append(event)
    timeline: dict[str, list[dict[str, Any]]] = {}
    for chain, chain_events in sorted(by_chain.items()):
        timeline[chain] = [
            {
                "timestamp": event.get("timestamp"),
                "event_type": event.get("event_type"),
                "trace_id": event.get("trace_id"),
                "summary": event.get("payload", {}).get("summary"),
            }
            for event in chain_events
        ]
    return {
        "total_events": len(events),
        "summary": summarize(events),
        "timeline": timeline,
    }


# 解析派单审计日志并输出按时间排序的审计记录列表。
def load_dispatch_audit(audit_path: Path) -> list[dict[str, Any]]:
    if not audit_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = record.get("payload", {})
        decision = payload.get("decision") or {}
        receipt = payload.get("assignment_receipt") or {}
        records.append(
            {
                "timestamp": record.get("timestamp"),
                "dispatch_id": record.get("dispatchId"),
                "trace_id": record.get("traceId"),
                "runtime_status": payload.get("runtime_status"),
                "decision_outcome": decision.get("outcome"),
                "selected_worker_id": decision.get("selected_worker_id"),
                "assignment_receipt": receipt.get("status"),
                "reason_code": receipt.get("reason_code"),
            }
        )
    records.sort(key=lambda r: r.get("timestamp") or "")
    return records


# 将时间戳字符串格式化为 HH:MM:SS 时刻显示，失败时原样返回。
def _format_ts(timestamp: str | None) -> str:
    if not timestamp:
        return ""
    try:
        return datetime.fromisoformat(timestamp).strftime("%H:%M:%S")
    except ValueError:
        return timestamp
