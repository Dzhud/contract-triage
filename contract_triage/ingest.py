"""
Contract ingestion: turn a PDF / DOCX / TXT file into plain text.

Kept deliberately simple and dependency-light. Real contracts arrive in all
three formats, so we handle each and normalise to text the rest of the
pipeline can work with. Parsing failures are surfaced clearly rather than
swallowed — if we can't read the document, a human needs to know.
"""

from __future__ import annotations

from pathlib import Path


def load_contract(path: str | Path) -> str:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Contract not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".txt" or suffix == ".md":
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        return _load_pdf(path)
    if suffix == ".docx":
        return _load_docx(path)
    raise ValueError(
        f"Unsupported file type: {suffix}. Supported: .txt, .pdf, .docx"
    )


def _load_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ImportError("Install pypdf to read PDF contracts: pip install pypdf") from e
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        raise ValueError(
            f"No extractable text in {path.name}. It may be a scanned image "
            "(OCR would be needed) — flag for human review."
        )
    return text


def _load_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as e:
        raise ImportError("Install python-docx to read DOCX contracts.") from e
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)
