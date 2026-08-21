# Memory

`conversation` 保存 FAQ thread 范围的 Recent/Summary/Slots/Finalize；`task_artifact` 保存版本化 Plan/Task/Artifact/Patch。两者使用 SQLite 证明跨进程读取和 expected-version 冲突语义，不保存完整思维过程。
