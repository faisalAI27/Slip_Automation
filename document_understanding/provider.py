"""Provider abstraction and provider construction."""

from pathlib import Path
from typing import Protocol

from config.settings import Settings
from document_understanding.models import DocumentUnderstandingResult


class DocumentProviderError(RuntimeError):
    """Base error for provider failures safe to classify without sensitive content."""


class ProviderConfigurationError(DocumentProviderError):
    pass


class ProviderUnavailableError(DocumentProviderError):
    pass


class ProviderTimeoutError(DocumentProviderError):
    pass


class ProviderResponseError(DocumentProviderError):
    pass


class DocumentVisionProvider(Protocol):
    def analyze_document(self, image_path: Path) -> DocumentUnderstandingResult:
        """Return structured understanding without performing downstream actions."""
        ...


def create_document_provider(settings: Settings) -> DocumentVisionProvider:
    provider_name = settings.document_ai_provider.strip().lower()
    model_name = settings.document_ai_model.strip()
    if not model_name:
        raise ProviderConfigurationError("DOCUMENT_AI_MODEL is not configured.")

    if provider_name == "ollama":
        if not settings.ollama_base_url:
            raise ProviderConfigurationError("OLLAMA_BASE_URL is not configured.")
        from document_understanding.ollama_provider import OllamaDocumentVisionProvider

        return OllamaDocumentVisionProvider(
            base_url=settings.ollama_base_url,
            model=model_name,
            timeout_seconds=settings.ollama_timeout_seconds,
        )

    if provider_name == "openai":
        if not settings.document_ai_api_key:
            raise ProviderConfigurationError("DOCUMENT_AI_API_KEY is not configured.")
        from document_understanding.openai_provider import OpenAIDocumentVisionProvider

        return OpenAIDocumentVisionProvider(
            api_key=settings.document_ai_api_key,
            model=model_name,
            timeout_seconds=settings.document_ai_timeout_seconds,
        )

    if provider_name == "gemini":
        if not settings.gemini_api_key:
            raise ProviderConfigurationError("GEMINI_API_KEY is not configured.")
        if not settings.gemini_base_url:
            raise ProviderConfigurationError("GEMINI_BASE_URL is not configured.")
        from document_understanding.gemini_provider import (
            GeminiDocumentVisionProvider,
        )

        return GeminiDocumentVisionProvider(
            api_key=settings.gemini_api_key,
            base_url=settings.gemini_base_url,
            model=model_name,
            timeout_seconds=settings.gemini_timeout_seconds,
        )

    raise ProviderConfigurationError(
        f"Unsupported document provider: {provider_name or 'not set'}"
    )
