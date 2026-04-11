"""Converts a resume (Markdown / plain-text) into a professionally styled PDF.

Handles both standard Markdown headings and the plain-text format used by the
master resume (ALL-CAPS section headers, unicode bullet points, pipe-separated
contact info, etc.).
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

from fpdf import FPDF

logger = logging.getLogger(__name__)

# Colours (RGB)
_CLR_PRIMARY = (26, 58, 95)       # dark navy
_CLR_ACCENT = (33, 115, 186)      # blue accent
_CLR_TEXT = (40, 40, 40)          # near-black body
_CLR_MUTED = (110, 110, 110)     # grey for contact info
_CLR_RULE = (200, 210, 220)      # light separator line

_BULLET = "-"  # ASCII bullet for core-font compatibility

_SECTION_RE = re.compile(
    r"^(PROFESSIONAL SUMMARY|TECHNICAL SKILLS|PROFESSIONAL EXPERIENCE|"
    r"KEY ACHIEVEMENTS|EDUCATION|CERTIFICATIONS|PROJECTS|SKILLS|SUMMARY|"
    r"EXPERIENCE|ACHIEVEMENTS|CONTACT|OBJECTIVE|WORK EXPERIENCE|"
    r"ADDITIONAL INFORMATION|INTERESTS|REFERENCES|HONORS|AWARDS|"
    r"PUBLICATIONS|LANGUAGES|VOLUNTEER)$",
    re.IGNORECASE,
)

_ROLE_LINE_RE = re.compile(r"^(.+?)\s*\|\s*(.+)$")
_LOCATION_DATE_RE = re.compile(r"^(.+?)\s*\|\s*(.+)$")

# Common system-font search paths
_FONT_SEARCH_PATHS = [
    # Ubuntu / Debian (GitHub Actions)
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    # Windows
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
    Path("C:/Windows/Fonts/calibri.ttf"),
    Path("C:/Windows/Fonts/calibrib.ttf"),
]


def _find_font(keyword: str) -> Path | None:
    """Locate a system TTF font matching *keyword* (case-insensitive)."""
    kw = keyword.lower()
    for p in _FONT_SEARCH_PATHS:
        if kw in p.name.lower() and p.exists():
            return p
    return None


class _ResumePDF(FPDF):
    _unicode_mode: bool = False

    def header(self) -> None:
        pass

    def footer(self) -> None:
        self.set_y(-12)
        self._set_body_font("I", 7)
        self.set_text_color(*_CLR_MUTED)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    # ── font helpers ──────────────────────────────────────────────────
    def setup_fonts(self) -> None:
        """Try to register a Unicode TTF font; fall back to built-in Helvetica."""
        regular = _find_font("dejavu") or _find_font("arial") or _find_font("liberation") or _find_font("calibri")
        if regular:
            try:
                self.add_font("Resume", "", str(regular), uni=True)
                bold = self._bold_variant(regular)
                if bold and bold.exists():
                    self.add_font("Resume", "B", str(bold), uni=True)
                else:
                    self.add_font("Resume", "B", str(regular), uni=True)
                italic = self._italic_variant(regular)
                if italic and italic.exists():
                    self.add_font("Resume", "I", str(italic), uni=True)
                else:
                    self.add_font("Resume", "I", str(regular), uni=True)
                self._unicode_mode = True
                logger.info("PDF: Using Unicode font from %s", regular)
                return
            except Exception as e:
                logger.warning("Failed to load TTF font %s: %s", regular, e)

        self._unicode_mode = False
        logger.info("PDF: Falling back to built-in Helvetica (ASCII only)")

    @staticmethod
    def _bold_variant(regular: Path) -> Path | None:
        name = regular.name.lower()
        parent = regular.parent
        if "dejavu" in name:
            return parent / "DejaVuSans-Bold.ttf"
        if "arial" in name:
            return parent / "arialbd.ttf"
        if "calibri" in name:
            return parent / "calibrib.ttf"
        if "liberation" in name:
            return parent / "LiberationSans-Bold.ttf"
        return None

    @staticmethod
    def _italic_variant(regular: Path) -> Path | None:
        name = regular.name.lower()
        parent = regular.parent
        if "dejavu" in name:
            return parent / "DejaVuSans-Oblique.ttf"
        if "arial" in name:
            return parent / "ariali.ttf"
        if "calibri" in name:
            return parent / "calibrii.ttf"
        if "liberation" in name:
            return parent / "LiberationSans-Italic.ttf"
        return None

    def _set_body_font(self, style: str = "", size: int = 10) -> None:
        family = "Resume" if self._unicode_mode else "Helvetica"
        self.set_font(family, style, size)

    @property
    def bullet_char(self) -> str:
        return "\u2022" if self._unicode_mode else _BULLET


def md_to_pdf(md_text: str, output_path: str | Path) -> Path:
    """Parse resume text and render a styled PDF."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = _ResumePDF(orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_left_margin(18)
    pdf.set_right_margin(18)
    pdf.setup_fonts()
    pdf.add_page()

    lines = md_text.splitlines()
    _render_resume(pdf, lines)

    pdf.output(str(output_path))
    size = output_path.stat().st_size
    logger.info("PDF resume saved: %s (%d bytes)", output_path, size)
    return output_path


# ── Rendering engine ─────────────────────────────────────────────────────────

def _render_resume(pdf: _ResumePDF, lines: list[str]) -> None:
    """Walk through resume lines and render each element with proper styling."""
    i = 0
    header_done = False

    while i < len(lines):
        line = lines[i].rstrip()

        if not line.strip():
            i += 1
            continue

        # Markdown headings
        if line.startswith("# "):
            _draw_name(pdf, line.lstrip("# ").strip())
            header_done = True
            i += 1
            continue
        if line.startswith("## "):
            _draw_section_header(pdf, line.lstrip("# ").strip())
            i += 1
            continue
        if line.startswith("### "):
            _draw_role_title(pdf, line.lstrip("# ").strip(), "")
            i += 1
            continue

        # Name block (first 3 non-blank lines)
        if not header_done and i < 3:
            if i == 0:
                _draw_name(pdf, line.strip())
                i += 1
                continue
            if i == 1:
                _draw_subtitle(pdf, line.strip())
                i += 1
                continue
            if i == 2:
                _draw_contact(pdf, line.strip())
                header_done = True
                i += 1
                continue

        # Section header (ALL-CAPS)
        if _SECTION_RE.match(line.strip()):
            _draw_section_header(pdf, line.strip())
            i += 1
            continue

        # Role / Company line  ("Amdocs Limited | Software Test Engineer")
        role_match = _ROLE_LINE_RE.match(line.strip())
        location_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if role_match and _LOCATION_DATE_RE.match(location_line):
            company = role_match.group(1).strip()
            role = role_match.group(2).strip()
            loc_match = _LOCATION_DATE_RE.match(location_line)
            location = loc_match.group(1).strip() if loc_match else ""
            dates = loc_match.group(2).strip() if loc_match else ""
            _draw_role_title(pdf, f"{role}  --  {company}", f"{location}  |  {dates}")
            i += 2
            continue

        # Bullet point
        stripped = line.strip()
        if stripped.startswith(("\u2022 ", "- ", "* ")):
            bullet_text = re.sub(r"^[\u2022\-\*]\s+", "", stripped)
            _draw_bullet(pdf, bullet_text)
            i += 1
            continue

        # Regular paragraph
        _draw_paragraph(pdf, stripped)
        i += 1


# ── Drawing helpers ──────────────────────────────────────────────────────────

def _draw_name(pdf: _ResumePDF, name: str) -> None:
    pdf._set_body_font("B", 22)
    pdf.set_text_color(*_CLR_PRIMARY)
    pdf.cell(0, 11, _safe(pdf, name), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(1)


def _draw_subtitle(pdf: _ResumePDF, text: str) -> None:
    pdf._set_body_font("", 12)
    pdf.set_text_color(*_CLR_ACCENT)
    pdf.cell(0, 7, _safe(pdf, text), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(1)


def _draw_contact(pdf: _ResumePDF, text: str) -> None:
    pdf._set_body_font("", 9)
    pdf.set_text_color(*_CLR_MUTED)
    display = text.replace("|", "   |   ")
    pdf.cell(0, 5, _safe(pdf, display), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(2)
    _draw_rule(pdf)
    pdf.ln(3)


def _draw_section_header(pdf: _ResumePDF, title: str) -> None:
    pdf.ln(4)
    pdf._set_body_font("B", 12)
    pdf.set_text_color(*_CLR_ACCENT)
    pdf.cell(0, 7, _safe(pdf, title.upper()), new_x="LMARGIN", new_y="NEXT")
    _draw_rule(pdf, color=_CLR_ACCENT, width=0.5)
    pdf.ln(2)


def _draw_role_title(pdf: _ResumePDF, role_line: str, detail_line: str) -> None:
    pdf._set_body_font("B", 10)
    pdf.set_text_color(*_CLR_PRIMARY)
    pdf.cell(0, 6, _safe(pdf, role_line), new_x="LMARGIN", new_y="NEXT")

    if detail_line:
        pdf._set_body_font("I", 9)
        pdf.set_text_color(*_CLR_MUTED)
        pdf.cell(0, 5, _safe(pdf, detail_line), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(1)


def _draw_bullet(pdf: _ResumePDF, text: str) -> None:
    pdf._set_body_font("", 9)
    pdf.set_text_color(*_CLR_TEXT)
    x = pdf.get_x()
    pdf.set_x(x + 5)

    bullet = pdf.bullet_char

    colon_pos = text.find(":")
    if 0 < colon_pos < 40:
        label = text[: colon_pos + 1]
        rest = text[colon_pos + 1 :].strip()
        pdf._set_body_font("B", 9)
        pdf.write(4.5, _safe(pdf, f"{bullet}  {label} "))
        pdf._set_body_font("", 9)
        pdf.multi_cell(0, 4.5, _safe(pdf, rest), new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.multi_cell(0, 4.5, _safe(pdf, f"{bullet}  {text}"), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(0.5)


def _draw_paragraph(pdf: _ResumePDF, text: str) -> None:
    pdf._set_body_font("", 9)
    pdf.set_text_color(*_CLR_TEXT)
    pdf.multi_cell(0, 4.5, _safe(pdf, text), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _draw_rule(pdf: _ResumePDF, color: tuple = _CLR_RULE, width: float = 0.3) -> None:
    pdf.set_draw_color(*color)
    pdf.set_line_width(width)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)


def _safe(pdf: _ResumePDF, text: str) -> str:
    """Ensure text is compatible with the current font encoding."""
    if pdf._unicode_mode:
        return text
    try:
        text.encode("latin-1")
        return text
    except UnicodeEncodeError:
        return text.encode("latin-1", errors="replace").decode("latin-1")
