"""Shared safe multipart upload handling for backend API routes."""

from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from config.settings import Settings
from utils.file_utils import (
    ImageTooLargeError,
    InvalidImageError,
    UnsupportedImageError,
    save_uploaded_image,
)


async def save_slip_upload(slip: UploadFile, settings: Settings) -> Path:
    """Read, validate, normalize, and randomly name one uploaded slip."""
    maximum_bytes = settings.max_upload_mb * 1024 * 1024
    file_data = await slip.read(maximum_bytes + 1)
    if len(file_data) > maximum_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The uploaded image exceeds the configured size limit.",
        )

    try:
        return save_uploaded_image(
            file_data=file_data,
            original_name=slip.filename or "upload",
            temp_dir=settings.temp_dir,
            max_upload_mb=settings.max_upload_mb,
        )
    except UnsupportedImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload a JPG, JPEG, or PNG image.",
        ) from exc
    except ImageTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The uploaded image exceeds the configured size limit.",
        ) from exc
    except InvalidImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded image could not be read.",
        ) from exc
