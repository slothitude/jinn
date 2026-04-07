"""Web tool schemas and adapter for web_eyes integration.

Provides 6 tools (search, crawl, summarize, ask, see, look) that wrap
the web_eyes controller. All imports are lazy — if web_eyes or its
dependencies aren't installed, tools return a clear error instead of crashing.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from src.execution.toolbox import ToolSchema

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

WEB_SEARCH_TOOL = ToolSchema(
    name="web_search",
    description="Search the web and return summarized results with sources.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "description": "Max results (default 5)"},
        },
        "required": ["query"],
    },
    cost_factor=2.5,
)

WEB_CRAWL_TOOL = ToolSchema(
    name="web_crawl",
    description="Crawl specific URLs and extract clean text content.",
    parameters={
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "URLs to crawl",
            },
        },
        "required": ["urls"],
    },
    cost_factor=2.0,
)

WEB_SUMMARIZE_TOOL = ToolSchema(
    name="web_summarize",
    description="Crawl URLs and summarize their content.",
    parameters={
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "URLs to summarize",
            },
            "instruction": {"type": "string", "description": "Custom summary instruction"},
        },
        "required": ["urls"],
    },
    cost_factor=2.5,
)

WEB_ASK_TOOL = ToolSchema(
    name="web_ask",
    description="Ask a question — searches web, crawls top results, synthesizes cited answer.",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Question to answer using web data"},
            "scrape_top": {"type": "integer", "description": "Number of results to crawl (default 3)"},
        },
        "required": ["question"],
    },
    cost_factor=3.0,
)

WEB_SEE_TOOL = ToolSchema(
    name="web_see",
    description="Screenshot web pages and use vision AI to extract content. Best for JS-heavy, canvas-rendered, or image-heavy pages.",
    parameters={
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "URLs to screenshot and analyze",
            },
            "instruction": {"type": "string", "description": "What to extract from the pages"},
            "extract_prompt": {"type": "string", "description": "Custom vision extraction prompt"},
        },
        "required": ["urls"],
    },
    cost_factor=3.5,
)

WEB_LOOK_TOOL = ToolSchema(
    name="web_look",
    description="Analyze a base64-encoded image with vision AI.",
    parameters={
        "type": "object",
        "properties": {
            "image_base64": {"type": "string", "description": "Base64-encoded image data"},
            "instruction": {"type": "string", "description": "What to analyze in the image"},
        },
        "required": ["image_base64"],
    },
    cost_factor=2.0,
)

WEB_TOOLS: list[ToolSchema] = [
    WEB_SEARCH_TOOL,
    WEB_CRAWL_TOOL,
    WEB_SUMMARIZE_TOOL,
    WEB_ASK_TOOL,
    WEB_SEE_TOOL,
    WEB_LOOK_TOOL,
]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class WebToolsAdapter:
    """Lazy adapter for web_eyes controller functions.

    All imports happen on first use so JINN boots fine without web_eyes.
    """

    def __init__(self) -> None:
        self._crawler: Any = None
        self._controller: Any = None
        self._summarizer: Any = None
        self._path_added = False

    # -- availability check ------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """Check if web_eyes can be imported without side effects."""
        try:
            _vendor = Path(__file__).resolve().parent.parent.parent / "vendor" / "web_eyes"
            if not _vendor.is_dir():
                return False
            if str(_vendor) not in sys.path:
                sys.path.insert(0, str(_vendor))
            import controller  # type: ignore[import-not-found]  # noqa: F401
            return True
        except (ImportError, ModuleNotFoundError):
            return False

    # -- lazy init ----------------------------------------------------------

    def _ensure_path(self) -> None:
        """Add vendor/web_eyes to sys.path on first call."""
        if self._path_added:
            return
        vendor = Path(__file__).resolve().parent.parent.parent / "vendor" / "web_eyes"
        if vendor.is_dir() and str(vendor) not in sys.path:
            sys.path.insert(0, str(vendor))
        self._path_added = True

    async def _ensure_crawler(self) -> str | None:
        """Import + create singleton AsyncWebCrawler. Returns error string or None."""
        if self._crawler is not None:
            return None
        self._ensure_path()
        try:
            from crawl4ai import AsyncWebCrawler  # type: ignore[import-not-found]
            self._crawler = AsyncWebCrawler()
            await self._crawler.__aenter__()
            return None
        except (ImportError, ModuleNotFoundError) as exc:
            return f"Web tools unavailable: missing dependency ({exc})"
        except Exception as exc:
            return f"Web tools unavailable: crawler init failed ({exc})"

    def _get_controller(self):
        """Lazily import web_eyes controller module."""
        if self._controller is not None:
            return self._controller
        self._ensure_path()
        import controller as ctrl  # type: ignore[import-not-found]
        self._controller = ctrl
        return ctrl

    def _get_summarizer(self):
        """Lazily import web_eyes summarizer module."""
        if self._summarizer is not None:
            return self._summarizer
        self._ensure_path()
        import summarizer as summ  # type: ignore[import-not-found]
        self._summarizer = summ
        return summ

    # -- public API ---------------------------------------------------------

    async def search(self, query: str, limit: int = 5) -> str:
        err = await self._ensure_crawler()
        if err:
            return err
        try:
            ctrl = self._get_controller()
        except (ImportError, ModuleNotFoundError) as exc:
            return f"Web tools unavailable: web_eyes not installed ({exc})"
        try:
            return await ctrl.search_and_crawl(query, limit=limit)
        except Exception as exc:
            return f"Web search error: {exc}"

    async def crawl(self, urls: list[str]) -> str:
        err = await self._ensure_crawler()
        if err:
            return err
        try:
            ctrl = self._get_controller()
        except (ImportError, ModuleNotFoundError) as exc:
            return f"Web tools unavailable: web_eyes not installed ({exc})"
        try:
            return await ctrl.crawl_only(urls)
        except Exception as exc:
            return f"Web crawl error: {exc}"

    async def summarize(self, urls: list[str], instruction: str | None = None) -> str:
        err = await self._ensure_crawler()
        if err:
            return err
        try:
            ctrl = self._get_controller()
        except (ImportError, ModuleNotFoundError) as exc:
            return f"Web tools unavailable: web_eyes not installed ({exc})"
        try:
            return await ctrl.summarize_urls(urls, instruction=instruction)
        except Exception as exc:
            return f"Web summarize error: {exc}"

    async def ask(self, question: str, scrape_top: int = 3) -> str:
        err = await self._ensure_crawler()
        if err:
            return err
        try:
            ctrl = self._get_controller()
        except (ImportError, ModuleNotFoundError) as exc:
            return f"Web tools unavailable: web_eyes not installed ({exc})"
        try:
            return await ctrl.ask_question(question, scrape_top=scrape_top)
        except Exception as exc:
            return f"Web ask error: {exc}"

    async def see(
        self,
        urls: list[str],
        instruction: str | None = None,
        extract_prompt: str | None = None,
    ) -> str:
        err = await self._ensure_crawler()
        if err:
            return err
        try:
            ctrl = self._get_controller()
        except (ImportError, ModuleNotFoundError) as exc:
            return f"Web tools unavailable: web_eyes not installed ({exc})"
        try:
            return await ctrl.see_urls(
                urls,
                instruction=instruction,
                extract_prompt=extract_prompt,
            )
        except Exception as exc:
            return f"Web see error: {exc}"

    async def look(self, image_base64: str, instruction: str | None = None) -> str:
        try:
            summ = self._get_summarizer()
        except (ImportError, ModuleNotFoundError) as exc:
            return f"Web tools unavailable: web_eyes not installed ({exc})"
        try:
            return await summ.vision_extract(image_base64, instruction=instruction)
        except Exception as exc:
            return f"Web look error: {exc}"

    async def close(self) -> None:
        """Shut down the crawler if it was created."""
        if self._crawler is not None:
            try:
                await self._crawler.__aexit__(None, None, None)
            except Exception:
                pass
            self._crawler = None
