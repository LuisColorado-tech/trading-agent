#!/usr/bin/env python3
"""Build EPUB from markdown chapters."""
import os
import re
from pathlib import Path
from ebooklib import epub
import markdown

BOOK_DIR = Path(__file__).parent
CHAPTERS_DIR = BOOK_DIR / "chapters"
OUTPUT = BOOK_DIR / "AI_Trading_Agent_Educativo.epub"

CSS = """
body { font-family: Georgia, serif; line-height: 1.6; margin: 1em; }
h1 { font-size: 1.8em; margin-top: 1.5em; border-bottom: 2px solid #333; padding-bottom: 0.3em; }
h2 { font-size: 1.4em; margin-top: 1.2em; }
h3 { font-size: 1.2em; }
pre { background: #f4f4f4; padding: 1em; border-radius: 4px; overflow-x: auto; font-size: 0.85em; }
code { background: #f4f4f4; padding: 0.15em 0.3em; border-radius: 3px; font-size: 0.9em; }
pre code { background: none; padding: 0; }
blockquote { border-left: 3px solid #666; padding-left: 1em; color: #555; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; }
th, td { border: 1px solid #ccc; padding: 0.5em; text-align: left; }
th { background: #f0f0f0; }
.math { font-style: italic; }
"""


def get_chapter_files():
    """Get ordered list of chapter markdown files."""
    files = sorted(CHAPTERS_DIR.glob("*.md"))
    return files


def md_to_html(md_text):
    """Convert markdown to HTML with extensions."""
    extensions = ["fenced_code", "tables", "toc", "codehilite", "md_in_html"]
    return markdown.markdown(md_text, extensions=extensions)


def build():
    book = epub.EpubBook()
    book.set_identifier("ai-trading-agent-educativo-2026")
    book.set_title("AI Trading Agent — De la Teoría a la Implementación")
    book.set_language("es")
    book.add_author("Luis Colorado")
    book.add_metadata("DC", "date", "2026")
    book.add_metadata("DC", "description",
        "Libro educativo que cubre desde fundamentos financieros hasta "
        "la implementación técnica de un agente de trading con IA.")

    style = epub.EpubItem(uid="style", file_name="style/default.css",
                          media_type="text/css", content=CSS.encode())
    book.add_item(style)

    chapters = []
    spine = ["nav"]
    toc = []

    chapter_files = get_chapter_files()
    if not chapter_files:
        print("ERROR: No chapter files found in", CHAPTERS_DIR)
        return

    for i, md_file in enumerate(chapter_files):
        md_text = md_file.read_text(encoding="utf-8")
        html_body = md_to_html(md_text)

        title_match = re.search(r"^#\s+(.+)", md_text, re.MULTILINE)
        title = title_match.group(1) if title_match else md_file.stem

        ch = epub.EpubHtml(
            title=title,
            file_name=f"ch_{i:02d}.xhtml",
            lang="es",
            content=f"<html><head><link rel='stylesheet' href='style/default.css'/></head>"
                    f"<body>{html_body}</body></html>"
        )
        ch.add_item(style)
        book.add_item(ch)
        chapters.append(ch)
        spine.append(ch)
        toc.append(epub.Link(f"ch_{i:02d}.xhtml", title, f"ch_{i:02d}"))

    book.toc = toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine

    epub.write_epub(str(OUTPUT), book, {})
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"EPUB generado: {OUTPUT} ({size_kb:.0f} KB, {len(chapters)} capítulos)")


if __name__ == "__main__":
    build()
