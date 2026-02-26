import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_pdf(filepath: Path) -> list[str]:
    """Extract text from a PDF file using PyMuPDF.

    Returns a list of strings, one per page.
    """
    import pymupdf

    pages: list[str] = []
    doc = pymupdf.open(str(filepath))

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        if text.strip():
            pages.append(text)

    doc.close()

    if not pages:
        logger.warning("No text extracted from: %s", filepath.name)

    return pages
