from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from jinja2 import ChoiceLoader, FileSystemLoader
from jinja2.nativetypes import NativeEnvironment

if TYPE_CHECKING:
    from src.execution.toolbox import ToolSchema

# Resolve prompts directory relative to project root
_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def _make_loader() -> FileSystemLoader:
    # Single loader at prompts root so templates can reference each other
    # with paths like "base/system.jinja", "macros/memory_ctx.jinja", etc.
    return FileSystemLoader(str(_PROMPTS_DIR))


_env = NativeEnvironment(
    loader=_make_loader(),
    enable_async=True,
    auto_reload=False,
)


async def render_graph(
    template_names: List[str],
    context: Dict[str, Any],
    memory_retriever: Optional[Callable] = None,
    agent_role: Optional[str] = None,
) -> str:
    """Render a list of templates in order, concatenate into system prompt.

    If memory_retriever and agent_role are provided, injects retrieved memories
    into the context before rendering.
    """
    if memory_retriever and agent_role:
        context.setdefault("memories", [])
        context["memories"] = await memory_retriever(
            context.get("query", ""), agent_role
        )

    parts: list[str] = []
    for name in template_names:
        tpl = _env.get_template(f"{name}.jinja")
        rendered = await tpl.render_async(**context)
        parts.append(rendered)
    return "\n\n".join(parts)


class PromptOS:
    """L5 Cognitive Assembly — stitches memory into reasoning context via Jinja2."""

    def __init__(
        self,
        tools: Optional[List[ToolSchema]] = None,
        user_permission_level: int = 2,
        wiki_store: Optional[Any] = None,
    ) -> None:
        if tools is None:
            from src.execution.toolbox import DEFAULT_TOOLS
            self.tools: List[ToolSchema] = DEFAULT_TOOLS
        else:
            self.tools = tools
        self.user_permission_level = user_permission_level
        self._wiki_store = wiki_store

    async def assemble(
        self,
        request: "AgentRequest",
        memory_data: Dict[str, Any],
        agent_id: str,
    ) -> str:
        template_map = {
            "BUDDY": ["base/system", "agents/buddy"],
            "KAIROS": ["base/system", "agents/kairos"],
            "ULTRAPLAN": ["base/system", "agents/ultraplan"],
            "LIBRARIAN": ["base/system", "agents/librarian"],
        }
        templates = template_map.get(agent_id, ["base/system", "agents/buddy"])
        context = {
            "memories": memory_data.get("memories", []),
            "wiki_pages": memory_data.get("wiki_pages", []),
            "query": request.input_text,
            "agent_id": agent_id,
            "agent_role": agent_id.lower(),
            "tools_list": self.tools,
            "user_permission_level": self.user_permission_level,
            "wiki_index": self._wiki_store.get_index() if self._wiki_store else memory_data.get("wiki_index", {}),
            "is_plan_execution": request.metadata.get("is_plan_execution", False) if request.metadata else False,
        }
        return await render_graph(templates, context)

    async def assemble_librarian(
        self,
        raw_content: str,
        category: str = "General",
        title: str = "Untitled",
    ) -> str:
        """Assemble the Librarian distillation prompt with raw doc content."""
        templates = ["base/system", "agents/librarian"]
        context = {
            "raw_content": raw_content,
            "category": category,
            "title": title,
            "agent_id": "LIBRARIAN",
            "agent_role": "librarian",
            "memories": [],
            "wiki_index": {},
            "tools_list": [],
            "user_permission_level": self.user_permission_level,
        }
        return await render_graph(templates, context)
