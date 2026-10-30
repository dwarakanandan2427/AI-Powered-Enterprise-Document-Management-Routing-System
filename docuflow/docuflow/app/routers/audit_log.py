from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import permissions as perm
from ..db import get_db
from ..deps import current_user
from ..models import AuditLog, User
from ..schemas import AuditOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
def list_logs(workspace_id: int, action: str | None = None, limit: int = 100,
              db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not perm.has_role(db, user, workspace_id, "admin"):
        raise HTTPException(403, "Workspace admin required")
    stmt = select(AuditLog).where(AuditLog.workspace_id == workspace_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return db.scalars(stmt.order_by(AuditLog.id.desc()).limit(min(limit, 500))).all()
