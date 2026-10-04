"""Records messages instead of sending them (tests). `fail_times` makes the first sends fail."""
from __future__ import annotations

from . import ChannelError


class FakeChannel:
    def __init__(self, name: str = "telegram", fail_times: int = 0):
        self.name, self.sent, self.fail_times = name, [], fail_times

    def send(self, recipient, text: str) -> str:
        if self.fail_times:
            self.fail_times -= 1
            raise ChannelError("simulated failure")
        self.sent.append((recipient.name, text))
        return str(len(self.sent))
