"""
Парсер резюме — извлекает текст из PDF, DOCX, TXT.
"""
import logging
import io

logger = logging.getLogger(__name__)


async def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Извлечь текст из PDF."""
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
        return "\n".join(text_parts)
    except Exception as e:
        logger.error(f"PDF parse error: {e}")
        return ""


async def extract_text_from_docx(file_bytes: bytes) -> str:
    """Извлечь текст из DOCX."""
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except Exception as e:
        logger.error(f"DOCX parse error: {e}")
        return ""


async def extract_text(file_bytes: bytes, filename: str) -> str:
    """Определить формат и извлечь текст."""
    filename_lower = filename.lower()

    if filename_lower.endswith(".pdf"):
        text = await extract_text_from_pdf(file_bytes)
    elif filename_lower.endswith(".docx"):
        text = await extract_text_from_docx(file_bytes)
    elif filename_lower.endswith((".txt", ".md")):
        text = file_bytes.decode("utf-8", errors="ignore")
    else:
        # Попробуем как текст
        text = file_bytes.decode("utf-8", errors="ignore")

    return text.strip()[:8000]  # Лимит для хранения
