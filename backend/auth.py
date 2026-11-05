"""Firebase identity verification and explicit private-pilot authorization."""

from functools import lru_cache

from fastapi import Depends, Header, HTTPException

from backend.dependencies import get_backend_settings
from backend.jobs import JobRecord
from config.settings import Settings
from utils.logger import get_logger

logger = get_logger(__name__)


def validate_auth_settings(settings: Settings) -> None:
    if settings.api_auth_mode not in {"none", "firebase"}:
        raise RuntimeError("API_AUTH_MODE must be none or firebase.")
    if settings.api_auth_mode == "firebase" and (
        not settings.firebase_project_id or not settings.pilot_allowed_uids
    ):
        raise RuntimeError(
            "Firebase authentication requires a project ID and approved tester UIDs."
        )


@lru_cache(maxsize=4)
def _firebase_app(project_id: str):
    import firebase_admin

    # Cloud Run supplies Application Default Credentials for its runtime identity.
    return firebase_admin.initialize_app(
        options={"projectId": project_id}, name=f"slip-pilot-{project_id}"
    )


def verify_identity_token(token: str, project_id: str) -> str:
    from firebase_admin import auth

    try:
        claims = auth.verify_id_token(
            token, app=_firebase_app(project_id), check_revoked=True
        )
    except (
        ValueError,
        auth.InvalidIdTokenError,
        auth.RevokedIdTokenError,
        auth.UserDisabledError,
    ):
        raise HTTPException(
            status_code=401,
            detail="Sign in again to continue.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except Exception as exc:
        logger.error("Identity verification unavailable: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503, detail="Sign-in verification is temporarily unavailable."
        ) from None
    uid = claims.get("uid")
    if not isinstance(uid, str) or not uid:
        raise HTTPException(status_code=401, detail="Sign in again to continue.")
    return uid


def authorized_uid(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_backend_settings),
) -> str | None:
    if settings.api_auth_mode == "none":
        return None
    if settings.api_auth_mode != "firebase":
        raise HTTPException(status_code=503, detail="Authentication is not configured.")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 8192:
        raise HTTPException(
            status_code=401,
            detail="Sign in to continue.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    uid = verify_identity_token(token, settings.firebase_project_id)
    if uid not in settings.pilot_allowed_uids:
        raise HTTPException(
            status_code=403, detail="This account is not approved for the pilot."
        )
    return uid


def require_owner(record: JobRecord | None, uid: str | None) -> JobRecord:
    if record is None or record.owner_uid != uid:
        raise HTTPException(status_code=404, detail="Result not found.")
    return record
