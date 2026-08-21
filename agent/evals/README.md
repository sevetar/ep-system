# Evals

保存固定评测集、实验配置和可复现报告。当前已有 50 条分层 Retrieval/QA、50 条 Router、M3 派单、M4 Runtime、Planning Golden 和 Single-Agent vs Multi-Agent 公平对照；知识闭环 K01～K10 由真实组件测试包执行。FAQ 多轮、Tool Selection 和 Planning MVP 数据仍没有独立 runner。

```bash
uv run flowfix-agent evaluate --with-qa --output evals/reports/l2-evaluation.json
uv run flowfix-agent evaluate-dispatch --dataset evals/datasets/dispatch_m3.jsonl
LANGGRAPH_STRICT_MSGPACK=true uv run flowfix-agent evaluate-runtime
```

新对照必须使用相同 Tool、Provider、模型、上下文和总预算。报告分别记录数据集、Prompt、模型、Capability Contract 和代码版本；合成指标不能表述为生产指标。

目标指标包括 Router Accuracy/Macro-F1/危险误路由、Conversation 隔离与压缩、Tool 选择/参数、Task Success、Plan Valid、Replan、Evidence Coverage、安全违规、P95 和 Token。数据集规模、切片和边界见 [datasets/README.md](datasets/README.md)。
