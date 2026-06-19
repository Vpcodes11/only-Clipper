"""
Storage abstraction layer — Local filesystem + Supabase Storage backends.
"""
import os
import shutil
import hashlib
import logging
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    @abstractmethod
    def upload(self, local_path: str, remote_key: str, content_type: str = "application/octet-stream") -> str:
        """Upload a file. Returns the remote path/URL."""
        ...

    @abstractmethod
    def download(self, remote_key: str, local_path: str) -> str:
        """Download a file to local path. Returns local_path."""
        ...

    @abstractmethod
    def delete(self, remote_key: str) -> bool:
        """Delete a remote object."""
        ...

    @abstractmethod
    def get_url(self, remote_key: str, expires: int = 3600) -> str:
        """Get a public or signed URL for the object."""
        ...

    @abstractmethod
    def exists(self, remote_key: str) -> bool:
        """Check if object exists."""
        ...

    def upload_bytes(self, data: bytes, remote_key: str, content_type: str = "application/octet-stream") -> str:
        """Upload raw bytes."""
        ...

    def compute_hash(self, local_path: str) -> str:
        h = hashlib.sha256()
        with open(local_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()


class LocalStorageBackend(StorageBackend):
    def __init__(self, base_dir: str = "./storage"):
        self.base_dir = os.path.abspath(base_dir)
        os.makedirs(self.base_dir, exist_ok=True)

    def _full_path(self, remote_key: str) -> str:
        safe_key = remote_key.replace("\\", "/").lstrip("/")
        path = os.path.join(self.base_dir, safe_key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def upload(self, local_path: str, remote_key: str, content_type: str = "application/octet-stream") -> str:
        dest = self._full_path(remote_key)
        shutil.copy2(local_path, dest)
        return remote_key

    def upload_bytes(self, data: bytes, remote_key: str, content_type: str = "application/octet-stream") -> str:
        dest = self._full_path(remote_key)
        with open(dest, "wb") as f:
            f.write(data)
        return remote_key

    def download(self, remote_key: str, local_path: str) -> str:
        src = self._full_path(remote_key)
        if not os.path.exists(src):
            raise FileNotFoundError(f"Object not found: {remote_key}")
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        shutil.copy2(src, local_path)
        return local_path

    def delete(self, remote_key: str) -> bool:
        p = self._full_path(remote_key)
        if os.path.exists(p):
            os.remove(p)
            return True
        return False

    def get_url(self, remote_key: str, expires: int = 3600) -> str:
        path = f"/storage/{remote_key}"
        base_url = os.getenv("BASE_URL", "").rstrip("/")
        return f"{base_url}{path}" if base_url else path

    def exists(self, remote_key: str) -> bool:
        return os.path.exists(self._full_path(remote_key))


class SupabaseStorageBackend(StorageBackend):
    def __init__(self, url: str, service_key: str, bucket: str):
        from supabase import create_client, Client
        self.url = url
        self.bucket = bucket
        self.client: Client = create_client(url, service_key)

    def upload(self, local_path: str, remote_key: str, content_type: str = "application/octet-stream") -> str:
        safe_key = remote_key.replace("\\", "/").lstrip("/")
        with open(local_path, "rb") as f:
            self.client.storage.from_(self.bucket).upload(
                path=safe_key,
                file=f,
                file_options={"content-type": content_type, "upsert": "true"},
            )
        return safe_key

    def upload_bytes(self, data: bytes, remote_key: str, content_type: str = "application/octet-stream") -> str:
        safe_key = remote_key.replace("\\", "/").lstrip("/")
        self.client.storage.from_(self.bucket).upload(
            path=safe_key,
            file=data,
            file_options={"content-type": content_type, "upsert": "true"},
        )
        return safe_key

    def download(self, remote_key: str, local_path: str) -> str:
        safe_key = remote_key.replace("\\", "/").lstrip("/")
        data = self.client.storage.from_(self.bucket).download(safe_key)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(data)
        return local_path

    def delete(self, remote_key: str) -> bool:
        safe_key = remote_key.replace("\\", "/").lstrip("/")
        try:
            self.client.storage.from_(self.bucket).remove([safe_key])
            return True
        except Exception as e:
            logger.warning("Failed to delete %s: %s", safe_key, e)
            return False

    def get_url(self, remote_key: str, expires: int = 3600) -> str:
        safe_key = remote_key.replace("\\", "/").lstrip("/")
        try:
            res = self.client.storage.from_(self.bucket).create_signed_url(safe_key, expires)
            if isinstance(res, dict):
                return res.get("signedURL", "")
            return res
        except Exception:
            return f"{self.url}/storage/v1/object/public/{self.bucket}/{safe_key}"

    def exists(self, remote_key: str) -> bool:
        safe_key = remote_key.replace("\\", "/").lstrip("/")
        try:
            self.client.storage.from_(self.bucket).download(safe_key)
            return True
        except Exception:
            return False


def get_storage() -> StorageBackend:
    backend = os.getenv("STORAGE_BACKEND", "local")
    if backend == "supabase":
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_KEY", "")
        bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "clips")
        if not url or not key:
            logger.warning("Supabase config missing, falling back to local storage")
            return LocalStorageBackend()
        return SupabaseStorageBackend(url, key, bucket)
    return LocalStorageBackend()
