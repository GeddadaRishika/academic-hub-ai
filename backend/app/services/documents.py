from pathlib import Path
from pypdf import PdfReader
from fastapi import UploadFile, HTTPException
from app.core.config import settings

ALLOWED_TYPES = {"application/pdf"}

def save_and_extract(file: UploadFile, document_id: int):
    if file.content_type not in ALLOWED_TYPES or not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Only PDF files are supported.")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes: raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_mb} MB limit.")
    if not data: raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    upload_dir = Path(settings.upload_dir).resolve(); upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"document_{document_id}.pdf"; path = upload_dir / safe_name
    path.write_bytes(data)
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try: reader.decrypt("")
            except Exception: raise HTTPException(status_code=400, detail="Encrypted PDFs are not supported.")
        pages = [(i + 1, (page.extract_text() or "")) for i, page in enumerate(reader.pages)]
        if not pages or not any(text.strip() for _, text in pages):
            path.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail="No readable text was found. Scanned PDFs need OCR before upload.")
        return str(path), pages
    except HTTPException:
        raise
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Could not read PDF: {exc}") from exc
