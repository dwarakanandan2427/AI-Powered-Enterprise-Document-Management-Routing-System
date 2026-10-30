from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import models  # noqa: F401  (register tables)
from . import storage
from .db import Base, engine
from .routers import audit_log, auth, documents, qa, workspaces


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    storage.ensure_bucket()
    yield


app = FastAPI(title="DocuFlow - Enterprise Document Management & Routing", lifespan=lifespan)
for r in (auth.router, workspaces.router, documents.router, qa.router, audit_log.router):
    app.include_router(r)


@app.get("/health")
def health():
    return {"status": "ok"}
