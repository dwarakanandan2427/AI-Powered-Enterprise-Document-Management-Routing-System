from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import current_user
from ..models import Membership, User, Workspace
from ..permissions import has_role
from ..schemas import MemberIn, WorkspaceIn, WorkspaceOut

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceOut, status_code=201)
def create(body: WorkspaceIn, request: Request, db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    if db.scalar(select(Workspace).where(Workspace.name == body.name)):
        raise HTTPException(409, "Workspace name already exists")
    ws = Workspace(name=body.name, description=body.description)
    db.add(ws)
    db.flush()
    db.add(Membership(user_id=user.id, workspace_id=ws.id, role="admin"))
    audit.log(db, request, user, "workspace.create", "workspace", ws.id, ws.id, name=ws.name)
    db.commit()
    return WorkspaceOut(id=ws.id, name=ws.name, description=ws.description, role="admin")


@router.get("", response_model=list[WorkspaceOut])
def mine(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.execute(select(Workspace, Membership.role).join(
        Membership, Membership.workspace_id == Workspace.id).where(Membership.user_id == user.id)).all()
    return [WorkspaceOut(id=w.id, name=w.name, description=w.description, role=r) for w, r in rows]


@router.post("/{workspace_id}/members", status_code=201)
def add_member(workspace_id: int, body: MemberIn, request: Request, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    if not has_role(db, user, workspace_id, "admin"):
        audit.log(db, request, user, "access.denied", "workspace", workspace_id, workspace_id, op="add_member")
        db.commit()
        raise HTTPException(403, "Workspace admin required")
    target = db.scalar(select(User).where(User.email == body.email.lower()))
    if not target:
        raise HTTPException(404, "User not found")
    m = db.scalar(select(Membership).where(Membership.user_id == target.id,
                                           Membership.workspace_id == workspace_id))
    if m:
        m.role = body.role
    else:
        db.add(Membership(user_id=target.id, workspace_id=workspace_id, role=body.role))
    audit.log(db, request, user, "member.set", "workspace", workspace_id, workspace_id,
              target_user_id=target.id, role=body.role)
    db.commit()
    return {"user_id": target.id, "role": body.role}


@router.get("/{workspace_id}/members")
def members(workspace_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not has_role(db, user, workspace_id, "viewer"):
        raise HTTPException(404, "Workspace not found")
    rows = db.execute(select(User.id, User.email, Membership.role).join(
        Membership, Membership.user_id == User.id).where(Membership.workspace_id == workspace_id)).all()
    return [{"user_id": i, "email": e, "role": r} for i, e, r in rows]
