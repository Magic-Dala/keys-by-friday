from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app.config import Settings, get_settings


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """The user identity the backend is allowed to trust."""

    uid: str
    sign_in_provider: str | None = None


class InvalidAuthenticationToken(ValueError):
    """The supplied Firebase token is missing, expired, or invalid."""


class AuthenticationServiceUnavailable(RuntimeError):
    """Firebase verification could not run because the server is misconfigured."""


bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache(maxsize=4)
def _firebase_app(project_id: str):
    try:
        import firebase_admin

        app_name = f"keys-by-friday-{project_id}"
        try:
            return firebase_admin.get_app(name=app_name)
        except ValueError:
            return firebase_admin.initialize_app(
                options={"projectId": project_id},
                name=app_name,
            )
    except Exception as exc:
        raise AuthenticationServiceUnavailable(
            "Firebase Admin could not be initialized."
        ) from exc


def _verify_firebase_id_token_sync(token: str, project_id: str) -> dict[str, Any]:
    try:
        from firebase_admin import auth as firebase_auth
    except Exception as exc:
        raise AuthenticationServiceUnavailable(
            "Firebase Admin is not installed."
        ) from exc

    try:
        claims = firebase_auth.verify_id_token(
            token,
            app=_firebase_app(project_id),
        )
    except AuthenticationServiceUnavailable:
        raise
    except (
        firebase_auth.InvalidIdTokenError,
        firebase_auth.ExpiredIdTokenError,
        firebase_auth.RevokedIdTokenError,
        firebase_auth.UserDisabledError,
        ValueError,
    ) as exc:
        # Token contents are deliberately not placed in the error or logs.
        raise InvalidAuthenticationToken("Firebase ID token is invalid.") from exc
    except Exception as exc:
        raise AuthenticationServiceUnavailable(
            "Firebase ID token verification is unavailable."
        ) from exc

    if not isinstance(claims, dict):
        raise InvalidAuthenticationToken("Firebase ID token has invalid claims.")
    return claims


async def verify_firebase_id_token(
    token: str, project_id: str
) -> dict[str, Any]:
    # Firebase's Python verifier is synchronous. A worker thread prevents it from
    # pausing unrelated FastAPI requests while public signing keys are fetched.
    return await asyncio.to_thread(
        _verify_firebase_id_token_sync, token, project_id
    )


def _settings_for_request(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    return settings if isinstance(settings, Settings) else get_settings()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="A valid sign-in token is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthenticatedUser:
    settings = _settings_for_request(request)

    if settings.auth_mode == "disabled":
        if settings.app_environment == "production":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication is not configured on the server.",
            )
        # This identity exists only for local development and automated tests.
        return AuthenticatedUser(uid="local-user", sign_in_provider="disabled")

    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise _unauthorized()
    if not settings.firebase_project_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured on the server.",
        )

    try:
        claims = await verify_firebase_id_token(
            credentials.credentials,
            settings.firebase_project_id,
        )
    except InvalidAuthenticationToken as exc:
        raise _unauthorized() from exc
    except AuthenticationServiceUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is temporarily unavailable.",
        ) from exc

    uid_value = claims.get("uid") or claims.get("sub")
    uid = str(uid_value).strip() if uid_value is not None else ""
    if not uid:
        raise _unauthorized()

    firebase_claims = claims.get("firebase")
    sign_in_provider = (
        firebase_claims.get("sign_in_provider")
        if isinstance(firebase_claims, dict)
        else None
    )
    return AuthenticatedUser(
        uid=uid,
        sign_in_provider=(
            str(sign_in_provider) if sign_in_provider is not None else None
        ),
    )
