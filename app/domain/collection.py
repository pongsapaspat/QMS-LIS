from enum import StrEnum
from typing import Literal


class CollectionRoom(StrEnum):
    URINE_STOOL = "URINE_STOOL"
    SWAB = "SWAB"
    BLOOD = "BLOOD"


COLLECTION_ROOM_LABELS = {
    CollectionRoom.URINE_STOOL: "ปัสสาวะ / อุจจาระ",
    CollectionRoom.SWAB: "Swab",
    CollectionRoom.BLOOD: "เจาะเลือด",
}

CollectionRoomFilter = CollectionRoom | Literal["all"]
