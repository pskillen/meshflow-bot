"""Tests for :mod:`src.responders.responder_factory`."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.responders.message_reaction_responder import MessageReactionResponder
from src.responders.responder_factory import ResponderFactory


def test_match_responder_returns_instance() -> None:
    bot = MagicMock()
    responder = ResponderFactory.match_responder("test", bot)
    assert isinstance(responder, MessageReactionResponder)


def test_match_responder_returns_none_for_unknown() -> None:
    assert ResponderFactory.match_responder("no match here", MagicMock()) is None
