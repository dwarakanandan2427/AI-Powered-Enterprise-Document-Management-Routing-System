import io

from fastapi import HTTPException


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    try:
        if name.endswith(".pdf"):
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        if name.endswith(".docx"):
            from docx import Document
            return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
        if name.endswith((".txt", ".md", ".csv", ".json", ".log")):
            return data.decode("utf-8", errors="replace")
    except Exception as e:  # corrupt file
        raise HTTPException(422, f"Could not read file: {e}")
    raise HTTPException(415, "Supported types: .pdf, .docx, .txt, .md, .csv, .json, .log")
