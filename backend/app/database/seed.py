"""Create safe local demo accounts/resources. Run with: python -m app.database.seed"""
from pathlib import Path

from sqlalchemy.orm import Session
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app.database.session import Base, engine, SessionLocal
from app.core.security import hash_password
from app.core.config import settings
from app.models.models import User, Document


# Use valid email domains instead of the reserved .local domain.
DEMO_ADMIN_EMAIL = "admin@academichub.com"
DEMO_ADMIN_PASSWORD = "AdminDemo123!"
DEMO_STUDENT_EMAIL = "student@academichub.com"
DEMO_STUDENT_PASSWORD = "StudentDemo123!"

SAMPLE_TEXT = [
    (
        "DBMS Unit 3: Database Normalization",
        "Normalization organizes relational tables to reduce redundancy and avoid update anomalies. First Normal Form (1NF) requires each attribute to contain an atomic value and each row to be unique. Second Normal Form (2NF) requires 1NF and removes partial dependency of a non-prime attribute on part of a candidate key. Third Normal Form (3NF) requires 2NF and removes transitive dependencies of non-prime attributes on candidate keys. BCNF is stronger: every determinant must be a candidate key.",
        "DBMS",
        "Lecture Notes",
        "Normalization",
    ),
    (
        "Java OOP Quick Revision",
        "Encapsulation bundles data and methods inside a class and controls access with modifiers. Inheritance allows a class to reuse and extend another class. Polymorphism allows one interface or method name to have different behavior, including method overloading at compile time and overriding at runtime. Abstraction exposes essential behavior while hiding implementation details, commonly through abstract classes and interfaces.",
        "Java",
        "Study Materials",
        "Object-Oriented Programming",
    ),
    (
        "Data Structures: Searching and Sorting",
        "Linear search checks elements sequentially and takes O(n) time in the worst case. Binary search repeatedly halves the search interval and takes O(log n) time, but requires sorted data. Bubble sort repeatedly swaps adjacent out-of-order elements and is O(n squared) in the average and worst cases. Merge sort divides a list, sorts the parts, and merges them in O(n log n) time, with additional memory for merging.",
        "Data Structures",
        "Study Materials",
        "Searching and Sorting",
    ),
]


def make_pdf(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=letter)
    _, height = letter

    for title, body, *_ in SAMPLE_TEXT:
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(54, height - 70, title)
        pdf.setFont("Helvetica", 11)

        y = height - 110
        words = body.split()
        lines = []
        line = ""

        for word in words:
            if len(line) + len(word) + 1 > 90:
                lines.append(line)
                line = word
            else:
                line = (line + " " + word).strip()

        if line:
            lines.append(line)

        for text_line in lines:
            pdf.drawString(54, y, text_line)
            y -= 19

        pdf.showPage()

    pdf.save()


def get_or_create_user(
    db: Session,
    *,
    email: str,
    name: str,
    password: str,
    department: str,
    role: str,
    year: int = 1,
    semester: int = 1,
    reputation_score: int = 0,
):
    """Create a demo user if missing; otherwise update its password and role."""
    user = db.query(User).filter_by(email=email).first()

    if user is None:
        user = User(
            name=name,
            email=email,
            password_hash=hash_password(password),
            department=department,
            role=role,
            year=year,
            semester=semester,
            reputation_score=reputation_score,
        )
        db.add(user)
        db.flush()
    else:
        # Keep existing records and ensure these demo credentials work.
        user.name = name
        user.password_hash = hash_password(password)
        user.department = department
        user.role = role
        user.year = year
        user.semester = semester
        user.reputation_score = reputation_score

    return user


def main():
    # The pgvector extension must already be installed for this PostgreSQL version.
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")

    Base.metadata.create_all(engine)
    db: Session = SessionLocal()

    try:
        # Create/update demo accounts using valid email addresses.
        admin = get_or_create_user(
            db,
            email=DEMO_ADMIN_EMAIL,
            name="Demo Administrator",
            password=DEMO_ADMIN_PASSWORD,
            department="Administration",
            role="admin",
            reputation_score=100,
        )

        student = get_or_create_user(
            db,
            email=DEMO_STUDENT_EMAIL,
            name="Demo Student",
            password=DEMO_STUDENT_PASSWORD,
            department="CSE",
            role="student",
            year=3,
            semester=5,
            reputation_score=24,
        )
        db.commit()

        sample_dir = Path(settings.upload_dir).resolve() / "samples"
        sample_pdf = sample_dir / "academic-samples.pdf"
        make_pdf(sample_pdf)

        existing_titles = {doc.title for doc in db.query(Document).all()}

        for index, (title, body, subject, kind, topic) in enumerate(SAMPLE_TEXT):
            if title in existing_titles:
                continue

            db.add(
                Document(
                    title=title,
                    description=body[:200] + "…",
                    subject=subject,
                    department="CSE",
                    year=3,
                    semester=5,
                    unit="Unit 3",
                    topic=topic,
                    resource_type=kind,
                    file_path=str(sample_pdf),
                    original_filename=sample_pdf.name,
                    verification_status="VERIFIED" if index == 0 else "UNVERIFIED",
                    uploader_id=student.id,
                    upvote_count=12 - index,
                    view_count=40 - index * 7,
                )
            )

        db.commit()

        print("Demo data ready.")
        print(f"Admin: {DEMO_ADMIN_EMAIL} / {DEMO_ADMIN_PASSWORD}")
        print(f"Demo student: {DEMO_STUDENT_EMAIL} / {DEMO_STUDENT_PASSWORD}")
        print(
            "Note: demo documents contain sample PDF text. "
            "Document-based RAG requires GEMINI_API_KEY and indexing/re-uploading "
            "documents if chunks are missing."
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
