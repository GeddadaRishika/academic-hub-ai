from io import BytesIO
from starlette.datastructures import UploadFile, Headers
from fastapi import HTTPException
from app.services.documents import save_and_extract

def test_non_pdf_is_rejected():
    upload = UploadFile(filename="notes.txt", file=BytesIO(b"hello"), headers=Headers({"content-type":"text/plain"}))
    try:
        save_and_extract(upload, 123456)
        assert False, "Expected unsupported file error"
    except HTTPException as exc:
        assert exc.status_code == 415
