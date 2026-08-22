"""Shared YAML frontmatter parser for SKILL.md files."""

from __future__ import annotations

import re

import yaml

# A frontmatter fence is a `---` that owns its whole line. Searching for a bare
# "---" substring instead truncates any file whose description contains one.
_FENCE_END = re.compile(r"^---[ \t]*$", re.M)

# `key:` at column zero. The value is everything after the first colon-space,
# so a description containing further colons stays intact.
_KEY = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]+(?P<value>.*))?$")
_BLOCK_HEADER = re.compile(r"^[|>][-+]?\d*$")


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split a SKILL.md file into (frontmatter, body).

    Returns (None, text) if no valid frontmatter is found.
    """
    stripped = text.strip()
    if not stripped.startswith("---"):
        return None, text
    match = _FENCE_END.search(stripped, 3)
    if match is None:
        return None, text
    frontmatter = stripped[3 : match.start()].strip()
    body = stripped[match.end() :]
    return frontmatter, body


def parse_frontmatter(frontmatter: str) -> dict:
    """Parse frontmatter into a dict, tolerating YAML that PyYAML rejects.

    Claude Code and most skill authors write `description:` values containing
    unquoted ": " sequences, which are legal in practice but a hard
    ScannerError to yaml.safe_load. Strict parsing is tried first so valid
    files keep their full typed structure; anything PyYAML refuses falls back
    to a line scanner that recovers the keys importers actually consume.

    Never raises. Returns {} when nothing can be recovered.
    """
    try:
        meta = yaml.safe_load(frontmatter)
    except yaml.YAMLError:
        return _salvage(frontmatter)
    return meta if isinstance(meta, dict) else {}


def _salvage(frontmatter: str) -> dict:
    """Line scanner for the YAML subset skill frontmatter actually uses."""
    meta: dict[str, object] = {}
    lines = frontmatter.splitlines()
    i = 0
    while i < len(lines):
        match = _KEY.match(lines[i])
        if match is None:
            i += 1
            continue

        key = match.group("key")
        raw = (match.group("value") or "").strip()
        i += 1

        if _BLOCK_HEADER.match(raw):  # block scalar: fold the indented lines
            block, i = _take_indented(lines, i)
            meta[key] = " ".join(block).strip()
        elif raw:
            meta[key] = _scalar(raw)
        else:  # bare `key:` — either a block sequence or an empty value
            items, i = _take_sequence(lines, i)
            meta[key] = items if items else ""
    return meta


def _take_indented(lines: list[str], i: int) -> tuple[list[str], int]:
    out: list[str] = []
    while i < len(lines) and (not lines[i].strip() or lines[i][:1] in (" ", "\t")):
        out.append(lines[i].strip())
        i += 1
    return out, i


def _take_sequence(lines: list[str], i: int) -> tuple[list[str], int]:
    out: list[str] = []
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        if not lines[i][:1].isspace() and not stripped.startswith("-"):
            break
        if stripped.startswith("- "):
            out.append(_scalar(stripped[2:].strip()))
        elif stripped.startswith("-") and len(stripped) > 1:
            out.append(_scalar(stripped[1:].strip()))
        else:
            break
        i += 1
    return out, i


def _scalar(raw: str) -> object:
    """Unwrap a flow list or a quoted scalar. Bare text is returned as-is."""
    if len(raw) >= 2 and raw[0] == "[" and raw[-1] == "]":
        return [_scalar(p.strip()) for p in raw[1:-1].split(",") if p.strip()]
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    return raw
