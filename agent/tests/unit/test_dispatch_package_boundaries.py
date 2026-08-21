import ast
from pathlib import Path

DISPATCH_ROOT = Path("src/flowfix_agent/dispatch")
FORBIDDEN_IMPORTS = {
    "domain": (
        "flowfix_agent.dispatch.application",
        "flowfix_agent.dispatch.skills",
        "flowfix_agent.dispatch.runtime",
        "flowfix_agent.dispatch.adapters",
        "langgraph",
    ),
    "skills": (
        "flowfix_agent.dispatch.application",
        "flowfix_agent.dispatch.runtime",
        "flowfix_agent.dispatch.adapters",
        "langgraph",
    ),
    "application": (
        "flowfix_agent.dispatch.runtime",
        "flowfix_agent.dispatch.adapters",
        "langgraph",
    ),
    "runtime": ("flowfix_agent.dispatch.adapters",),
}


# 验证 Dispatch 根包不再保留重构前混合分层的模块文件。
def test_dispatch_root_contains_no_mixed_layer_modules() -> None:
    assert {path.name for path in DISPATCH_ROOT.glob("*.py")} == {"__init__.py"}


# 验证 Dispatch 各分层导入方向遵守向内依赖规则。
def test_dispatch_dependencies_point_inward() -> None:
    violations: list[str] = []
    for layer, forbidden_prefixes in FORBIDDEN_IMPORTS.items():
        for path in sorted((DISPATCH_ROOT / layer).glob("*.py")):
            for imported in _imports(path):
                if imported.startswith(forbidden_prefixes):
                    violations.append(
                        f"{path.relative_to(DISPATCH_ROOT)} imports {imported}"
                    )
    assert violations == []


# 使用 AST 提取文件中的 import 和 from import 模块路径。
def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return imported
