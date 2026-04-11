"""Converts Markdown resume text to a styled PDF using fpdf2."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import markdown
from fpdf import FPDF

logger = logging.getLogger(__name__)

_CSS_CLEAN_RE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)


class _ResumePDF(FPDF):
    """Custom FPDF subclass with a clean header/footer for resumes."""

    def header(self) -> None:
        pass

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


def md_to_pdf(md_text: str, output_path: str | Path) -> Path:
    """Convert Markdown text to a professionally styled PDF.

    Uses markdown lib to parse to HTML, then fpdf2's write_html() to render.
    Returns the Path of the written PDF file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br"],
    )

    html_body = _CSS_CLEAN_RE.sub("", html_body)

    styled_html = _wrap_with_styles(html_body)

    pdf = _ResumePDF(orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    pdf.set_font("Helvetica", size=10)

    try:
        pdf.write_html(styled_html)
    except Exception as e:
        logger.warning("write_html partially failed (%s), falling back to plain text", e)
        _fallback_plain_text(pdf, md_text)

    pdf.output(str(output_path))
    logger.info("PDF resume saved: %s (%d bytes)", output_path, output_path.stat().st_size)
    return output_path


def _wrap_with_styles(html_body: str) -> str:
    """Wrap raw HTML body with inline styling compatible with fpdf2."""
    return f"""
<font size="22"><b>Resume</b></font>
<br><br>
{html_body}
"""


def _fallback_plain_text(pdf: FPDF, text: str) -> None:
    """Last-resort: dump the markdown as plain text into the PDF."""
    pdf.set_font("Helvetica", size=10)
    for line in text.splitlines():
        if line.startswith("# "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.cell(0, 8, line.lstrip("# ").strip(), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=10)
        elif line.startswith("## "):
            pdf.set_font("Helvetica", "B", 13)
            pdf.cell(0, 7, line.lstrip("# ").strip(), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=10)
        elif line.startswith("### "):
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 6, line.lstrip("# ").strip(), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=10)
        elif line.strip().startswith("- "):
            pdf.cell(8)
            pdf.multi_cell(0, 5, f"\u2022 {line.strip().lstrip('- ')}")
        elif line.strip():
            pdf.multi_cell(0, 5, line.strip())
        else:
            pdf.ln(3)
