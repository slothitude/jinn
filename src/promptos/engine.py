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
        parts.append(str(rendered))
    return "\n\n".join(parts)


class PromptOS:
    """L5 Cognitive Assembly — stitches memory into reasoning context via Jinja2."""

    TEMPLATE_MAP: Dict[str, list[str]] = {
        "BUDDY": ["base/system", "agents/buddy"],
        "KAIROS": ["base/system", "agents/kairos"],
        "ULTRAPLAN": ["base/system", "agents/ultraplan"],
        "LIBRARIAN": ["base/system", "agents/librarian"],
        "ORCHESTRATOR": ["base/system", "agents/orchestrator"],
        "SUPERVISOR": ["base/system", "agents/supervisor"],
    }

    def __init__(
        self,
        tools: Optional[List[ToolSchema]] = None,
        user_permission_level: int = 2,
        wiki_store: Optional[Any] = None,
        crypt_store: Optional[Any] = None,
    ) -> None:
        if tools is None:
            from src.execution.toolbox import DEFAULT_TOOLS
            from src.execution.web_tools import WEB_TOOLS
            from src.execution.self_tools import SELF_TOOLS
            self.tools: List[ToolSchema] = DEFAULT_TOOLS + WEB_TOOLS + SELF_TOOLS
        else:
            self.tools = tools
        self.user_permission_level = user_permission_level
        self._wiki_store = wiki_store
        self._crypt_store = crypt_store

    def _build_context(
        self,
        agent_id: str,
        *,
        query: str = "",
        memories: Optional[list] = None,
        wiki_pages: Optional[list] = None,
        wiki_index: Optional[Dict] = None,
        raw_content: str = "",
        category: str = "General",
        title: str = "Untitled",
        is_plan_execution: bool = False,
        crypt_lessons: Optional[list] = None,
    ) -> Dict[str, Any]:
        """Shared context builder for all assemble methods."""
        from src.core.version import get_version, get_git_info
        git = get_git_info()
        return {
            "memories": memories or [],
            "wiki_pages": wiki_pages or [],
            "wiki_index": wiki_index or {},
            "query": query,
            "agent_id": agent_id,
            "agent_role": agent_id.lower(),
            "tools_list": self.tools,
            "user_permission_level": self.user_permission_level,
            "raw_content": raw_content,
            "category": category,
            "title": title,
            "is_plan_execution": is_plan_execution,
            "jinn_version": get_version(),
            "jinn_git_branch": git["branch"],
            "jinn_git_commit": git["commit"],
            "crypt_lessons": crypt_lessons or [],
        }

    async def assemble(
        self,
        request: "AgentRequest",
        memory_data: Dict[str, Any],
        agent_id: str,
    ) -> str:
        # Fetch crypt lessons — relevance-ranked, fallback to recent
        crypt_lessons = []
        if self._crypt_store:
            try:
                crypt_lessons = self._crypt_store.search_lessons(request.input_text, limit=10)
                if not crypt_lessons:
                    crypt_lessons = self._crypt_store.get_recent_lessons(limit=10)
            except Exception:
                crypt_lessons = []

        templates = self.TEMPLATE_MAP.get(agent_id, ["base/system", "agents/buddy"])
        context = self._build_context(
            agent_id,
            query=request.input_text,
            memories=memory_data.get("memories", []),
            wiki_pages=memory_data.get("wiki_pages", []),
            wiki_index=self._wiki_store.get_index() if self._wiki_store else memory_data.get("wiki_index", {}),
            is_plan_execution=request.metadata.get("is_plan_execution", False) if request.metadata else False,
            crypt_lessons=crypt_lessons,
        )
        return await render_graph(templates, context)

    async def assemble_librarian(
        self,
        raw_content: str,
        category: str = "General",
        title: str = "Untitled",
    ) -> str:
        """Assemble the Librarian distillation prompt with raw doc content."""
        templates = self.TEMPLATE_MAP["LIBRARIAN"]
        context = self._build_context(
            "LIBRARIAN",
            raw_content=raw_content,
            category=category,
            title=title,
        )
        # Librarian doesn't need tools — override with empty list
        context["tools_list"] = []
        return await render_graph(templates, context)
