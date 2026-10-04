"""Prints messages to the terminal: for trying a report without sending it anywhere."""
from __future__ import annotations

import sys


class ConsoleChannel:
    name = "console"

    def send(self, recipient, text: str) -> str:
        print(f"--- to {recipient.name} ---\n{text}\n", file=sys.stdout)
        return "console"
