from __future__ import annotations

from pydantic import BaseModel, Field

from flowfix_agent.retrieval.models import Evidence, EvidenceBundle


# 描述答案中一个可追溯到知识分块的引用。
class Citation(BaseModel):
    citation_id: int
    source_id: str
    title: str
    section_path: str
    source_version: str
    chunk_id: str


# 记录答案引用校验、修复与错误信息。
class ValidationResult(BaseModel):
    valid: bool
    cited_ids: list[int] = Field(default_factory=list)
    repaired: bool = False
    errors: list[str] = Field(default_factory=list)


# 封装问答链路的答案、证据、检索结果与校验结果。
class QAResult(BaseModel):
    trace_id: str
    question: str
    answer: str
    refused: bool
    citations: list[Citation]
    evidence: list[Evidence]
    retrieval: EvidenceBundle
    validation: ValidationResult
    generator_model: str
    rewritten_question: str | None = None
    conversation_version: int | None = None
    conversation_finalized: bool = False
