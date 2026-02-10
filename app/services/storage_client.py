"""Object storage helper for illustration media assets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from app.config import Settings
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage
from starlette.concurrency import run_in_threadpool


@dataclass(frozen=True)
class StorageObjectMetadata:
  """Metadata returned for a downloaded storage object."""

  content_type: str | None
  cache_control: str | None
  size: int | None


class StorageClient:
  """Thin wrapper over GCS and emulator access for media upload/download."""

  def __init__(self, settings: Settings) -> None:
    self._bucket_name = settings.illustration_bucket
    self._storage_host = settings.gcs_storage_host
    # Ensure emulator endpoint is visible to the SDK in local development.
    if self._storage_host:
      emulator_endpoint = _normalize_emulator_endpoint(self._storage_host)
      os.environ["GCS_STORAGE_EMULATOR_HOST"] = emulator_endpoint
      self._client = storage.Client(project=settings.gcp_project_id or "local-dev", credentials=AnonymousCredentials(), client_options={"api_endpoint": emulator_endpoint})
    else:
      self._client = storage.Client(project=settings.gcp_project_id)

  @property
  def bucket_name(self) -> str:
    """Return the default bucket name for illustration objects."""
    return self._bucket_name

  async def ensure_bucket(self) -> None:
    """Create the default bucket when missing in local/dev flows."""
    # Keep production startup side-effect free; only auto-create in emulator mode.
    if not self._storage_host:
      return
    bucket = self._client.bucket(self._bucket_name)

    def _create_if_missing() -> None:
      if not bucket.exists(client=self._client):
        self._client.create_bucket(bucket)

    await run_in_threadpool(_create_if_missing)

  async def upload_webp(self, image_bytes: bytes, object_name: str, cache_control: str = "public, max-age=3600") -> None:
    """Upload WebP bytes to the default bucket with cache directives."""
    bucket = self._client.bucket(self._bucket_name)
    blob = bucket.blob(object_name)
    blob.cache_control = cache_control
    blob.content_type = "image/webp"
    await run_in_threadpool(blob.upload_from_string, image_bytes, "image/webp")

  async def download(self, object_name: str) -> tuple[bytes, StorageObjectMetadata]:
    """Download object bytes and return content metadata."""
    bucket = self._client.bucket(self._bucket_name)
    blob = bucket.blob(object_name)
    data = await run_in_threadpool(blob.download_as_bytes)
    metadata = StorageObjectMetadata(content_type=blob.content_type, cache_control=blob.cache_control, size=blob.size)
    return data, metadata

  async def exists(self, object_name: str) -> bool:
    """Return True when an object exists in the default bucket."""
    bucket = self._client.bucket(self._bucket_name)
    blob = bucket.blob(object_name)
    return bool(await run_in_threadpool(blob.exists))

  async def delete(self, object_name: str) -> None:
    """Delete an object from the default bucket when cleanup is required."""
    bucket = self._client.bucket(self._bucket_name)
    blob = bucket.blob(object_name)
    await run_in_threadpool(blob.delete)


def build_storage_client(settings: Settings) -> StorageClient:
  """Create a storage client instance with environment-aware credentials."""
  return StorageClient(settings)


def _normalize_emulator_endpoint(raw_endpoint: str) -> str:
  """Normalize emulator endpoint so the SDK receives scheme+host+port only."""
  parsed = urlparse(raw_endpoint)
  if not parsed.scheme or not parsed.netloc:
    return raw_endpoint.rstrip("/")
  return urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")
