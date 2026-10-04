"""Channel adapters share one contract: `send(recipient, text) -> external id`. Register a channel under its name."""
from __future__ import annotations

from typing import Protocol

from ...config import settings


class ChannelError(Exception):
    pass


class Channel(Protocol):
    name: str

    def send(self, recipient, text: str) -> str: ...


_CHANNELS: dict[str, Channel] = {}


def register(channel: Channel) -> None:
    _CHANNELS[channel.name] = channel


def get(name: str) -> Channel:
    if name not in _CHANNELS:
        if name == "telegram":
            from .telegram import TelegramChannel
            if not settings.telegram_bot_token:
                raise ChannelError("INSIGHTS_TELEGRAM_BOT_TOKEN is not set")
            register(TelegramChannel(settings.telegram_bot_token))
        elif name == "console":
            from .console import ConsoleChannel
            register(ConsoleChannel())
        else:
            raise ChannelError(f"unknown channel {name!r}")
    return _CHANNELS[name]
