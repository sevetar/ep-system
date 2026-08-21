#!/usr/bin/env bash
# FlowFix Agent 一键演示脚本
#
# 覆盖三条链路与公共底座：知识检索/QA、确定性派单、调查规划门禁、Router、Trace 回放。
# 所有命令均可独立重跑；演示不是唯一证据，具体指标以 evals/reports/ 下最终报告为准。
#
# 用法:
#   bash scripts/demo.sh            # 完整演示（含真实模型 L2 QA，较慢）
#   bash scripts/demo.sh --quick    # 快速演示（跳过真实模型 L2 QA）
set -euo pipefail

cd "$(dirname "$0")/.."

QUICK=0
if [[ "${1:-}" == "--quick" ]]; then
    QUICK=1
    shift || true
fi

step() {
    echo ""
    echo "══════════════════════════════════════════════════════"
    echo "▶ $1"
    echo "══════════════════════════════════════════════════════"
}

# ── 0. 环境自检 ──────────────────────────────────────────────
step "0. 环境自检：lint 与单元测试"
uv run ruff check .
uv run pytest -q | tail -3

# ── 1. 公共底座：Router 固定集 ──────────────────────────────
step "1. Phase A Router 固定集（公共底座）"
uv run flowfix-agent evaluate-foundation

# ── 2. 链路一：知识检索 + QA ────────────────────────────────
step "2. 链路一：知识检索与 QA"
if [[ "$QUICK" -eq 1 ]]; then
    echo "（快速模式：跳过真实模型 L2 QA，只跑确定性检索门禁）"
else
    uv run flowfix-agent evaluate --with-qa
fi

# ── 3. 链路二：确定性派单 M3/M4 ─────────────────────────────
step "3. 链路二：确定性派单 M3 自动派单"
uv run flowfix-agent evaluate-dispatch

step "4. 链路二：M4 StateGraph / HITL / Tool Guard"
LANGGRAPH_STRICT_MSGPACK=true uv run flowfix-agent evaluate-runtime

# ── 4. 链路三：调查规划门禁 ─────────────────────────────────
step "5. 链路三：Diagnosis / ImpactSafety / ResourcePlanning"
uv run flowfix-agent evaluate-diagnosis
uv run flowfix-agent evaluate-impact-safety
uv run flowfix-agent evaluate-resource-planning

step "6. 链路三：三类内容触发 Replan 与完成门禁"
uv run flowfix-agent evaluate-replanning
uv run flowfix-agent evaluate-completion

step "7. 链路三：Golden Set 与单/多 Agent 公平评测"
uv run flowfix-agent evaluate-golden
uv run flowfix-agent evaluate-fairness

# ── 5. 观测：Trace 回放 ─────────────────────────────────────
step "8. 观测：Trace 回放"
uv run flowfix-agent trace-replay

echo ""
echo "══════════════════════════════════════════════════════"
echo "✅ 演示完成。详细报告见 evals/reports/。"
echo "══════════════════════════════════════════════════════"
