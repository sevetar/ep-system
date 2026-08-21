# Scripts

保存可重复执行的摄取、索引检查、检索回放、评测、开发启动、健康检查和文档校验脚本。脚本必须失败即退出、固定输入/版本、输出可追溯报告，不打印 Token、Conversation 敏感原文或 Secret；不能用脚本结果替代正式测试门禁。

## Documentation validation

```bash
uv run python scripts/check_docs.py
```

校验项目根目录与 `/docs` 下 Markdown 的本地链接和标题锚点；外部 URL 不会被访问。
