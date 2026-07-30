from __future__ import annotations

import re
from collections.abc import Iterator

_BOUNDARY = re.compile(r"(?:\r?\n){2,}|(?<=[。！？.!?;；])\s+")  # noqa: RUF001


def normalize_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.replace("\x00", "").splitlines()]
    compact: list[str] = []
    for line in lines:
        if line:
            compact.append(line)
        elif compact and compact[-1] != "":
            compact.append("")
    return "\n".join(compact).strip()


def chunk_text(text: str, max_chars: int, overlap: int) -> Iterator[str]:
    normalized = normalize_text(text)
    if not normalized:
        return
    if len(normalized) <= max_chars:
        yield normalized
        return

    pieces = [piece.strip() for piece in _BOUNDARY.split(normalized) if piece.strip()]
    if len(pieces) <= 1:
        start = 0
        while start < len(normalized):
            end = min(len(normalized), start + max_chars)
            yield normalized[start:end].strip()
            if end == len(normalized):
                return
            start = max(start + 1, end - overlap)
        return

    buffer = ""
    for piece in pieces:
        candidate = f"{buffer}\n\n{piece}".strip() if buffer else piece
        if len(candidate) <= max_chars:
            buffer = candidate
            continue
        if buffer:
            yield buffer
            prefix = buffer[-overlap:] if overlap else ""
            buffer = f"{prefix}\n\n{piece}".strip()
        else:
            yield from chunk_text(piece, max_chars, overlap)
            buffer = ""
        while len(buffer) > max_chars:
            yield buffer[:max_chars]
            buffer = buffer[max_chars - overlap :].strip()
    if buffer:
        yield buffer
