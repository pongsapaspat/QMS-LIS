from fastapi import Request
from fastapi.responses import Response

from app.core.config import get_settings
from app.domain.collection import CollectionRoom, CollectionRoomFilter

COLLECTION_ROOM_COOKIE = "qms_lis_collection_room"


def selected_collection_room(
    request: Request, requested: CollectionRoomFilter | None
) -> CollectionRoom | None:
    value = requested if requested is not None else request.cookies.get(COLLECTION_ROOM_COOKIE)
    try:
        return CollectionRoom(value) if value else None
    except ValueError:
        return None


def remember_collection_room(response: Response, room: CollectionRoom | None) -> None:
    response.set_cookie(
        COLLECTION_ROOM_COOKIE, room.value if room else "all", max_age=365 * 24 * 60 * 60,
        httponly=True, secure=get_settings().session_https_only, samesite="lax",
    )
