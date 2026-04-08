"""Export JINN's encyclopedia pages to standalone, browsable HTML."""

from __future__ import annotations

import re
from pathlib import Path

import markdown as md_lib


def export_to_html(wiki_root: Path, output_dir: Path) -> list[str]:
    """Export all encyclopedia .md pages to standalone HTML.

    Preserves any existing .html files that agents may have written directly.
    Returns list of written file paths (relative to output_dir).
    """
    wiki_root = Path(wiki_root)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    md_files = sorted(wiki_root.rglob("*.md"))

    # Build page metadata for navigation
    pages: list[dict] = []
    for path in md_files:
        rel = path.relative_to(wiki_root)
        html_rel = rel.with_suffix(".html")
        title = _page_title(path)
        pages.append({
            "title": title,
            "html_rel": html_rel,
            "source": path,
        })

    written: list[str] = []

    # Build sidebar nav links (shared across all pages)
    nav_links = sorted(
        [{"title": p["title"], "href": p["html_rel"].as_posix()} for p in pages],
        key=lambda x: x["title"],
    )

    # Render each page
    for page in pages:
        raw_md = page["source"].read_text(encoding="utf-8")
        body_html = _markdown_to_html(raw_md, nav_links)

        out_path = output_dir / page["html_rel"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            _page_html(page["title"], body_html, nav_links),
            encoding="utf-8",
        )
        written.append(page["html_rel"].as_posix())

    # Generate index.html
    index_body = _render_index(pages)
    (output_dir / "index.html").write_text(
        _page_html("Encyclopedia Index", index_body, nav_links),
        encoding="utf-8",
    )
    written.insert(0, "index.html")

    return written


def _page_title(path: Path) -> str:
    """Derive a human-readable title from a filename."""
    stem = path.stem
    # Remove common prefixes like class_, tutorials_
    stem = re.sub(r"^(class_|tutorials?)_", "", stem)
    return stem.replace("_", " ").replace(".", " ").strip().title()


def _markdown_to_html(text: str, nav_links: list[dict]) -> str:
    """Convert markdown to HTML, resolving [[PageName]] cross-links."""
    # Resolve [[PageName]] -> pagename.html
    def _resolve_link(match: re.Match) -> str:
        name = match.group(1)
        href = name.lower().replace(" ", "_") + ".html"
        return f"[{name}]({href})"

    resolved = re.sub(r"\[\[([^\]]+)\]\]", _resolve_link, text)
    return md_lib.markdown(resolved, extensions=["extra", "toc"])


def _page_html(title: str, body: str, nav_links: list[dict]) -> str:
    """Full standalone HTML page with embedded CSS and sidebar nav."""
    nav_items = "\n".join(
        f'<li><a href="{l["href"]}">{l["title"]}</a></li>' for l in nav_links
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ --sidebar: 260px; --bg: #0d1117; --card: #161b22; --border: #30363d;
           --text: #c9d1d9; --heading: #f0f6fc; --accent: #58a6ff; --muted: #8b949e; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
         background: var(--bg); color: var(--text); line-height: 1.6; }}
  .sidebar {{ position: fixed; top: 0; left: 0; width: var(--sidebar); height: 100vh;
             background: var(--card); border-right: 1px solid var(--border);
             overflow-y: auto; padding: 20px 16px; }}
  .sidebar h2 {{ font-size: 14px; color: var(--muted); text-transform: uppercase;
                letter-spacing: 0.05em; margin-bottom: 12px; }}
  .sidebar ul {{ list-style: none; }}
  .sidebar li {{ margin-bottom: 4px; }}
  .sidebar a {{ color: var(--accent); text-decoration: none; font-size: 13px; }}
  .sidebar a:hover {{ text-decoration: underline; }}
  .main {{ margin-left: var(--sidebar); padding: 32px 40px; max-width: 900px; }}
  h1 {{ color: var(--heading); font-size: 28px; margin-bottom: 16px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
  h2 {{ color: var(--heading); font-size: 22px; margin: 24px 0 12px; }}
  h3 {{ color: var(--heading); font-size: 18px; margin: 20px 0 10px; }}
  code {{ background: var(--card); padding: 2px 6px; border-radius: 4px; font-size: 14px;
         font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace; }}
  pre {{ background: var(--card); border: 1px solid var(--border); border-radius: 6px;
        padding: 16px; overflow-x: auto; margin: 12px 0; }}
  pre code {{ background: none; padding: 0; }}
  a {{ color: var(--accent); }}
  table {{ border-collapse: collapse; margin: 12px 0; width: 100%; }}
  th, td {{ border: 1px solid var(--border); padding: 8px 12px; text-align: left; }}
  th {{ background: var(--card); color: var(--heading); }}
  blockquote {{ border-left: 3px solid var(--accent); padding-left: 16px; color: var(--muted); margin: 12px 0; }}
</style>
</head>
<body>
<nav class="sidebar">
  <h2>Encyclopedia</h2>
  <ul>{nav_items}</ul>
</nav>
<main class="main">
<h1>{title}</h1>
{body}
</main>
</body>
</html>"""


def _render_index(pages: list[dict]) -> str:
    """Render the encyclopedia index — a list of all pages with summaries."""
    items = []
    for p in pages:
        href = p["html_rel"].as_posix()
        # Read first meaningful line as a mini-summary
        try:
            raw = p["source"].read_text(encoding="utf-8")
        except Exception:
            raw = ""
        summary = _first_summary(raw)
        items.append(f'<li><a href="{href}">{p["title"]}</a>'
                     f'{" — " + summary if summary else ""}</li>')
    return "<ul>\n" + "\n".join(items) + "\n</ul>"


def _first_summary(text: str, max_len: int = 120) -> str:
    """Extract the first non-heading, non-empty line as a summary."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and len(stripped) > 10:
            return stripped[:max_len]
    return ""
