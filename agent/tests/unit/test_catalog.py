from flowfix_agent.adapters.catalog import FileKnowledgeCatalog
from flowfix_agent.knowledge.models import CatalogRecord, SourceType


# 验证目录激活新版本时会替换同一知识源的旧版本记录。
async def test_catalog_activates_and_replaces_source_version(tmp_path):
    catalog = FileKnowledgeCatalog(tmp_path / "catalog.json")
    first = CatalogRecord(
        source_id="guide.md",
        source_type=SourceType.PLATFORM_DOC,
        active_version="v1",
        knowledge_key="guide.md:v1",
        content_hash="hash-1",
        indexed_chunks=2,
        tenant_id="public",
        visibility="public",
    )
    second = first.model_copy(
        update={
            "active_version": "v2",
            "knowledge_key": "guide.md:v2",
            "content_hash": "hash-2",
        }
    )

    await catalog.activate(first)
    await catalog.activate(second)

    stored = await catalog.get("guide.md")
    assert stored is not None
    assert stored.active_version == "v2"
    assert len(await catalog.list_active()) == 1
