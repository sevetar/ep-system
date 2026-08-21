from pathlib import Path

from flowfix_agent.adapters.catalog import FileKnowledgeCatalog
from flowfix_agent.knowledge.markdown import MarkdownKnowledgeLoader
from flowfix_agent.knowledge.service import KnowledgeIngestionService


# 模拟可切换成功或失败状态的向量生成器。
class ToggleEmbedding:
    dimensions = 2

    # 初始化为正常生成向量的状态。
    def __init__(self):
        self.fail = False

    # 根据开关返回固定向量或模拟模型服务异常。
    async def embed_documents(self, texts):
        if self.fail:
            raise RuntimeError("provider unavailable")
        return [[1.0, 0.0] for _ in texts]


# 模拟按知识版本统计写入数量的索引端口。
class FakeIndex:
    index_name = "test-index"

    # 初始化各知识版本的分块计数器。
    def __init__(self):
        self.counts = {}

    # 模拟确保索引存在且不执行外部操作。
    async def ensure_index(self, recreate=False):
        return None

    # 模拟写入分块并累计各知识版本数量。
    async def index_chunks(self, chunks):
        for chunk in chunks:
            self.counts[chunk.knowledge_key] = (
                self.counts.get(chunk.knowledge_key, 0) + 1
            )
        return len(chunks)

    # 返回指定知识版本已模拟写入的分块数量。
    async def count_knowledge_key(self, knowledge_key):
        return self.counts.get(knowledge_key, 0)


# 模拟无需持久化的追踪事件输出端口。
class FakeTrace:
    # 接收追踪事件但不执行任何外部写入。
    async def emit(self, event_type, trace_id, payload):
        return None


# 验证新版本摄取失败时目录仍保留上一成功激活版本。
async def test_failed_new_version_keeps_previous_active_catalog(tmp_path: Path):
    root = tmp_path / "knowledge"
    root.mkdir()
    source = root / "guide.md"
    source.write_text("# Guide\n\nold active content", encoding="utf-8")
    catalog = FileKnowledgeCatalog(tmp_path / "catalog.json")
    embedding = ToggleEmbedding()
    service = KnowledgeIngestionService(
        MarkdownKnowledgeLoader(root, chunk_size=200, chunk_overlap=20),
        embedding,
        FakeIndex(),
        catalog,
        FakeTrace(),
        embedding_batch_size=4,
    )

    first = await service.ingest(["guide.md"])
    active_before = await catalog.get("guide.md")
    source.write_text("# Guide\n\nnew content that fails", encoding="utf-8")
    embedding.fail = True

    second = await service.ingest(["guide.md"])
    active_after = await catalog.get("guide.md")

    assert first.failed_sources == 0
    assert second.failed_sources == 1
    assert active_before is not None
    assert active_after is not None
    assert active_after.active_version == active_before.active_version
    assert active_after.content_hash == active_before.content_hash


# 验证源文件未变化但索引投影缺失时仍会重新构建分块。
async def test_unchanged_source_rebuilds_missing_search_projection(tmp_path: Path):
    root = tmp_path / "knowledge"
    root.mkdir()
    source = root / "guide.md"
    source.write_text("# Guide\n\ncontent", encoding="utf-8")
    catalog = FileKnowledgeCatalog(tmp_path / "catalog.json")
    index = FakeIndex()
    service = KnowledgeIngestionService(
        MarkdownKnowledgeLoader(root, chunk_size=200, chunk_overlap=20),
        ToggleEmbedding(),
        index,
        catalog,
        FakeTrace(),
        embedding_batch_size=4,
    )

    first = await service.ingest(["guide.md"])
    index.counts.clear()
    second = await service.ingest(["guide.md"])

    assert first.indexed_chunks == 1
    assert second.indexed_chunks == 1
    assert second.skipped_sources == 0
