"""Orchestration for the complete Phase 2 understanding pipeline."""

from pathlib import Path
from collections.abc import Callable

from document_understanding.models import DocumentUnderstandingResult, QRCodeResult
from document_understanding.provider import DocumentVisionProvider
from document_understanding.qr import decode_qr_codes
from document_understanding.validation import merge_qr_codes, normalize_result
from utils.logger import get_logger


logger = get_logger(__name__)
QRDecoder = Callable[[Path], tuple[list[QRCodeResult], list[str]]]


class DocumentUnderstandingService:
    def __init__(
        self,
        provider: DocumentVisionProvider,
        qr_decoder: QRDecoder = decode_qr_codes,
    ) -> None:
        self._provider = provider
        self._qr_decoder = qr_decoder

    def analyze(self, image_path: Path) -> DocumentUnderstandingResult:
        logger.info("Document understanding started")
        decoded_codes, decoder_warnings = self._qr_decoder(image_path)
        provider_result = self._provider.analyze_document(image_path)
        result = merge_qr_codes(
            normalize_result(provider_result), decoded_codes, decoder_warnings
        )
        # Never log the result, field values, names, identifiers, or credentials.
        logger.info(
            "Document understanding completed with status=%s confidence=%s",
            result.analysis_status.value,
            result.overall_confidence.value,
        )
        return result
