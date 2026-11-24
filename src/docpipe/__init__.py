"""Reusable evidence-first PDF pipeline. Offline backend is deterministic, not an LLM."""

from .pipeline import process_pdf, Settings, PipelineError
from .normalization import normalize

__all__ = ["process_pdf", "Settings", "PipelineError", "normalize"]
