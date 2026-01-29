"""Schemas for OCR extraction responses."""

from pydantic import BaseModel


class ExtractionResult(BaseModel):
  """Represent OCR output to keep filenames aligned with extracted text."""

  # Store the file name for client-side mapping.
  filename: str
  # Store extracted content for downstream display.
  content: str


class BatchResponse(BaseModel):
  """Bundle OCR extraction results to keep batch ordering intact."""

  # Store batch results to keep the response predictable.
  results: list[ExtractionResult]
