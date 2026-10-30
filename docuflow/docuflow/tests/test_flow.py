import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["ANTHROPIC_API_KEY"] = ""

import pytest
from fastapi.testclient import TestClient

from app import storage, vector
from app.db import Base, engine
from app.main import app

FILES: dict[str, bytes] = {}
INDEX: dict[int, tuple[int, str]] = {}


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    FILES.clear(); INDEX.clear()
    monkeypatch.setattr(storage, "put", lambda k, d, c: FILES.__setitem__(k, d))
    monkeypatch.setattr(storage, "stream", lambda k: iter([FILES[k]]))
    monkeypatch.setattr(vector, "index_document",
                        lambda did, wid, v, t, text: INDEX.__setitem__(did, (wid, text)) or 1)
    monkeypatch.setattr(vector, "delete_document", lambda did: INDEX.pop(did, None))
    monkeypatch.setattr(vector, "search",
                        lambda q, ids, k: [{"text": INDEX[i][1], "document_id": i, "title": "t", "version": 1}
                                           for i in ids if i in INDEX][:k])
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)


c = TestClient(app)


def user(email):
    c.post("/auth/register", json={"email": email, "password": "password123"})
    t = c.post("/auth/login", data={"username": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {t}"}


def test_rbac_and_document_permissions():
    alice, bob, eve = user("a@x.com"), user("b@x.com"), user("e@x.com")
    ws = c.post("/workspaces", json={"name": "Legal", "description": "contracts"}, headers=alice).json()
    c.post(f"/workspaces/{ws['id']}/members", json={"email": "b@x.com", "role": "viewer"}, headers=alice)

    r = c.post("/documents", files={"file": ("nda.txt", b"This agreement between the parties...")},
               data={"workspace_id": ws["id"]}, headers=alice)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["category"] == "contract"

    # viewer can read, cannot upload or delete; outsider sees nothing
    assert c.get(f"/documents/{doc['id']}", headers=bob).status_code == 200
    assert c.post("/documents", files={"file": ("x.txt", b"hi")}, data={"workspace_id": ws["id"]},
                  headers=bob).status_code == 403
    assert c.delete(f"/documents/{doc['id']}", headers=bob).status_code == 403
    assert c.get(f"/documents/{doc['id']}", headers=eve).status_code == 404
    assert c.get("/documents", headers=eve).json() == []

    # restricted doc hides from viewer until granted via ACL
    bob_id = c.get("/auth/me", headers=bob).json()["id"]
    c.put(f"/documents/{doc['id']}/acl", json={"visibility": "restricted", "entries": []}, headers=alice)
    assert c.get(f"/documents/{doc['id']}", headers=bob).status_code == 404
    c.put(f"/documents/{doc['id']}/acl",
          json={"visibility": "restricted", "entries": [{"user_id": bob_id, "permission": "read"}]}, headers=alice)
    assert c.get(f"/documents/{doc['id']}", headers=bob).status_code == 200

    # versioning, download, RAG respects permissions, audit
    assert c.post(f"/documents/{doc['id']}/versions", files={"file": ("nda.txt", b"v2 agreement text")},
                  headers=alice).json()["current_version"] == 2
    assert len(c.get(f"/documents/{doc['id']}/versions", headers=alice).json()) == 2
    assert c.get(f"/documents/{doc['id']}/download?version=1", headers=alice).content.startswith(b"This agreement")
    assert c.post("/qa", json={"question": "what is it?"}, headers=eve).json()["sources"] == []
    assert len(c.post("/qa", json={"question": "what is it?"}, headers=alice).json()["sources"]) == 1
    logs = c.get(f"/audit?workspace_id={ws['id']}", headers=alice).json()
    assert {"document.upload", "access.denied", "document.version"} <= {l["action"] for l in logs}
    assert c.get(f"/audit?workspace_id={ws['id']}", headers=bob).status_code == 403


def test_auto_routing_picks_permitted_workspace():
    alice = user("a@x.com")
    c.post("/workspaces", json={"name": "HR", "description": "people"}, headers=alice)
    r = c.post("/documents", files={"file": ("leave.txt", b"employee leave policy")}, headers=alice)
    assert r.status_code == 201 and r.json()["category"] == "hr"
