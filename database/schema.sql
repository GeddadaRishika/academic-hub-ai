-- Run after creating the academic_hub database.
CREATE EXTENSION IF NOT EXISTS vector;
-- The application creates all SQLAlchemy tables on startup. This file records the
-- required extension and can be used as a starting point for Alembic migrations.
