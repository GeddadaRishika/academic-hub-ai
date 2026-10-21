import json
from google import genai
from google.genai import types
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.models import DocumentChunk, Document

class RAGError(RuntimeError): pass

def _client():
    if not settings.gemini_api_key:
        raise RAGError("Gemini is not configured. Add GEMINI_API_KEY to backend/.env.")
    return genai.Client(api_key=settings.gemini_api_key)

def embed_text(content: str) -> list[float]:
    client = _client()
    result = client.models.embed_content(model=settings.gemini_embed_model, contents=content, config=types.EmbedContentConfig(output_dimensionality=768))
    return list(result.embeddings[0].values)

def embed_document_chunks(db: Session, document: Document, pages: list[tuple[int, str]]):
    chunks = []
    chunk_index = 0
    for page_number, text_content in pages:
        clean = " ".join(text_content.split())
        if not clean: continue
        # Keep chunks modest and page-local so citations remain reliable.
        words = clean.split()
        for start in range(0, len(words), 180):
            chunk_text = " ".join(words[start:start + 220])
            if not chunk_text: continue
            chunk = DocumentChunk(document_id=document.id, page_number=page_number, chunk_index=chunk_index, chunk_text=chunk_text, subject=document.subject, topic=document.topic)
            chunk.embedding = embed_text(chunk_text)
            db.add(chunk); chunks.append(chunk); chunk_index += 1
    db.commit()
    return len(chunks)

def retrieve(db: Session, document_id: int, question: str, limit: int = 5):
    vector = embed_text(question)
    # pgvector cosine distance operator; document scope prevents cross-document leakage.
    rows = db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id, DocumentChunk.embedding.is_not(None)).order_by(DocumentChunk.embedding.cosine_distance(vector)).limit(limit).all()
    return rows

def answer_question(db: Session, document: Document, question: str, selected_text: str = ""):
    chunks = retrieve(db, document.id, question, 6)
    if not chunks:
        return {"answer": "I couldn't find relevant information in this document. Check that the PDF contains selectable text and that its processing completed successfully.", "sources": []}
    context = "\n\n".join(f"[Page {c.page_number}] {c.chunk_text}" for c in chunks)
    if selected_text.strip(): context += "\n\n[User-selected text; supplementary context]\n" + selected_text.strip()
    prompt = f'''You are AcademicHub AI, an academic assistant. Answer using only the supplied document context. If the context does not support the answer, say clearly that the information could not be found in the provided material. Do not invent facts or citations. Cite supporting page numbers inline like [Page 4]. Explain simply when useful.\n\nDOCUMENT CONTEXT:\n{context}\n\nQUESTION:\n{question}'''
    try:
        response = _client().models.generate_content(model=settings.gemini_chat_model, contents=prompt)
        answer = (response.text or "").strip()
        if not answer: raise RAGError("Gemini returned an empty response.")
    except Exception as exc:
        if isinstance(exc, RAGError): raise
        raise RAGError(f"Gemini request failed: {exc}") from exc
    sources = sorted({c.page_number for c in chunks})
    return {"answer": answer, "sources": [{"page": p} for p in sources]}
