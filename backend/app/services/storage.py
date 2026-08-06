from minio import Minio
from minio.error import S3Error
from io import BytesIO
from app.config import get_settings

settings = get_settings()
_client: Minio | None = None


def get_minio() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        ensure_bucket()
    return _client


def ensure_bucket():
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    name = settings.minio_bucket
    if not client.bucket_exists(name):
        client.make_bucket(name)


def upload_bytes(object_key: str, data: bytes, content_type: str = "application/octet-stream"):
    client = get_minio()
    client.put_object(
        settings.minio_bucket,
        object_key,
        BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return object_key


def upload_file(object_key: str, file_path: str, content_type: str = "application/octet-stream"):
    client = get_minio()
    client.fput_object(settings.minio_bucket, object_key, file_path, content_type=content_type)
    return object_key


def download_bytes(object_key: str) -> bytes:
    client = get_minio()
    response = client.get_object(settings.minio_bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def object_exists(object_key: str) -> bool:
    client = get_minio()
    try:
        client.stat_object(settings.minio_bucket, object_key)
        return True
    except S3Error as e:
        if e.code in ("NoSuchKey", "NotFound", "NoSuchObject"):
            return False
        # MinIO may raise with 404 status
        if getattr(e, "status", None) == 404:
            return False
        raise


def get_presigned_url(object_key: str, expires_hours: int = 24) -> str:
    from datetime import timedelta
    client = get_minio()
    return client.presigned_get_object(
        settings.minio_bucket, object_key, expires=timedelta(hours=expires_hours)
    )


def delete_object(object_key: str) -> None:
    if not object_key:
        return
    client = get_minio()
    try:
        client.remove_object(settings.minio_bucket, object_key)
    except S3Error:
        pass


def list_objects(prefix: str) -> list[dict]:
    """列出 bucket 下指定前缀的对象。"""
    client = get_minio()
    items = []
    for obj in client.list_objects(settings.minio_bucket, prefix=prefix, recursive=True):
        items.append({
            "object_key": obj.object_name,
            "size": obj.size,
            "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
        })
    return items
