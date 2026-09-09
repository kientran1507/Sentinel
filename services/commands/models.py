from __future__ import annotations

from dataclasses import dataclass, field
from shlex import split as shell_split
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Command:
    name: str
    args: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class CommandResponse:
    text: str
    ok: bool = True
    command: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)


class CommandParser:
    """Parse only slash-prefixed, explicitly registered command names."""

    def parse(self, text: str) -> Optional[Command]:
        if not text or not text.strip().startswith("/"):
            return None
        try:
            parts = shell_split(text.strip())
        except ValueError:
            return Command("__malformed__")
        if not parts:
            return None
        name = parts[0][1:].split("@", 1)[0].lower()
        return Command(name=name, args=parts[1:])
