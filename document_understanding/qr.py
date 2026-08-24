"""Independent QR decoding that never blocks semantic analysis."""

from pathlib import Path

from PIL import Image

from document_understanding.models import ConfidenceLevel, QRCodeResult, QRContentType
from document_understanding.validation import normalize_http_url
from utils.logger import get_logger


logger = get_logger(__name__)


def decode_qr_codes(image_path: Path) -> tuple[list[QRCodeResult], list[str]]:
    try:
        import zxingcpp
    except ImportError:
        logger.warning("QR decoder is unavailable")
        return [], ["Independent QR decoding is unavailable."]

    try:
        with Image.open(image_path) as image:
            barcodes = zxingcpp.read_barcodes(
                image, formats=zxingcpp.BarcodeFormat.QRCode
            )
    except Exception as exc:  # QR failure must not stop document understanding.
        logger.warning("QR decoding failed: %s", type(exc).__name__)
        return [], ["A visible QR code could not be decoded independently."]

    codes: list[QRCodeResult] = []
    for barcode in barcodes:
        value = str(barcode.text).strip()
        if not value:
            continue
        content_type = (
            QRContentType.URL if normalize_http_url(value) else QRContentType.TEXT
        )
        symbol_format = getattr(getattr(barcode, "format", None), "name", None)
        codes.append(
            QRCodeResult(
                value=value,
                type=content_type,
                confidence=ConfidenceLevel.HIGH,
                symbol_format=symbol_format,
            )
        )
    return codes, []
