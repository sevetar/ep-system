from __future__ import annotations

import hashlib
from pathlib import Path

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from flowfix_agent.core.errors import KnowledgeSourceError
from flowfix_agent.knowledge.models import KnowledgeChunk, SourceSnapshot, SourceType

HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4")]


# 负责发现 Markdown 文件、生成版本快照并切分稳定知识块。
class MarkdownKnowledgeLoader:
    # 初始化知识根目录以及标题和递归文本分割器。
    def __init__(self, root: Path, chunk_size: int, chunk_overlap: int) -> None:
        self.root = root.resolve()
        self.header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=HEADERS,
            strip_headers=False,
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "；", ". ", " ", ""],
            length_function=len,
        )

    # 在知识根目录内发现并返回符合要求的 Markdown 文件。
    def discover(self, requested_paths: list[str]) -> list[Path]:
        discovered: set[Path] = set()
        for requested in requested_paths:
            candidate = (self.root / requested).resolve()
            if not candidate.is_relative_to(self.root):
                raise KnowledgeSourceError(f"Path escapes KNOWLEDGE_ROOT: {requested}")
            if not candidate.exists():
                raise KnowledgeSourceError(f"Knowledge path does not exist: {requested}")
            if candidate.is_file():
                if candidate.suffix.lower() != ".md":
                    raise KnowledgeSourceError(f"Only Markdown is supported: {requested}")
                discovered.add(candidate)
            else:
                discovered.update(path.resolve() for path in candidate.rglob("*.md"))
        return sorted(discovered)

    # 读取单个知识文件并生成带内容哈希和版本号的不可变快照。
    def snapshot(
        self,
        path: Path,
        source_type: SourceType = SourceType.PLATFORM_DOC,
        tenant_id: str = "public",
        visibility: str = "public",
    ) -> SourceSnapshot:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise KnowledgeSourceError(f"Knowledge file must stay under {self.root}: {path}")
        try:
            content = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise KnowledgeSourceError(f"Cannot read knowledge source: {resolved}") from exc
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        source_id = resolved.relative_to(self.root).as_posix()
        return SourceSnapshot(
            source_id=source_id,
            source_type=source_type,
            path=str(resolved),
            content=content,
            content_hash=content_hash,
            version=content_hash[:16],
            tenant_id=tenant_id,
            visibility=visibility,
        )

    # 按标题层级和字符窗口把知识快照切分为稳定可索引的分块。
    def chunk(self, snapshot: SourceSnapshot) -> list[KnowledgeChunk]:
        header_documents = self.header_splitter.split_text(snapshot.content)
        documents = self.text_splitter.split_documents(header_documents)
        title = self._title(snapshot.content, Path(snapshot.path).stem)
        chunks: list[KnowledgeChunk] = []
        for position, document in enumerate(documents):
            content = document.page_content.strip()
            if not content:
                continue
            section_path = " / ".join(
                str(document.metadata[key])
                for key in ("h1", "h2", "h3", "h4")
                if document.metadata.get(key)
            )
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            stable_value = (
                f"{snapshot.source_id}\0{snapshot.version}\0{section_path}\0{position}\0{content_hash}"
            )
            chunk_id = hashlib.sha256(stable_value.encode()).hexdigest()[:32]
            chunks.append(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    source_id=snapshot.source_id,
                    source_type=snapshot.source_type,
                    source_version=snapshot.version,
                    knowledge_key=snapshot.knowledge_key,
                    tenant_id=snapshot.tenant_id,
                    visibility=snapshot.visibility,
                    title=title,
                    section_path=section_path,
                    content=content,
                    content_hash=content_hash,
                    position=position,
                    metadata=document.metadata,
                    embedding=[],
                )
            )
        if not chunks:
            raise KnowledgeSourceError(f"No chunks produced for {snapshot.source_id}")
        return chunks

    # 提取 Markdown 一级标题，缺失时使用文件名作为标题。
    @staticmethod
    def _title(content: str, fallback: str) -> str:
        for line in content.splitlines():
            if line.startswith("# "):
                return line.removeprefix("# ").strip()
        return fallback
