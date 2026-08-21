from __future__ import annotations

import json

from flowfix_agent.observability.replay import (
    build_replay_view,
    chain_of,
    load_dispatch_audit,
    load_trace_events,
    summarize,
)


# 构造一条最小 Trace 事件。
def _event(event_type: str, trace_id: str, ts: str, summary: str | None = None) -> dict:
    return {
        "timestamp": ts,
        "event_type": event_type,
        "trace_id": trace_id,
        "payload": {"summary": summary},
    }


def test_chain_of_event_mapping() -> None:
    assert chain_of(_event("qa.completed", "t1", "2026-08-06T08:00:00+00:00")) == "知识问答"
    assert chain_of(_event("dispatch.decision", "t2", "2026-08-06T08:00:01+00:00")) == "派单"
    assert chain_of(_event("unknown.event", "t3", "2026-08-06T08:00:02+00:00")) == "其他"


def test_load_trace_events_skips_empty_and_invalid_lines(tmp_path) -> None:
    path = tmp_path / "traces.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(_event("qa.completed", "t1", "2026-08-06T08:00:00+00:00")),
                "not-json",
                "",
                json.dumps(_event("retrieval.completed", "t2", "2026-08-06T08:00:01+00:00")),
            ]
        ),
        encoding="utf-8",
    )
    events = load_trace_events(path)
    assert len(events) == 2
    assert events[0]["event_type"] == "qa.completed"
    assert events[1]["trace_id"] == "t2"


def test_load_trace_events_missing_file(tmp_path) -> None:
    assert load_trace_events(tmp_path / "absent.jsonl") == []


def test_summarize_counts_by_chain() -> None:
    events = [
        _event("qa.completed", "t1", "2026-08-06T08:00:00+00:00"),
        _event("retrieval.completed", "t1", "2026-08-06T08:00:00+00:00"),
        _event("dispatch.decision", "t2", "2026-08-06T08:00:01+00:00"),
    ]
    summary = summarize(events)
    assert summary["知识问答"] == {"events": 1, "traces": 1}
    assert summary["派单"] == {"events": 1, "traces": 1}


def test_build_replay_view_groups_and_sorts() -> None:
    events = [
        _event("dispatch.decision", "t2", "2026-08-06T08:00:01+00:00", "决策完成"),
        _event("qa.completed", "t1", "2026-08-06T08:00:00+00:00", "回答完成"),
    ]
    view = build_replay_view(events)
    assert view["total_events"] == 2
    # 按链路分组且每组内按时间正序
    assert view["timeline"]["派单"][0]["summary"] == "决策完成"
    assert view["timeline"]["知识问答"][0]["summary"] == "回答完成"
    assert view["summary"]["派单"] == {"events": 1, "traces": 1}


def test_load_dispatch_audit_parses_payload(tmp_path) -> None:
    path = tmp_path / "dispatch-audit.jsonl"
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-08-06T08:46:47+00:00",
                "dispatchId": "integration-d20-20260806-04",
                "traceId": "trace-d20-04",
                "payload": {
                    "runtime_status": "verified",
                    "decision": {
                        "outcome": "assign",
                        "selected_worker_id": "91001",
                    },
                    "assignment_receipt": {
                        "status": "accepted",
                        "reason_code": None,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    records = load_dispatch_audit(path)
    assert len(records) == 1
    assert records[0]["runtime_status"] == "verified"
    assert records[0]["selected_worker_id"] == "91001"
    assert records[0]["assignment_receipt"] == "accepted"


def test_load_dispatch_audit_null_receipt(tmp_path) -> None:
    # 拒绝/失败派单的审计记录可能缺失 assignment_receipt 或为 null，不应崩溃。
    path = tmp_path / "dispatch-audit.jsonl"
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-08-06T08:44:10+00:00",
                "dispatchId": "integration-d20-20260806-02",
                "payload": {
                    "runtime_status": "failed",
                    "decision": None,
                    "assignment_receipt": None,
                },
            }
        ),
        encoding="utf-8",
    )
    records = load_dispatch_audit(path)
    assert len(records) == 1
    assert records[0]["runtime_status"] == "failed"
    assert records[0]["assignment_receipt"] is None
    assert records[0]["decision_outcome"] is None


def test_load_dispatch_audit_missing_file(tmp_path) -> None:
    assert load_dispatch_audit(tmp_path / "absent.jsonl") == []
