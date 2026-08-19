from __future__ import annotations

from functools import lru_cache


class FirebaseAdminUnavailable(RuntimeError):
    """The server could not initialize a Firebase Admin service."""


@lru_cache(maxsize=4)
def get_firebase_admin_app(project_id: str):
    """Return one named Firebase Admin app for a Google Cloud project."""

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
        raise FirebaseAdminUnavailable(
            "Firebase Admin could not be initialized."
        ) from exc


@lru_cache(maxsize=8)
def get_firestore_client(project_id: str, database_id: str = "(default)"):
    """Create and reuse the privileged server-side Firestore client."""

    try:
        from firebase_admin import firestore

        return firestore.client(
            app=get_firebase_admin_app(project_id),
            database_id=database_id,
        )
    except FirebaseAdminUnavailable:
        raise
    except Exception as exc:
        raise FirebaseAdminUnavailable(
            "Cloud Firestore could not be initialized."
        ) from exc
