from contextlib import asynccontextmanager
from pathlib import Path
import json, os, re
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from app.core.config import settings
from app.core.security import hash_password, verify_password, create_access_token, get_current_user, get_admin
from app.database.session import Base, engine, get_db, SessionLocal
from app.models.models import User, Document, DocumentChunk, Vote, Comment, Report, SavedDocument, ChatSession, ChatMessage, Activity
from app.schemas.schemas import RegisterIn, LoginIn, ProfileUpdate, UserOut, CommentIn, VoteIn, ReportIn, AskIn, VerifyIn
from app.services.documents import save_and_extract
from app.rag.pipeline import embed_document_chunks, answer_question, embed_text, RAGError

@asynccontextmanager
async def lifespan(app: FastAPI):
    # The SQL extension is also created in database/schema.sql; this keeps local startup convenient.
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.email == settings.demo_admin_email.lower()).first():
            db.add(User(name="Demo Administrator", email=settings.demo_admin_email.lower(), password_hash=hash_password(settings.demo_admin_password), department="Administration", role="admin", reputation_score=100))
            db.commit()
    finally: db.close()
    yield

app = FastAPI(title="AcademicHub AI API", version="1.0.0", lifespan=lifespan)

@app.get("/")
def home():
    return {
        "message": "Welcome to AcademicHub AI",
        "status": "running",
        "docs": "/docs",
        "health": "/api/health",
    }
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/api/health")
def health(): return {"status":"ok", "service":"AcademicHub AI API"}

@app.post("/api/auth/register", status_code=201)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    email = str(payload.email).lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "An account with this email already exists.")

    # Public registration creates a student account with profile defaults.
    user = User(
        name=email.split("@")[0],
        email=email,
        password_hash=hash_password(payload.password),
        department="",
        year=1,
        semester=1,
        role="student",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": UserOut.model_validate(user),
    }

@app.post("/api/auth/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.password_hash): raise HTTPException(401, "Incorrect email or password.")
    return {"access_token": create_access_token(user.id), "token_type":"bearer", "user": UserOut.model_validate(user)}

@app.post("/api/auth/logout")
def logout(user: User = Depends(get_current_user)): return {"message":"Logged out. Remove the token from this browser."}

@app.get("/api/users/me")
def me(user: User = Depends(get_current_user)): return UserOut.model_validate(user)

@app.patch("/api/users/me")
def update_profile(payload: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(user, key, value)
    db.commit(); db.refresh(user); return UserOut.model_validate(user)

@app.get("/api/users/{user_id}")
def public_profile(user_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    user = db.get(User, user_id)
    if not user: raise HTTPException(404, "User not found")
    return {"id":user.id,"name":user.name,"department":user.department,"year":user.year,"reputation_score":user.reputation_score,"uploads":db.query(Document).filter_by(uploader_id=user.id).count(),"verified_resources":db.query(Document).filter_by(uploader_id=user.id,verification_status="VERIFIED").count()}

def document_json(doc: Document, db: Session, current_user_id: int | None = None):
    votes = db.query(Vote).filter_by(document_id=doc.id).all()
    return {"id":doc.id,"title":doc.title,"description":doc.description,"subject":doc.subject,"department":doc.department,"year":doc.year,"semester":doc.semester,"unit":doc.unit,"topic":doc.topic,"resource_type":doc.resource_type,"original_filename":doc.original_filename,"verification_status":doc.verification_status,"uploader_id":doc.uploader_id,"uploader_name":doc.uploader.name if doc.uploader else "Student","upload_date":doc.upload_date.isoformat(),"view_count":doc.view_count,"upvote_count":doc.upvote_count,"downvote_count":doc.downvote_count,"my_vote":next((v.value for v in votes if v.user_id == current_user_id),0),"chunk_count":db.query(DocumentChunk).filter_by(document_id=doc.id).count()}

@app.post("/api/documents", status_code=201)
def upload_document(file: UploadFile = File(...), title: str = Form(...), description: str = Form(""), subject: str = Form("General"), department: str = Form("CSE"), year: int = Form(1), semester: int = Form(1), unit: str = Form(""), topic: str = Form(""), resource_type: str = Form("Study Materials"), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not title.strip(): raise HTTPException(422, "Title is required.")
    doc = Document(title=title.strip(), description=description, subject=subject, department=department, year=year, semester=semester, unit=unit, topic=topic, resource_type=resource_type, file_path="pending", original_filename=(file.filename or "document.pdf")[:255], uploader_id=user.id)
    db.add(doc); db.commit(); db.refresh(doc)
    try:
        path, pages = save_and_extract(file, doc.id); doc.file_path = path; db.commit()
        chunk_count = embed_document_chunks(db, doc, pages) if settings.gemini_api_key else 0
        db.add(Activity(user_id=user.id, document_id=doc.id, action="uploaded resource")); user.reputation_score += 10; db.commit()
        result = document_json(doc, db, user.id); result["processing"] = "ready" if chunk_count else "text extracted; embeddings pending GEMINI_API_KEY"; result["chunks_created"] = chunk_count
        return result
    except HTTPException:
        db.delete(doc); db.commit(); raise
    except Exception as exc:
        # Preserve the uploaded PDF and resource record so an embedding outage does not lose student work.
        db.add(Activity(user_id=user.id, document_id=doc.id, action="uploaded resource; processing needs retry")); user.reputation_score += 10; db.commit()
        return {**document_json(doc, db, user.id), "processing":"failed", "processing_message":f"PDF saved, but indexing failed: {exc}. Check Gemini configuration and retry later."}

@app.get("/api/documents")
def list_documents(q: str = "", subject: str = "", department: str = "", semester: int | None = None, year: int | None = None, resource_type: str = "", topic: str = "", sort: str = "newest", limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Document).join(User, Document.uploader_id == User.id)
    if q.strip():
        term = f"%{q.strip()}%"; query = query.filter(or_(Document.title.ilike(term), Document.description.ilike(term), Document.subject.ilike(term), Document.topic.ilike(term), Document.resource_type.ilike(term)))
    if subject: query = query.filter(Document.subject.ilike(f"%{subject}%"))
    if department: query = query.filter(Document.department.ilike(f"%{department}%"))
    if semester: query = query.filter(Document.semester == semester)
    if year: query = query.filter(Document.year == year)
    if resource_type: query = query.filter(Document.resource_type == resource_type)
    if topic: query = query.filter(Document.topic.ilike(f"%{topic}%"))
    if sort == "upvoted": query = query.order_by(Document.upvote_count.desc(), Document.upload_date.desc())
    elif sort == "viewed": query = query.order_by(Document.view_count.desc(), Document.upload_date.desc())
    else: query = query.order_by(Document.upload_date.desc())
    total = query.count(); docs = query.offset(offset).limit(limit).all()
    return {"items":[document_json(d, db, user.id) for d in docs], "total":total, "limit":limit, "offset":offset}

@app.get("/api/documents/{document_id}")
def get_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = db.get(Document, document_id)
    if not doc: raise HTTPException(404, "Resource not found")
    doc.view_count += 1; db.add(Activity(user_id=user.id, document_id=doc.id, action="viewed resource")); db.commit()
    return document_json(doc, db, user.id)

@app.get("/api/documents/{document_id}/file")
def document_file(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from fastapi.responses import FileResponse
    doc = db.get(Document, document_id)
    if not doc: raise HTTPException(404, "Resource not found")
    path = Path(doc.file_path)
    if not path.is_file(): raise HTTPException(404, "PDF file is missing from local storage")
    return FileResponse(path, media_type="application/pdf", filename=doc.original_filename, content_disposition_type="inline")

@app.delete("/api/documents/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = db.get(Document, document_id)
    if not doc: raise HTTPException(404, "Resource not found")
    if doc.uploader_id != user.id and user.role != "admin": raise HTTPException(403, "You can only delete your own resources.")
    Path(doc.file_path).unlink(missing_ok=True) if doc.file_path != "pending" else None
    db.delete(doc); db.commit(); return {"message":"Resource deleted"}

@app.post("/api/documents/{document_id}/vote")
def vote_document(document_id: int, payload: VoteIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = db.get(Document, document_id)
    if not doc: raise HTTPException(404, "Resource not found")
    vote = db.query(Vote).filter_by(document_id=document_id,user_id=user.id).first()
    if vote:
        if vote.value == payload.value: return {"message":"Vote already recorded", "vote":vote.value}
        if vote.value == 1: doc.upvote_count = max(0, doc.upvote_count - 1)
        else: doc.downvote_count = max(0, doc.downvote_count - 1)
        vote.value = payload.value
    else:
        vote = Vote(document_id=document_id,user_id=user.id,value=payload.value); db.add(vote)
    if payload.value == 1: doc.upvote_count += 1; doc.uploader.reputation_score += 2
    else: doc.downvote_count += 1
    db.commit(); return {"message":"Vote saved", "vote":payload.value,"upvote_count":doc.upvote_count,"downvote_count":doc.downvote_count}

@app.delete("/api/documents/{document_id}/vote")
def remove_vote(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    vote = db.query(Vote).filter_by(document_id=document_id,user_id=user.id).first()
    if not vote: return {"message":"No vote to remove"}
    doc = db.get(Document, document_id)
    if vote.value == 1: doc.upvote_count = max(0,doc.upvote_count-1)
    else: doc.downvote_count = max(0,doc.downvote_count-1)
    db.delete(vote); db.commit(); return {"message":"Vote removed"}

@app.get("/api/documents/{document_id}/comments")
def get_comments(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not db.get(Document, document_id): raise HTTPException(404,"Resource not found")
    comments = db.query(Comment).filter_by(document_id=document_id).order_by(Comment.created_at.desc()).all()
    return [{"id":c.id,"body":c.body,"user_id":c.user_id,"author":c.author.name,"created_at":c.created_at.isoformat()} for c in comments]

@app.post("/api/documents/{document_id}/comments", status_code=201)
def add_comment(document_id: int, payload: CommentIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = db.get(Document,document_id)
    if not doc: raise HTTPException(404,"Resource not found")
    comment = Comment(document_id=document_id,user_id=user.id,body=payload.body.strip()); db.add(comment); user.reputation_score += 3; db.add(Activity(user_id=user.id,document_id=document_id,action="commented")); db.commit(); db.refresh(comment)
    return {"id":comment.id,"body":comment.body,"user_id":user.id,"author":user.name,"created_at":comment.created_at.isoformat()}

@app.delete("/api/comments/{comment_id}")
def delete_comment(comment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.get(Comment,comment_id)
    if not c: raise HTTPException(404,"Comment not found")
    if c.user_id != user.id and user.role != "admin": raise HTTPException(403,"You can only delete your own comments")
    db.delete(c); db.commit(); return {"message":"Comment deleted"}

@app.post("/api/documents/{document_id}/report", status_code=201)
def report_document(document_id: int, payload: ReportIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not db.get(Document,document_id): raise HTTPException(404,"Resource not found")
    report = Report(document_id=document_id,reporter_id=user.id,reason=payload.reason,details=payload.details); db.add(report); db.commit(); return {"message":"Report submitted for review"}

@app.post("/api/documents/{document_id}/save")
def save_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not db.get(Document,document_id): raise HTTPException(404,"Resource not found")
    if not db.query(SavedDocument).filter_by(document_id=document_id,user_id=user.id).first(): db.add(SavedDocument(document_id=document_id,user_id=user.id)); db.commit()
    return {"message":"Resource saved"}

@app.delete("/api/documents/{document_id}/save")
def unsave_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(SavedDocument).filter_by(document_id=document_id,user_id=user.id).first()
    if row: db.delete(row); db.commit()
    return {"message":"Resource removed from saved list"}

@app.get("/api/saved")
def saved_documents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(SavedDocument).filter_by(user_id=user.id).order_by(SavedDocument.created_at.desc()).all()
    return [document_json(db.get(Document,r.document_id),db,user.id) for r in rows if db.get(Document,r.document_id)]

@app.post("/api/documents/{document_id}/ask")
def ask_document(document_id: int, payload: AskIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = db.get(Document,document_id)
    if not doc: raise HTTPException(404,"Resource not found")
    try: result = answer_question(db,doc,payload.question,payload.selected_text)
    except RAGError as exc: raise HTTPException(503,str(exc))
    session = db.query(ChatSession).filter_by(document_id=document_id,user_id=user.id).first()
    if not session: session = ChatSession(document_id=document_id,user_id=user.id); db.add(session); db.commit(); db.refresh(session)
    db.add(ChatMessage(session_id=session.id,role="user",content=payload.question))
    db.add(ChatMessage(session_id=session.id,role="assistant",content=result["answer"],sources_json=json.dumps(result["sources"])))
    db.add(Activity(user_id=user.id,document_id=document_id,action="asked AI question")); db.commit()
    return {**result,"session_id":session.id}

@app.get("/api/documents/{document_id}/chat")
def get_chat(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = db.query(ChatSession).filter_by(document_id=document_id,user_id=user.id).first()
    if not session: return {"messages":[]}
    msgs = db.query(ChatMessage).filter_by(session_id=session.id).order_by(ChatMessage.created_at.asc()).all()
    return {"session_id":session.id,"messages":[{"id":m.id,"role":m.role,"content":m.content,"sources":json.loads(m.sources_json or "[]"),"created_at":m.created_at.isoformat()} for m in msgs]}

@app.delete("/api/documents/{document_id}/chat")
def clear_chat(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = db.query(ChatSession).filter_by(document_id=document_id,user_id=user.id).first()
    if session: db.delete(session); db.commit()
    return {"message":"Conversation cleared"}

@app.get("/api/search/semantic")
def semantic_search(q: str = Query(min_length=2), limit: int = Query(10,ge=1,le=30), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        vector = embed_text(q)
        chunks = db.query(DocumentChunk).filter(DocumentChunk.embedding.is_not(None)).order_by(DocumentChunk.embedding.cosine_distance(vector)).limit(limit).all()
    except RAGError as exc: raise HTTPException(503,str(exc))
    ids = list(dict.fromkeys(c.document_id for c in chunks)); docs = [db.get(Document,i) for i in ids]
    return {"items":[document_json(d,db,user.id) for d in docs if d],"matched_chunks":[{"document_id":c.document_id,"page":c.page_number,"snippet":c.chunk_text[:280]} for c in chunks]}

@app.get("/api/search")
def normal_search(q: str = Query(min_length=1), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    term=f"%{q.strip()}%"; docs=db.query(Document).filter(or_(Document.title.ilike(term),Document.description.ilike(term),Document.subject.ilike(term),Document.topic.ilike(term),Document.resource_type.ilike(term))).order_by(Document.upload_date.desc()).limit(50).all()
    return {"items":[document_json(d,db,user.id) for d in docs],"total":len(docs)}

@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    docs=db.query(Document).filter_by(uploader_id=user.id).all(); saved=db.query(SavedDocument).filter_by(user_id=user.id).count(); recent=db.query(Activity).filter_by(user_id=user.id).order_by(Activity.created_at.desc()).limit(8).all()
    upvotes=sum(d.upvote_count for d in docs)
    recommended=db.query(Document).filter(Document.department.ilike(f"%{user.department}%"),Document.uploader_id != user.id).order_by(Document.upvote_count.desc()).limit(5).all()
    return {"stats":{"uploaded_resources":len(docs),"saved_resources":saved,"upvotes_received":upvotes,"reputation_score":user.reputation_score,"verified_resources":sum(d.verification_status=="VERIFIED" for d in docs)},"recent_activity":[{"action":a.action,"document_id":a.document_id,"created_at":a.created_at.isoformat()} for a in recent],"recommended_resources":[document_json(d,db,user.id) for d in recommended]}

@app.get("/api/admin/users")
def admin_users(db: Session = Depends(get_db), admin: User = Depends(get_admin)):
    return [{"id":u.id,"name":u.name,"email":u.email,"role":u.role,"department":u.department,"reputation_score":u.reputation_score,"uploads":db.query(Document).filter_by(uploader_id=u.id).count()} for u in db.query(User).order_by(User.created_at.desc()).all()]

@app.get("/api/admin/documents")
def admin_documents(db: Session = Depends(get_db), admin: User = Depends(get_admin)):
    return [document_json(d,db,admin.id) for d in db.query(Document).order_by(Document.upload_date.desc()).all()]

@app.patch("/api/admin/documents/{document_id}/verify")
def admin_verify(document_id: int, payload: VerifyIn, db: Session = Depends(get_db), admin: User = Depends(get_admin)):
    doc=db.get(Document,document_id)
    if not doc: raise HTTPException(404,"Resource not found")
    doc.verification_status=payload.status
    if payload.status == "VERIFIED": doc.uploader.reputation_score += 10
    db.commit(); return document_json(doc,db,admin.id)

@app.delete("/api/admin/documents/{document_id}")
def admin_delete_document(document_id: int, db: Session = Depends(get_db), admin: User = Depends(get_admin)):
    doc=db.get(Document,document_id)
    if not doc: raise HTTPException(404,"Resource not found")
    if doc.file_path != "pending": Path(doc.file_path).unlink(missing_ok=True)
    db.delete(doc); db.commit(); return {"message":"Resource deleted"}

@app.get("/api/admin/reports")
def admin_reports(db: Session = Depends(get_db), admin: User = Depends(get_admin)):
    rows=db.query(Report).order_by(Report.created_at.desc()).all()
    return [{"id":r.id,"document_id":r.document_id,"title":db.get(Document,r.document_id).title if db.get(Document,r.document_id) else "Deleted resource","reporter_id":r.reporter_id,"reason":r.reason,"details":r.details,"status":r.status,"created_at":r.created_at.isoformat()} for r in rows]

@app.patch("/api/admin/reports/{report_id}")
def update_report(report_id: int, status: str = Query(pattern="^(OPEN|REVIEWED|DISMISSED)$"), db: Session = Depends(get_db), admin: User = Depends(get_admin)):
    report=db.get(Report,report_id)
    if not report: raise HTTPException(404,"Report not found")
    report.status=status; db.commit(); return {"message":"Report updated","status":status}

@app.get("/api/admin/analytics")
def admin_analytics(db: Session = Depends(get_db), admin: User = Depends(get_admin)):
    docs=db.query(Document).all(); users=db.query(User).count()
    subjects={}
    for d in docs: subjects[d.subject]=subjects.get(d.subject,0)+1
    top_users=sorted(db.query(User).all(),key=lambda u:u.reputation_score,reverse=True)[:5]
    return {"total_users":users,"total_documents":len(docs),"total_verified_documents":sum(d.verification_status=="VERIFIED" for d in docs),"total_questions_asked":db.query(ChatMessage).filter_by(role="user").count(),"popular_subjects":[{"subject":k,"count":v} for k,v in sorted(subjects.items(),key=lambda x:x[1],reverse=True)[:8]],"most_viewed":[{"title":d.title,"views":d.view_count} for d in sorted(docs,key=lambda x:x.view_count,reverse=True)[:5]],"top_contributors":[{"name":u.name,"reputation_score":u.reputation_score} for u in top_users],"recent_uploads":[document_json(d,db,admin.id) for d in sorted(docs,key=lambda x:x.upload_date,reverse=True)[:8]]}
