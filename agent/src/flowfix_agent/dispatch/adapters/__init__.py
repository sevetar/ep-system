"""派单适配器：测试/离线阶段可替换的本地实现，以及生产用 Java HTTP 与提案桥接。"""

from flowfix_agent.dispatch.adapters.decision_repository import (
    InMemoryDispatchDecisionRepository,
)
from flowfix_agent.dispatch.adapters.fake_tools import FakeDispatchToolAdapter
from flowfix_agent.dispatch.adapters.mysql_decision_repository import (
    MySQLDispatchDecisionRepository,
)
from flowfix_agent.dispatch.adapters.skill_registry import FileDispatchSkillRegistry
from flowfix_agent.dispatch.adapters.sqlite_decision_repository import (
    SQLiteDispatchDecisionRepository,
)

__all__ = [
    "FakeDispatchToolAdapter",
    "FileDispatchSkillRegistry",
    "InMemoryDispatchDecisionRepository",
    "MySQLDispatchDecisionRepository",
    "SQLiteDispatchDecisionRepository",
]
