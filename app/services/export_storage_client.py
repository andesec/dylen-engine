"""GCS helper for private export/hydrate artifact storage and signed downloads."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlparse, urlunparse

from app.config import Settings
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage
from starlette.concurrency import run_in_threadpool


@dataclass(frozen=True)
class ExportObjectMetadata:
  """Metadata returned for uploaded/downloaded artifact objects."""

  object_name: str
  size: int
  content_type: str | None


class ExportStorageClient:
  """Thin wrapper over GCS for data transfer zip artifacts."""

  def __init__(self, settings: Settings) -> None:
    if not settings.export_bucket:
      raise RuntimeError("DYLEN_EXPORT_BUCKET must be configured for data transfer.")
    self._bucket_name = settings.export_bucket
    self._storage_host = settings.gcs_storage_host
    if self._storage_host:
      emulator_endpoint = _normalize_emulator_endpoint(self._storage_host)
      os.environ["GCS_STORAGE_EMULATOR_HOST"] = emulator_endpoint
      self._client = storage.Client(project=settings.gcp_project_id or "local-dev", credentials=AnonymousCredentials(), client_options={"api_endpoint": emulator_endpoint})
    else:
      self._client = storage.Client(project=settings.gcp_project_id)

  @property
  def bucket_name(self) -> str:
    """Return bucket name used by this client."""
    return self._bucket_name

  async def upload_bytes(self, *, object_name: str, payload: bytes, content_type: str = "application/zip") -> ExportObjectMetadata:
    """Upload bytes to the configured export bucket."""
    bucket = self._client.bucket(self._bucket_name)
    blob = bucket.blob(object_name)
    blob.content_type = content_type
    await run_in_threadpool(blob.upload_from_string, payload, content_type)
    size = int(len(payload))
    return ExportObjectMetadata(object_name=object_name, size=size, content_type=blob.content_type)

  async def ensure_bucket(self) -> None:
    """Create the export bucket automatically when running against emulator."""
    if not self._storage_host:
      return
    bucket = self._client.bucket(self._bucket_name)

    def _create_if_missing() -> None:
      if not bucket.exists(client=self._client):
        self._client.create_bucket(bucket)

    await run_in_threadpool(_create_if_missing)

  async def download_bytes(self, *, object_name: str) -> tuple[bytes, ExportObjectMetadata]:
    """Download bytes from the configured export bucket."""
    bucket = self._client.bucket(self._bucket_name)
    blob = bucket.blob(object_name)
    payload = await run_in_threadpool(blob.download_as_bytes)
    metadata = ExportObjectMetadata(object_name=object_name, size=int(len(payload)), content_type=blob.content_type)
    return payload, metadata

  async def generate_signed_url(self, *, object_name: str, ttl_seconds: int) -> str:
    """Generate a short-lived signed URL for direct artifact download."""
    if self._storage_host:
      raise RuntimeError("Signed URLs are not supported with GCS emulator host.")
    bucket = self._client.bucket(self._bucket_name)
    blob = bucket.blob(object_name)
    expiration = timedelta(seconds=int(ttl_seconds))
    return await run_in_threadpool(blob.generate_signed_url, expiration=expiration, method="GET")


def build_export_storage_client(settings: Settings) -> ExportStorageClient:
  """Create an export artifact storage client."""
  return ExportStorageClient(settings)


def _normalize_emulator_endpoint(raw_endpoint: str) -> str:
  """Normalize emulator endpoint so SDK receives scheme+host+port only."""
  parsed = urlparse(raw_endpoint)
  if not parsed.scheme or not parsed.netloc:
    return raw_endpoint.rstrip("/")
  return urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")
