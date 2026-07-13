from __future__ import annotations

from pathlib import Path
from typing import Iterable


def parse_line(line: str) -> list[str]:
    fields: list[str] = []
    current: list[str] = []
    index = 0
    text = line.rstrip("\r\n")
    while index < len(text):
        character = text[index]
        if character == "\\" and index + 1 < len(text) and text[index + 1] in ("|", "\\"):
            current.append(text[index + 1])
            index += 2
            continue
        elif character == "|":
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
        index += 1
    fields.append("".join(current))
    return fields


def encode_field(value: object) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace(
        "\r\n", "\\n"
    ).replace("\r", "\\n").replace("\n", "\\n")


def read_records(path: str | Path) -> list[dict[str, str]]:
    return parse_records(Path(path).read_text(encoding="utf-8-sig"), str(path))


def parse_records(text: str, source: str = "<memory>") -> list[dict[str, str]]:
    lines = text.lstrip("\ufeff").splitlines()
    if not lines:
        return []
    header = parse_line(lines[0])
    records: list[dict[str, str]] = []
    for line_number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        values = parse_line(line)
        if len(values) != len(header):
            raise ValueError(
                f"{source}:{line_number}: expected {len(header)} fields, got {len(values)}"
            )
        records.append(dict(zip(header, values, strict=True)))
    return records


def write_records(
    path: str | Path, header: list[str], records: Iterable[dict[str, object]]
) -> None:
    Path(path).write_text(render_records(header, records), encoding="utf-8", newline="")


def render_records(header: list[str], records: Iterable[dict[str, object]]) -> str:
    output = ["|".join(header)]
    output.extend("|".join(encode_field(row.get(key, "")) for key in header) for row in records)
    return "\n".join(output) + "\n"
