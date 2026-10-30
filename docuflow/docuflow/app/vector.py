"""ChromaDB wrapper. Chroma stores chunks + embeddings; the DB stays the source of truth for permissions."""
from .config import settings

_collection = None


def collection():
    global _collection
    if _collection is None:
        import chromadb
        client = chromadb.PersistentClient(path=settings.chroma_path)
        _collection = client.get_or_create_collection("documents")
    return _collection


def chunk(text: str, size: int = 1000, overlap: int = 150) -> list[str]:
    text = " ".join(text.split())
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        i += size - overlap
    return out


def delete_document(document_id: int) -> None:
    collection().delete(where={"document_id": document_id})


def index_document(document_id: int, workspace_id: int, version: int, title: str, text: str) -> int:
    delete_document(document_id)  # only the current version is searchable
    chunks = chunk(text)
    if not chunks:
        return 0
    collection().add(
        ids=[f"{document_id}:{version}:{i}" for i in range(len(chunks))],
        documents=chunks,
        metadatas=[{"document_id": document_id, "workspace_id": workspace_id,
                    "version": version, "title": title} for _ in chunks],
    )
    return len(chunks)


def search(question: str, allowed_document_ids: list[int], top_k: int) -> list[dict]:
    if not allowed_document_ids:
        return []
    res = collection().query(query_texts=[question], n_results=top_k,
                             where={"document_id": {"$in": allowed_document_ids}})
    docs, metas = res["documents"][0], res["metadatas"][0]
    return [{"text": d, **m} for d, m in zip(docs, metas)]
