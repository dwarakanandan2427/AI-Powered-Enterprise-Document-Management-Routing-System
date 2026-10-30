from minio import Minio

from .config import settings

_client: Minio | None = None


def client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(settings.minio_endpoint, access_key=settings.minio_access_key,
                        secret_key=settings.minio_secret_key, secure=settings.minio_secure)
    return _client


def ensure_bucket() -> None:
    c = client()
    if not c.bucket_exists(settings.minio_bucket):
        c.make_bucket(settings.minio_bucket)


def put(key: str, data: bytes, content_type: str) -> None:
    import io
    client().put_object(settings.minio_bucket, key, io.BytesIO(data), len(data),
                        content_type=content_type or "application/octet-stream")


def stream(key: str):
    resp = client().get_object(settings.minio_bucket, key)
    try:
        yield from resp.stream(64 * 1024)
    finally:
        resp.close()
        resp.release_conn()


def remove(key: str) -> None:
    client().remove_object(settings.minio_bucket, key)
