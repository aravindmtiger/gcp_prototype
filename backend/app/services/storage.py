"""Object storage for uploaded source documents.

``STORAGE_BACKEND=gcs`` writes to a Cloud Storage bucket (Cloud Run's service account
needs ``roles/storage.objectAdmin`` on it). ``local`` writes under LOCAL_STORAGE_DIR and
is used for development and tests.
"""

import asyncio
import re
import uuid
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

from app.config import Settings, get_settings

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def make_object_key(collection: str, filename: str) -> str:
    """Build a server-side key. The client filename is sanitized, never trusted as a path."""
    safe_name = _UNSAFE_CHARS.sub("_", filename)[:120] or "upload"
    return f"{collection}/{uuid.uuid4().hex}-{safe_name}"


class ObjectStorage(ABC):
    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str) -> str:
        """Store bytes under ``key`` and return a URI for the stored object."""


class LocalObjectStorage(ObjectStorage):
    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        target = (self._root / key).resolve()
        if self._root not in target.parents:
            raise ValueError("object key escapes the storage root")
        await asyncio.to_thread(self._write, target, data)
        return target.as_uri()

    @staticmethod
    def _write(target: Path, data: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


class GCSObjectStorage(ObjectStorage):
    def __init__(self, bucket_name: str) -> None:
        from google.cloud import storage

        self._bucket = storage.Client().bucket(bucket_name)
        self._bucket_name = bucket_name

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        blob = self._bucket.blob(key)
        # The google-cloud-storage client is synchronous; keep it off the event loop.
        await asyncio.to_thread(blob.upload_from_string, data, content_type=content_type)
        return f"gs://{self._bucket_name}/{key}"


def build_object_storage(settings: Settings) -> ObjectStorage:
    if settings.storage_backend == "gcs":
        return GCSObjectStorage(settings.gcs_bucket)
    return LocalObjectStorage(settings.local_storage_dir)


@lru_cache
def get_object_storage() -> ObjectStorage:
    return build_object_storage(get_settings())
