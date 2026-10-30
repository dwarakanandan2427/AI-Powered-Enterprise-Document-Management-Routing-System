import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import String, cast, delete, func, or_, select
from sqlalchemy.orm import Session

from .. import agent, audit, extract, permissions as perm, storage, vector
from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..models import Document, DocumentACL, DocumentVersion, Membership, User, Workspace
from ..schemas import ACLIn, DocumentOut, VersionOut

router = APIRouter(prefix="/documents", tags=["documents"])


def _read_upload(file: UploadFile) -> bytes:
    data = file.file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB")
    if not data:
        raise HTTPException(422, "Empty file")
    return data


def _get_readable(db: Session, request: Request, user: User, doc_id: int) -> Document:
    doc = db.get(Document, doc_id)
    if not doc or doc.status != "active":
        raise HTTPException(404, "Document not found")
    if not perm.can_read(db, user, doc):
        audit.log(db, request, user, "access.denied", "document", doc.id, doc.workspace_id, op="read")
        db.commit()
        raise HTTPException(404, "Document not found")  # 404, not 403: don't reveal existence
    return doc


def _get_writable(db: Session, request: Request, user: User, doc_id: int) -> Document:
    doc = _get_readable(db, request, user, doc_id)
    if not perm.can_write(db, user, doc):
        audit.log(db, request, user, "access.denied", "document", doc.id, doc.workspace_id, op="write")
        db.commit()
        raise HTTPException(403, "You do not have write access to this document")
    return doc


def _store_version(db: Session, doc: Document, version: int, filename: str, data: bytes,
                   content_type: str, user: User) -> None:
    key = f"{doc.workspace_id}/{doc.id}/v{version}/{uuid.uuid4().hex}-{filename}"
    storage.put(key, data, content_type)
    db.add(DocumentVersion(document_id=doc.id, version=version, object_key=key, filename=filename,
                           size=len(data), uploaded_by=user.id))


@router.post("", response_model=DocumentOut, status_code=201)
def upload(request: Request, file: UploadFile = File(...), workspace_id: int | None = Form(None),
           title: str | None = Form(None), db: Session = Depends(get_db), user: User = Depends(current_user)):
    data = _read_upload(file)
    filename = file.filename or "upload"

    rows = db.execute(select(Workspace, Membership.role).join(
        Membership, Membership.workspace_id == Workspace.id).where(Membership.user_id == user.id)).all()
    candidates = [{"id": w.id, "name": w.name, "description": w.description}
                  for w, r in rows if perm.RANK[r] >= perm.RANK["editor"]]
    if not candidates:
        raise HTTPException(403, "You need editor access to at least one workspace")
    if workspace_id is not None and workspace_id not in {c["id"] for c in candidates}:
        audit.log(db, request, user, "access.denied", "workspace", workspace_id, workspace_id, op="upload")
        db.commit()
        raise HTTPException(403, "You cannot upload to this workspace")

    text = extract.extract_text(filename, data)
    if not text.strip():
        raise HTTPException(422, "No extractable text in file")

    result = agent.run(filename, text, candidates, workspace_id)
    doc = Document(workspace_id=result["workspace_id"], owner_id=user.id, title=title or filename,
                   filename=filename, content_type=file.content_type or "", category=result["category"],
                   summary=result["summary"], tags=result["tags"], routing_reason=result["reason"])
    db.add(doc)
    db.flush()
    _store_version(db, doc, 1, filename, data, doc.content_type, user)
    vector.index_document(doc.id, doc.workspace_id, 1, doc.title, text)
    audit.log(db, request, user, "document.upload", "document", doc.id, doc.workspace_id,
              auto_routed=workspace_id is None, category=doc.category, version=1)
    db.commit()
    return doc


@router.get("", response_model=list[DocumentOut])
def search(request: Request, q: str | None = None, workspace_id: int | None = None,
           category: str | None = None, tag: str | None = None, limit: int = 50, offset: int = 0,
           db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(Document).where(perm.readable_filter(user))
    if workspace_id:
        stmt = stmt.where(Document.workspace_id == workspace_id)
    if category:
        stmt = stmt.where(Document.category == category)
    if tag:
        stmt = stmt.where(cast(Document.tags, String).ilike(f'%"{tag.lower()}"%'))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Document.title.ilike(like), Document.summary.ilike(like),
                              Document.filename.ilike(like)))
    rows = db.scalars(stmt.order_by(Document.updated_at.desc()).limit(min(limit, 200)).offset(offset)).all()
    audit.log(db, request, user, "document.search", workspace_id=workspace_id, q=q, results=len(rows))
    db.commit()
    return rows


@router.get("/{doc_id}", response_model=DocumentOut)
def get_one(doc_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = _get_readable(db, request, user, doc_id)
    audit.log(db, request, user, "document.view", "document", doc.id, doc.workspace_id)
    db.commit()
    return doc


@router.get("/{doc_id}/versions", response_model=list[VersionOut])
def versions(doc_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = _get_readable(db, request, user, doc_id)
    return db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == doc.id)
                      .order_by(DocumentVersion.version.desc())).all()


@router.post("/{doc_id}/versions", response_model=DocumentOut, status_code=201)
def new_version(doc_id: int, request: Request, file: UploadFile = File(...),
                db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = _get_writable(db, request, user, doc_id)
    data = _read_upload(file)
    filename = file.filename or doc.filename
    text = extract.extract_text(filename, data)
    if not text.strip():
        raise HTTPException(422, "No extractable text in file")

    ws = db.get(Workspace, doc.workspace_id)
    result = agent.run(filename, text, [{"id": ws.id, "name": ws.name, "description": ws.description}], ws.id)
    doc.current_version += 1
    doc.filename, doc.category = filename, result["category"]
    doc.summary, doc.tags, doc.routing_reason = result["summary"], result["tags"], result["reason"]
    _store_version(db, doc, doc.current_version, filename, data, file.content_type or "", user)
    vector.index_document(doc.id, doc.workspace_id, doc.current_version, doc.title, text)
    audit.log(db, request, user, "document.version", "document", doc.id, doc.workspace_id,
              version=doc.current_version)
    db.commit()
    return doc


@router.get("/{doc_id}/download")
def download(doc_id: int, request: Request, version: int | None = None,
             db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = _get_readable(db, request, user, doc_id)
    v = db.scalar(select(DocumentVersion).where(
        DocumentVersion.document_id == doc.id, DocumentVersion.version == (version or doc.current_version)))
    if not v:
        raise HTTPException(404, "Version not found")
    audit.log(db, request, user, "document.download", "document", doc.id, doc.workspace_id, version=v.version)
    db.commit()
    return StreamingResponse(storage.stream(v.object_key), media_type="application/octet-stream",
                             headers={"Content-Disposition": f'attachment; filename="{v.filename}"'})


@router.put("/{doc_id}/acl", response_model=DocumentOut)
def set_acl(doc_id: int, body: ACLIn, request: Request, db: Session = Depends(get_db),
            user: User = Depends(current_user)):
    doc = _get_readable(db, request, user, doc_id)
    is_ws_admin = perm.has_role(db, user, doc.workspace_id, "admin")
    if not (is_ws_admin or doc.owner_id == user.id):
        audit.log(db, request, user, "access.denied", "document", doc.id, doc.workspace_id, op="acl")
        db.commit()
        raise HTTPException(403, "Only the owner or a workspace admin can change permissions")
    member_ids = set(db.scalars(select(Membership.user_id).where(Membership.workspace_id == doc.workspace_id)))
    if any(e.user_id not in member_ids for e in body.entries):
        raise HTTPException(422, "All users must be members of the document's workspace")
    db.execute(delete(DocumentACL).where(DocumentACL.document_id == doc.id))
    for e in body.entries:
        db.add(DocumentACL(document_id=doc.id, user_id=e.user_id, permission=e.permission))
    doc.visibility = body.visibility
    audit.log(db, request, user, "document.acl_update", "document", doc.id, doc.workspace_id,
              visibility=body.visibility, entries=[e.model_dump() for e in body.entries])
    db.commit()
    return doc


@router.delete("/{doc_id}", status_code=204)
def remove(doc_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = _get_writable(db, request, user, doc_id)
    doc.status = "deleted"  # soft delete keeps history for compliance; objects stay in MinIO
    vector.delete_document(doc.id)
    audit.log(db, request, user, "document.delete", "document", doc.id, doc.workspace_id)
    db.commit()
