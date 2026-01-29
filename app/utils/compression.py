"""Compression utilities for Fenster Widgets."""

import brotli

BROTLI_QUALITY = 11


def compress_html(raw_html: str) -> bytes:
  """Compress HTML string using Brotli (Level 11)."""
  return brotli.compress(raw_html.encode("utf-8"), quality=BROTLI_QUALITY)


def decompress_html(blob: bytes) -> str:
  """Decompress Brotli-compressed blob to HTML string."""
  return brotli.decompress(blob).decode("utf-8")
