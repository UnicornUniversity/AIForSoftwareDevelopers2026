"""Local vision-language analysis through Ollama. Advisory only."""

from .ollama_client import DEFAULT_BASE_URL, OllamaClient, OllamaModel
from .vlm_detector import (
    DEFAULT_PROMPT,
    OllamaVlmDetector,
    VlmConfig,
    encode_frame_jpeg_base64,
)
from .vlm_parsing import VlmFinding, VlmParseError, parse_vlm_response

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_PROMPT",
    "OllamaClient",
    "OllamaModel",
    "OllamaVlmDetector",
    "VlmConfig",
    "VlmFinding",
    "VlmParseError",
    "encode_frame_jpeg_base64",
    "parse_vlm_response",
]
