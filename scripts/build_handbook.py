#!/usr/bin/env python3
"""Regenerate the handbook mirror + HTML from the canonical brain page.

One command keeps the three copies in sync (edit canonical -> regenerate):

    canonical  ../wiki/handbook.md        (Obsidian; wikilinks into the brain)
    mirror     HANDBOOK.md                (repo-root; wikilinks -> relative md links)
    html       reports/handbook.html      (self-contained dark-theme page)

Usage:
    python scripts/build_handbook.py            # writes both outputs
    python scripts/build_handbook.py --check    # exit 1 if outputs are stale (CI-style)

Wikilinks resolve by basename against ../wiki/**/*.md (Obsidian semantics; the
brain enforces unique basenames). Unresolvable links are left as plain text and
reported. Requires the ``markdown`` package (``pip install markdown``).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
BRAIN_ROOT = CODE_ROOT.parent
CANONICAL = BRAIN_ROOT / "wiki" / "handbook.md"
MIRROR = CODE_ROOT / "HANDBOOK.md"
HTML_OUT = CODE_ROOT / "reports" / "handbook.html"

MIRROR_HEADER = (
    "<!-- Generated from ../wiki/handbook.md (canonical). Edit that file, then regenerate. -->\n"
    "> **Canonical 版本：** `../wiki/handbook.md`（Obsidian，會 wikilink 入 brain）。\n"
    "> 本檔係 code repo 的鏡像，連結已改為相對路徑；改內容請改 canonical 再重生。\n"
    "\n"
)

#: Prose-path rewrites: the canonical speaks brain-root-relative (`wiki/`,
#: `code/`); the mirror lives inside code/, so those flip. Order matters.
SUBSTITUTIONS: list[tuple[str, str]] = [
    ("（`code/`）", "（本 repo 根）"),  # whole-repo mention, not a path prefix
    ("`code/", "`"),                     # `code/src/...` -> `src/...`
    ("`wiki/", "`../wiki/"),             # `wiki/...` -> `../wiki/...`
]

_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)

# Styling lifted verbatim from the first generated reports/handbook.html so
# regeneration never churns the look.
_CSS = """
:root{--bg:#0f1419;--card:#1a2129;--ink:#e6e8ea;--mut:#8a949e;--acc:#4fc3f7;--pos:#66bb6a;--neg:#ef5350;--warn:#ffb74d;--line:#2a333d}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font:16px/1.7 -apple-system,'Segoe UI','Microsoft JhengHei',Roboto,sans-serif;margin:0}
.wrap{max-width:900px;margin:0 auto;padding:32px 5vw 80px}
h1{font-size:26px;margin:.4em 0 .2em;border-bottom:2px solid var(--acc);padding-bottom:8px}
h2{font-size:20px;color:var(--acc);margin:1.8em 0 .5em;border-bottom:1px solid var(--line);padding-bottom:4px}
h3{font-size:16.5px;color:var(--warn);margin:1.3em 0 .4em}
a{color:var(--acc);text-decoration:none} a:hover{text-decoration:underline}
code{background:#0b0f14;border:1px solid var(--line);border-radius:5px;padding:1px 5px;font:13.5px/1.5 'Cascadia Code',Consolas,monospace}
pre{background:#0b0f14;border:1px solid var(--line);border-radius:10px;padding:14px 16px;overflow-x:auto}
pre code{border:0;padding:0;background:none}
blockquote{border-left:3px solid var(--warn);background:#20242c;margin:12px 0;padding:10px 16px;border-radius:0 8px 8px 0;color:#d7dbe0}
table{border-collapse:collapse;width:100%;margin:14px 0;font-size:14.5px;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:7px 11px;text-align:left;vertical-align:top}
th{background:#212a34;color:var(--mut);white-space:nowrap}
tr:nth-child(even) td{background:#161c23}
hr{border:0;border-top:1px solid var(--line);margin:28px 0}
strong{color:#fff}
ul,ol{padding-left:22px}
.meta{color:var(--mut);font-size:13px;margin-top:6px}
""".strip()


def wiki_page_map() -> dict[str, Path]:
    """basename (no .md) -> path relative to the brain root, for all wiki pages."""
    return {
        p.stem: p.relative_to(BRAIN_ROOT)
        for p in sorted((BRAIN_ROOT / "wiki").rglob("*.md"))
    }


def build_mirror(canonical_text: str, pages: dict[str, Path]) -> tuple[str, list[str]]:
    """Canonical markdown -> mirror markdown; returns (text, unresolved links)."""
    body = _FRONTMATTER.sub("", canonical_text)
    unresolved: list[str] = []

    def link(m: re.Match[str]) -> str:
        name, alias = m.group(1).strip(), m.group(2)
        page = pages.get(name)
        if page is None:
            unresolved.append(name)
            return alias or name
        return f"[{alias or name}](../{page.as_posix()})"

    body = _WIKILINK.sub(link, body)
    for old, new in SUBSTITUTIONS:
        body = body.replace(old, new)
    return MIRROR_HEADER + body, unresolved


def build_html(mirror_text: str) -> str:
    import markdown

    body_md = mirror_text.split("-->\n", 1)[-1]  # drop the generated-comment line
    html_body = markdown.markdown(body_md, extensions=["tables", "fenced_code"])
    title_m = re.search(r"^# (.+)$", mirror_text, re.MULTILINE)
    title = title_m.group(1).strip() if title_m else "Handbook"
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="zh-Hant"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n<style>\n{_CSS}\n</style>\n"
        f'</head><body><div class="wrap">\n{html_body}\n'
        "</div></body></html>\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify outputs are current; write nothing (exit 1 if stale)")
    args = parser.parse_args()

    if not CANONICAL.exists():
        print(f"canonical not found: {CANONICAL}", file=sys.stderr)
        return 1
    mirror_text, unresolved = build_mirror(
        CANONICAL.read_text(encoding="utf-8"), wiki_page_map()
    )
    html_text = build_html(mirror_text)
    if unresolved:
        print(f"[warn] unresolved wikilinks left as plain text: {sorted(set(unresolved))}")

    if args.check:
        stale = []
        if not MIRROR.exists() or MIRROR.read_text(encoding="utf-8") != mirror_text:
            stale.append(str(MIRROR))
        if not HTML_OUT.exists() or HTML_OUT.read_text(encoding="utf-8") != html_text:
            stale.append(str(HTML_OUT))
        if stale:
            print("stale (rerun scripts/build_handbook.py): " + ", ".join(stale))
            return 1
        print("handbook outputs are current.")
        return 0

    MIRROR.write_text(mirror_text, encoding="utf-8")
    HTML_OUT.parent.mkdir(parents=True, exist_ok=True)
    HTML_OUT.write_text(html_text, encoding="utf-8")
    print(f"wrote {MIRROR.relative_to(CODE_ROOT)} and {HTML_OUT.relative_to(CODE_ROOT)} "
          f"from {CANONICAL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
