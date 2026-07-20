"""
Backward-compatibility alias for common.llm_client.
"""
from common.llm_client import generate_structured, _generate_structured_gemini, _generate_structured_ollama

__all__ = ["generate_structured", "_generate_structured_gemini", "_generate_structured_ollama"]
