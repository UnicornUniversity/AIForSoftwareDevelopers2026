"""Convert a corpus of DOCX/PDF documents into an authored Word book."""

from .errors import (
    EXIT_CONTENT,
    EXIT_CORPUS,
    EXIT_RENDER,
    EXIT_USAGE,
    BookError,
    ContentError,
    CorpusError,
    RenderError,
    SettingsError,
)
from .extract import Extractor, SourceText, extract_docx, extract_pdf
from .manifest import DocumentEntry, Manifest, load_manifest, resolve_manifest_path
from .settings import Settings, load_settings

__all__ = [
    "EXIT_CONTENT",
    "EXIT_CORPUS",
    "EXIT_RENDER",
    "EXIT_USAGE",
    "BookError",
    "ContentError",
    "CorpusError",
    "DocumentEntry",
    "Extractor",
    "Manifest",
    "RenderError",
    "Settings",
    "SettingsError",
    "SourceText",
    "extract_docx",
    "extract_pdf",
    "load_manifest",
    "load_settings",
    "resolve_manifest_path",
]
