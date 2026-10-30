from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog, User


def log(db: Session, request: Request | None, user: User | None, action: str,
        resource_type: str = "", resource_id: int | None = None,
        workspace_id: int | None = None, **details) -> None:
    """Adds an audit row to the session; the caller commits."""
    db.add(AuditLog(
        user_id=user.id if user else None,
        workspace_id=workspace_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip=(request.client.host if request and request.client else ""),
    ))
