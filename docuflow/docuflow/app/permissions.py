"""All authorization decisions live here and are enforced server-side."""
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .models import Document, DocumentACL, Membership, User

RANK = {"viewer": 1, "editor": 2, "admin": 3}


def workspace_role(db: Session, user: User, workspace_id: int) -> str | None:
    return db.scalar(select(Membership.role).where(
        Membership.user_id == user.id, Membership.workspace_id == workspace_id))


def has_role(db: Session, user: User, workspace_id: int, minimum: str) -> bool:
    role = workspace_role(db, user, workspace_id)
    return role is not None and RANK[role] >= RANK[minimum]


def _acl(db: Session, user: User, doc: Document) -> str | None:
    return db.scalar(select(DocumentACL.permission).where(
        DocumentACL.document_id == doc.id, DocumentACL.user_id == user.id))


def can_read(db: Session, user: User, doc: Document) -> bool:
    role = workspace_role(db, user, doc.workspace_id)
    if role is None:
        return False
    if doc.visibility == "workspace" or role == "admin" or doc.owner_id == user.id:
        return True
    return _acl(db, user, doc) is not None


def can_write(db: Session, user: User, doc: Document) -> bool:
    role = workspace_role(db, user, doc.workspace_id)
    if role is None:
        return False
    if role == "admin" or doc.owner_id == user.id:
        return True
    if doc.visibility == "workspace":
        return RANK[role] >= RANK["editor"]
    return _acl(db, user, doc) == "write"


def readable_filter(user: User):
    """SQL version of can_read, for listing/search/RAG so unreadable rows never leave the DB."""
    member_ws = select(Membership.workspace_id).where(Membership.user_id == user.id)
    admin_ws = select(Membership.workspace_id).where(
        Membership.user_id == user.id, Membership.role == "admin")
    acl_docs = select(DocumentACL.document_id).where(DocumentACL.user_id == user.id)
    return and_(
        Document.status == "active",
        Document.workspace_id.in_(member_ws),
        or_(
            Document.visibility == "workspace",
            Document.owner_id == user.id,
            Document.id.in_(acl_docs),
            Document.workspace_id.in_(admin_ws),
        ),
    )
