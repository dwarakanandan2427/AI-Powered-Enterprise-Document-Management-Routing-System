# DocuFlow — AI-Powered Enterprise Document Management & Routing System

Stack: Python, FastAPI, PostgreSQL, MinIO, JWT, ChromaDB, LangGraph, Anthropic API, Docker.

## Setup (everything you need)
1. Install Docker Desktop (nothing else: Python, Postgres, MinIO, Chroma all run in containers).
2. Get an Anthropic API key from console.anthropic.com. (Without one the app still runs with a heuristic fallback.)
3. `cp .env.example .env` and paste the key; set JWT_SECRET to a long random string.
4. `docker compose up --build`
5. Open http://localhost:8000/docs (API) and http://localhost:9001 (MinIO console, minioadmin/minioadmin).
The first upload downloads Chroma's ~80 MB embedding model once; that is normal.

## Try it (Swagger UI: click Authorize after login)
1. POST /auth/register, POST /auth/login
2. POST /workspaces  {"name":"Legal","description":"contracts, NDAs, compliance"}; make a second, e.g. "Finance"
3. POST /documents (file only, no workspace_id) -> the agent summarizes, classifies, tags, routes
4. POST /workspaces/{id}/members to add a second user as viewer/editor
5. PUT /documents/{id}/acl to restrict one document to specific users
6. POST /qa {"question": "..."}  (RAG, only over documents you can read)
7. GET /audit?workspace_id=1 (workspace admins only)

## Design
- Roles per workspace: viewer < editor < admin. Document visibility: `workspace` or `restricted` (owner, ACL grants, workspace admins).
- All checks are server-side in `app/permissions.py`. Unreadable docs return 404 (existence not leaked); denied attempts are audit-logged.
- RAG: allowed document IDs are computed from PostgreSQL first, then passed as a filter to ChromaDB, so retrieval can never return text the user can't read.
- Agent (LangGraph): analyze -> route. It can only route into workspaces where the uploader is editor/admin; explicit workspace choice always wins. Document text is treated as untrusted (prompt-injection-aware prompts).
- Versions: every upload creates a new MinIO object; only the latest version is indexed for Q&A.

## Tests
`pip install -r requirements.txt && pytest` (uses SQLite + fakes for MinIO/Chroma, no Docker needed).
