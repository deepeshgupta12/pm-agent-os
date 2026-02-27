from __future__ import annotations

import io
import re
from typing import List

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


def _wrap_text(text: str, font: str, font_size: int, max_width: float) -> List[str]:
    """
    Simple word-wrap for PDF.
    """
    words = text.split()
    lines: List[str] = []
    cur: List[str] = []
    for w in words:
        trial = (" ".join(cur + [w])).strip()
        if stringWidth(trial, font, font_size) <= max_width:
            cur.append(w)
        else:
            if cur:
                lines.append(" ".join(cur))
                cur = [w]
            else:
                lines.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines


_BULLET_RE = re.compile(r"^(\-|\*)\s+")
_NUM_RE = re.compile(r"^(\d+)\.\s+")


def markdown_to_pdf_bytes(title: str, markdown: str) -> bytes:
    """
    Minimal Markdown → PDF (small upgrade):
    - # / ## headings
    - bullets starting with '-' or '*'
    - numbered lists like '1. '
    - fenced code blocks ``` ... ``` rendered in Courier
    - paragraphs
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    width, height = A4
    left = 0.75 * inch
    right = 0.75 * inch
    top = height - 0.75 * inch
    bottom = 0.75 * inch
    max_width = width - left - right

    y = top

    def ensure_space(lines_needed: int, line_h: float):
        nonlocal y
        if y - (lines_needed * line_h) < bottom:
            c.showPage()
            y = top

    # Title
    c.setFont("Helvetica-Bold", 16)
    ensure_space(2, 18)
    c.drawString(left, y, title or "Export")
    y -= 22

    c.setFont("Helvetica", 10)
    ensure_space(1, 12)
    c.drawString(left, y, "Exported from PM Agent OS")
    y -= 18

    lines = (markdown or "").splitlines()

    in_code = False
    code_font = "Courier"
    code_size = 9

    for raw in lines:
        line = raw.rstrip()

        # toggle fenced code
        if line.strip().startswith("```"):
            in_code = not in_code
            # add a tiny gap around fences
            y -= 6
            continue

        if not line.strip():
            y -= 8
            continue

        if in_code:
            c.setFont(code_font, code_size)
            wrapped = _wrap_text(line, code_font, code_size, max_width)
            ensure_space(len(wrapped), 12)
            for w in wrapped:
                c.drawString(left, y, w)
                y -= 12
            continue

        # Heading 1
        if line.startswith("# "):
            txt = line[2:].strip()
            c.setFont("Helvetica-Bold", 14)
            wrapped = _wrap_text(txt, "Helvetica-Bold", 14, max_width)
            ensure_space(len(wrapped) + 1, 18)
            for w in wrapped:
                c.drawString(left, y, w)
                y -= 18
            y -= 4
            c.setFont("Helvetica", 11)
            continue

        # Heading 2
        if line.startswith("## "):
            txt = line[3:].strip()
            c.setFont("Helvetica-Bold", 12)
            wrapped = _wrap_text(txt, "Helvetica-Bold", 12, max_width)
            ensure_space(len(wrapped) + 1, 16)
            for w in wrapped:
                c.drawString(left, y, w)
                y -= 16
            y -= 2
            c.setFont("Helvetica", 11)
            continue

        # Bullet
        if _BULLET_RE.match(line):
            txt = _BULLET_RE.sub("", line).strip()
            c.setFont("Helvetica", 11)
            wrapped = _wrap_text(txt, "Helvetica", 11, max_width - 18)
            ensure_space(len(wrapped), 14)
            if wrapped:
                c.drawString(left, y, u"\u2022")
                c.drawString(left + 14, y, wrapped[0])
                y -= 14
                for w in wrapped[1:]:
                    c.drawString(left + 14, y, w)
                    y -= 14
            continue

        # Numbered list
        nm = _NUM_RE.match(line)
        if nm:
            prefix = nm.group(1) + "."
            txt = _NUM_RE.sub("", line).strip()
            c.setFont("Helvetica", 11)
            wrapped = _wrap_text(txt, "Helvetica", 11, max_width - 24)
            ensure_space(len(wrapped), 14)
            if wrapped:
                c.drawString(left, y, prefix)
                c.drawString(left + 18, y, wrapped[0])
                y -= 14
                for w in wrapped[1:]:
                    c.drawString(left + 18, y, w)
                    y -= 14
            continue

        # Paragraph
        c.setFont("Helvetica", 11)
        wrapped = _wrap_text(line.strip(), "Helvetica", 11, max_width)
        ensure_space(len(wrapped), 14)
        for w in wrapped:
            c.drawString(left, y, w)
            y -= 14

    c.save()
    return buf.getvalue()