import pytest

from flowfix_agent.core.errors import KnowledgeSourceError
from flowfix_agent.knowledge.markdown import MarkdownKnowledgeLoader


# 验证相同文档切分出的分块标识稳定且保留标题层级。
def test_chunk_ids_are_stable_and_preserve_heading(tmp_path):
    path = tmp_path / "guide.md"
    path.write_text("# 平台指南\n\n## 报修\n\n用户创建报修工单。" * 4, encoding="utf-8")
    loader = MarkdownKnowledgeLoader(tmp_path, chunk_size=200, chunk_overlap=20)

    first_snapshot = loader.snapshot(path)
    first = loader.chunk(first_snapshot)
    second = loader.chunk(loader.snapshot(path))

    assert [item.chunk_id for item in first] == [item.chunk_id for item in second]
    assert all(item.source_id == "guide.md" for item in first)
    assert any("报修" in item.section_path for item in first)


# 验证源内容变化后生成新的版本号和分块标识。
def test_changed_source_produces_new_version_and_ids(tmp_path):
    path = tmp_path / "guide.md"
    path.write_text("# 指南\n\n旧内容", encoding="utf-8")
    loader = MarkdownKnowledgeLoader(tmp_path, chunk_size=200, chunk_overlap=20)
    old_snapshot = loader.snapshot(path)
    old_ids = [item.chunk_id for item in loader.chunk(old_snapshot)]
    path.write_text("# 指南\n\n新内容", encoding="utf-8")

    new_snapshot = loader.snapshot(path)
    new_ids = [item.chunk_id for item in loader.chunk(new_snapshot)]

    assert old_snapshot.version != new_snapshot.version
    assert old_ids != new_ids


# 验证知识文件发现过程会拒绝逃逸根目录的路径。
def test_discovery_rejects_path_escape(tmp_path):
    loader = MarkdownKnowledgeLoader(tmp_path, chunk_size=200, chunk_overlap=20)

    with pytest.raises(KnowledgeSourceError, match="escapes"):
        loader.discover(["../outside.md"])
