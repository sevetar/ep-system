from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from flowfix_agent.dispatch.domain.models import WorkOrderPriority

SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


# 调度策略版本的生命周期状态。
class SkillLifecycle(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


# 候选工作人员同分时使用的排序策略。
class TieBreakPolicy(StrEnum):
    LOWEST_LOAD_THEN_WORKER_ID = "lowest_load_then_worker_id"
    NEAREST_THEN_WORKER_ID = "nearest_then_worker_id"
    WORKER_ID = "worker_id"


# 定义策略可配置但只能收紧的人员资格条件。
class EligibilityRules(BaseModel):
    require_region_match: bool = True
    max_distance_km: float = Field(default=50.0, gt=0.0, le=1000.0)
    max_load_ratio: float = Field(default=1.0, gt=0.0, le=1.0)


# 定义候选评分各维度的归一化权重。
class ScoringWeights(BaseModel):
    distance: float = Field(ge=0.0, le=1.0)
    load: float = Field(ge=0.0, le=1.0)
    skill: float = Field(ge=0.0, le=1.0)
    sla: float = Field(ge=0.0, le=1.0)

    # 校验所有评分权重之和是否为 1。
    @model_validator(mode="after")
    def validate_sum(self) -> ScoringWeights:
        total = self.distance + self.load + self.skill + self.sla
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"scoring weights must sum to 1.0, got {total}")
        return self


# 定义自动分配与转人工之间的风险阈值。
class RiskThresholds(BaseModel):
    minimum_auto_score: float = Field(default=0.55, ge=0.0, le=1.0)
    minimum_score_margin: float = Field(default=0.02, ge=0.0, le=1.0)
    force_manual_priorities: list[WorkOrderPriority] = Field(default_factory=list)


# 声明策略获准使用的只读和写入工具。
class ToolPolicy(BaseModel):
    contract_version: str = "dispatch-tools/v1"
    allowed_read_tools: list[str] = Field(default_factory=list)
    allowed_write_tools: list[str] = Field(default_factory=list)

    # 清洗工具名称并去重排序，以保证配置稳定。
    @field_validator("allowed_read_tools", "allowed_write_tools")
    @classmethod
    def normalize_tools(cls, value: list[str]) -> list[str]:
        return sorted({item.strip() for item in value if item.strip()})


# 表示一个带版本、约束、评分规则和内容指纹的调度策略。
class DispatchSkill(BaseModel):
    skill_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    skill_version: str
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    status: SkillLifecycle = SkillLifecycle.DRAFT
    compatible_schema: str = "dispatch-state/v1"
    required_snapshot_fields: list[str] = Field(default_factory=list)
    eligibility_rules: EligibilityRules
    scoring_weights: ScoringWeights
    tie_break_policy: TieBreakPolicy
    risk_thresholds: RiskThresholds
    tool_policy: ToolPolicy = Field(default_factory=ToolPolicy)
    reason_templates: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    # 校验策略版本是否符合语义化版本格式。
    @field_validator("skill_version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if not SEMVER_PATTERN.fullmatch(value):
            raise ValueError("skill_version must use MAJOR.MINOR.PATCH")
        return value

    # 清洗、去重并排序策略依赖的快照字段。
    @field_validator("required_snapshot_fields")
    @classmethod
    def normalize_required_fields(cls, value: list[str]) -> list[str]:
        return sorted({item.strip() for item in value if item.strip()})

    # 校验已声明的内容指纹，或在缺省时自动填充。
    @model_validator(mode="after")
    def validate_or_fill_hash(self) -> DispatchSkill:
        computed = self.compute_content_hash()
        if self.content_hash and self.content_hash != computed:
            raise ValueError(
                f"skill content_hash mismatch: declared={self.content_hash}, computed={computed}"
            )
        self.content_hash = computed
        return self

    # 返回由策略标识和版本组成的唯一注册键。
    @property
    def key(self) -> str:
        return f"{self.skill_id}:{self.skill_version}"

    # 对不含生命周期状态的策略内容计算稳定短哈希。
    def compute_content_hash(self) -> str:
        payload = self.model_dump(
            mode="json",
            exclude={"content_hash", "status"},
        )
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode()).hexdigest()[:16]
