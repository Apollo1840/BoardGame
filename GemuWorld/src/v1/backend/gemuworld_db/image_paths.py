from __future__ import annotations

from pathlib import PurePosixPath


CANONICAL_PREFIX = "pics/"


def normalize_image_path(value: object) -> str:
    """Return the portable database form: pics/<relative artwork path>."""
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    lowered = text.casefold()
    marker = "/data/current/pics/"
    marker_at = lowered.find(marker)
    if marker_at >= 0:
        text = "pics/" + text[marker_at + len(marker):]
    else:
        text = text.lstrip("/")
        lowered = text.casefold()
        for prefix in ("data/current/pics/", "pictures/", "pics/"):
            if lowered.startswith(prefix):
                text = "pics/" + text[len(prefix):]
                break
        else:
            if ":" in text or "/" in text:
                raise ValueError("image path must be a filename or live under pics/")
            text = "pics/" + text
    relative = PurePosixPath(text.removeprefix("pics/"))
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("image path must not be empty or contain parent traversal")
    return CANONICAL_PREFIX + relative.as_posix()


def card_image_path(card_id: object) -> str:
    """Return the locked artwork path for a stable card ID."""
    value = str(card_id or "").strip()
    if not value or value in {".", ".."} or any(character in value for character in '<>:"/\\|?*') or any(ord(character) < 32 for character in value):
        raise ValueError("card_id contains characters that are unsafe in an image filename")
    return f"{CANONICAL_PREFIX}{value}.png"


def image_url(value: object) -> str:
    path = normalize_image_path(value)
    return "/" + path if path else ""


def legacy_image_path(value: object) -> str:
    path = normalize_image_path(value)
    return "pictures/" + path.removeprefix(CANONICAL_PREFIX) if path else ""
