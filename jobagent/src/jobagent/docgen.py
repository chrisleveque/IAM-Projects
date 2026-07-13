"""Generate .docx (and optionally .pdf via LibreOffice) from a tailored package."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from docx import Document
from docx.shared import Pt

from .ai.tailor import TailoredResume


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len] or "job"


def _base_style(doc: Document) -> None:
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)


def write_resume_docx(resume: TailoredResume, path: Path) -> Path:
    doc = Document()
    _base_style(doc)

    doc.add_heading(resume.name, level=0)
    if resume.contact:
        doc.add_paragraph(resume.contact)
    if resume.summary:
        doc.add_heading("Summary", level=1)
        doc.add_paragraph(resume.summary)
    if resume.skills:
        doc.add_heading("Skills", level=1)
        doc.add_paragraph(" · ".join(resume.skills))
    if resume.experience:
        doc.add_heading("Experience", level=1)
        for role in resume.experience:
            header = doc.add_paragraph()
            header.add_run(f"{role.title} — {role.company}").bold = True
            meta = " · ".join(x for x in (role.dates, role.location) if x)
            if meta:
                doc.add_paragraph(meta).runs[0].italic = True
            for bullet in role.bullets:
                doc.add_paragraph(bullet, style="List Bullet")
    if resume.education:
        doc.add_heading("Education", level=1)
        for line in resume.education:
            doc.add_paragraph(line, style="List Bullet")
    if resume.certifications:
        doc.add_heading("Certifications", level=1)
        for line in resume.certifications:
            doc.add_paragraph(line, style="List Bullet")

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


def write_cover_letter_docx(text: str, name: str, path: Path) -> Path:
    doc = Document()
    _base_style(doc)
    doc.add_heading(name, level=0)
    for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
        doc.add_paragraph(para)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


def convert_to_pdf(docx_path: Path) -> Path | None:
    """Convert with LibreOffice if installed; return the PDF path or None."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        return None
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf",
             "--outdir", str(docx_path.parent), str(docx_path)],
            check=True, capture_output=True, timeout=120,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    pdf = docx_path.with_suffix(".pdf")
    return pdf if pdf.exists() else None
