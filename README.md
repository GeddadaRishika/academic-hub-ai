# AcademicHub AI

A peer-to-peer academic knowledge hub built with React + Vite, FastAPI, PostgreSQL + pgvector, and Google Gemini. Students can upload PDF notes, discover resources, vote, comment, save resources, report issues, and ask questions grounded in document passages with page citations.

> **Honest scope note:** This is a runnable, production-style starter application with real database/API flows and a real Gemini/pgvector RAG implementation. It is not a security-audited production deployment. The demo seed creates sample resources for browsing; sample PDFs are not automatically indexed into embeddings. Configure Gemini and upload a real text-based PDF to exercise RAG end-to-end. OCR for scanned PDFs, email verification/password reset, threaded replies, Alembic migrations, background job processing, and production object storage are not included.

## Features

- JWT authentication, bcrypt password hashing, protected student/admin routes, profile editing.
- PDF upload validation, text extraction with page numbers, page-local chunking, Gemini embeddings, pgvector cosine similarity retrieval, grounded Gemini answers and page sources.
- Resource search/filter/sort, PDF preview, Ask the Doc chat history, optional selected-text context.
- Votes with per-user uniqueness, comments, reports, saved resources, contributor reputation, verification workflow and admin analytics.
- Responsive React/Tailwind-style SaaS interface, loading/empty/error states.

## Architecture

```text
React + Vite browser
    │ REST/JSON + JWT
    ▼
FastAPI API ─────────────── Local PDF storage
    │
    ├── SQLAlchemy ─────── PostgreSQL (users, resources, votes, comments, chats…)
    │                           └── pgvector (document chunk embeddings)
    │
    └── RAG service ────── Gemini embeddings + Gemini answer generation
```

### RAG workflow

```text
Upload PDF → Validate PDF → Extract text by page → Clean/chunk
   → Gemini embedding per chunk → Store chunk + page metadata + vector in pgvector

Question → Gemini query embedding → pgvector cosine similarity search (document scoped)
   → Top relevant passages with page numbers → Context + question sent to Gemini
   → Grounded answer + source page list → Persist conversation history
```

The model is instructed to say when the answer is not supported by retrieved material. A response is not considered grounded if retrieval is unavailable; the API returns a configuration/error message rather than silently using Gemini alone.

## Project structure

```text
academic-hub-ai/
├── backend/
│   ├── app/api/                 # reserved for route modules
│   ├── app/core/                # settings and JWT/password security
│   ├── app/database/            # SQLAlchemy session and demo seeder
│   ├── app/models/              # relational models + pgvector chunk model
│   ├── app/rag/                 # embedding, retrieval, grounded generation
│   ├── app/schemas/              # Pydantic validation
│   ├── app/services/             # PDF validation/extraction
│   ├── main.py                   # REST API
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
├── frontend/src/                 # React app, auth context, API client, styles
├── database/schema.sql
├── database/seed.sql
├── .gitignore
└── README.md
```

## Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL 15+ with pgvector installed
- A Google Gemini API key for embeddings and AI answers (optional for browsing/auth; required for RAG indexing and Ask the Doc)

## 1. PostgreSQL + pgvector setup

### macOS with Homebrew

Install PostgreSQL and pgvector (the exact package may depend on your PostgreSQL major version):

```bash
brew install postgresql@16
brew services start postgresql@16
brew install pgvector
```

If `pgvector` is not available from Homebrew on your system, use the official pgvector installation instructions for your PostgreSQL version: https://github.com/pgvector/pgvector.

Create a local role/database (run once):

```bash
psql postgres
```

At the `psql` prompt:

```sql
CREATE USER academic WITH PASSWORD 'academic';
CREATE DATABASE academic_hub OWNER academic;
\connect academic_hub
CREATE EXTENSION IF NOT EXISTS vector;
\q
```

If the role/database already exists, don't recreate it. You can alternatively use your own PostgreSQL credentials and update `DATABASE_URL`.

### Ubuntu/Debian (example for PostgreSQL 16)

Install PostgreSQL 16 and the matching pgvector package using your distribution's package repository, then start PostgreSQL:

```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl enable --now postgresql
```

Install the pgvector package matching your PostgreSQL major version (often named `postgresql-16-pgvector` on supported repositories). Then create the role/database and enable the extension using the SQL above. If the package isn't available, follow the pgvector upstream installation guide.

## 2. Configure environment variables

```bash
cd academic-hub-ai/backend
cp .env.example .env
```

Edit `backend/.env`:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy connection URL, e.g. `postgresql+psycopg://academic:academic@localhost:5432/academic_hub` |
| `GEMINI_API_KEY` | Google AI Studio Gemini API key; leave empty if testing non-AI flows only |
| `GEMINI_CHAT_MODEL` | Gemini text generation model (default `gemini-2.5-flash`) |
| `GEMINI_EMBED_MODEL` | Embedding model (default `gemini-embedding-001`, configured for 768 dimensions) |
| `JWT_SECRET_KEY` | Long, random secret for signing tokens; replace the development value |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT lifetime in minutes |
| `UPLOAD_DIR` | PDF storage directory; default `./uploads` relative to backend working directory |
| `MAX_UPLOAD_MB` | Upload size limit, default 20 MB |
| `CORS_ORIGINS` | Comma-separated allowed frontend origins, default `http://localhost:5173` |
| `DEMO_ADMIN_EMAIL` | Local demo admin email |
| `DEMO_ADMIN_PASSWORD` | Local demo admin password; change for any shared environment |

Never commit `.env`. The frontend does not receive the Gemini key.

## 3. Start the FastAPI backend

From the project root:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env  # if not already created; then edit it
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The API creates the pgvector extension and SQLAlchemy tables on startup, then creates the demo admin account if it doesn't exist. Swagger docs: http://127.0.0.1:8000/docs. Health check: http://127.0.0.1:8000/api/health.

### Optional demo data

In a second terminal, activate the same virtual environment and run:

```bash
cd academic-hub-ai/backend
source .venv/bin/activate
python -m app.database.seed
```

Demo accounts:

- Admin: `admin@academichub.local` / `AdminDemo123!` (or values in your `.env`)
- Student: `student@academichub.local` / `StudentDemo123!`

These are local development credentials only. Do not use them on a public deployment. Demo sample documents share a bundled PDF; the seed does not generate embeddings. For a real Ask the Doc test, upload a text-based PDF after setting `GEMINI_API_KEY`.

## 4. Start the React frontend

In another terminal:

```bash
cd academic-hub-ai/frontend
cp .env.example .env
npm install
npm run dev
```

Open http://localhost:5173. Set `VITE_API_URL` in `frontend/.env` if the API is running elsewhere. Restart Vite after editing environment variables.

## REST API overview

| Area | Endpoints |
|---|---|
| Auth | `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET/PATCH /api/users/me` |
| Resources | `POST/GET /api/documents`, `GET /api/documents/{id}`, `GET /api/documents/{id}/file`, `DELETE /api/documents/{id}` |
| Community | `POST/DELETE /api/documents/{id}/vote`, `GET/POST /api/documents/{id}/comments`, `DELETE /api/comments/{id}`, `POST /api/documents/{id}/report` |
| Saved/chat | `POST/DELETE /api/documents/{id}/save`, `GET /api/saved`, `POST /api/documents/{id}/ask`, `GET/DELETE /api/documents/{id}/chat` |
| Search/dashboard | `GET /api/search?q=...`, `GET /api/search/semantic?q=...`, `GET /api/dashboard` |
| Admin | `GET /api/admin/users`, `GET /api/admin/documents`, `PATCH /api/admin/documents/{id}/verify`, `DELETE /api/admin/documents/{id}`, `GET /api/admin/reports`, `PATCH /api/admin/reports/{id}?status=REVIEWED`, `GET /api/admin/analytics` |

All API routes except `/api/health`, registration, and login require a bearer JWT. Admin endpoints require an account with role `admin`.

## Database design

The SQLAlchemy schema includes `users`, `documents`, `document_chunks` (with `vector(768)` embeddings, page number and chunk index), `votes` (unique document/user pair), `comments`, `reports`, `saved_documents` (unique document/user pair), `chat_sessions`, `chat_messages`, and `activity`. Foreign keys and indexes support common lookups. `database/schema.sql` enables pgvector; the app creates the tables. For production, replace startup `create_all` with versioned Alembic migrations.

## Tests

```bash
cd backend
source .venv/bin/activate
pytest -q
```

Included tests cover password hashing/token creation and rejection of non-PDF uploads. The full authentication, database, upload, voting, authorization, and RAG integration suite should be expanded and run against a configured PostgreSQL/Gemini test environment before deployment. No external API success is assumed by the included tests.

## Security notes / before production

- Replace JWT and demo credentials; use managed secrets and HTTPS.
- Add rate limiting, email verification, password reset, audit logging, malware scanning, quotas, and background PDF indexing.
- Put PDFs in private object storage for multi-instance deployments; local disk is for development.
- Add Alembic migrations, structured logs, monitoring, database backups, and a dedicated integration-test database.
- Review upload permissions and content moderation policies. OCR for scanned PDFs is not currently included.
- Reputation rules are intentionally simple; production systems should prevent repeat-vote farming and award reputation transactionally.

## Screenshots

_Add application screenshots here after running the frontend locally._

## Future improvements

- OCR and asynchronous indexing jobs with processing-status tracking.
- Threaded comment replies, saved-resource recommendations, notifications, and richer admin moderation.
- Automated evaluation of retrieval quality, chunking strategies, and grounded-answer faithfulness.
- Alembic migrations, deployment manifests, observability, and object storage.
