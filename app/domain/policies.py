from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class DuplicateCandidate:
    patient_id: int
    hn: str
    display_name: str
    match_reason: str


def normalize_person_name(*parts: str | None) -> str:
    return " ".join(part.strip().casefold() for part in parts if part and part.strip())


def names_are_similar(left: str, right: str, threshold: float = 0.85) -> bool:
    if not left or not right:
        return False
    return SequenceMatcher(None, left, right).ratio() >= threshold
