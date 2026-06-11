"""Backward-compatible re-exports. Prefer quorascrapper.messaging."""

from quorascrapper.messaging import BaseSender, KafkaSender, StdoutSender

__all__ = ["BaseSender", "StdoutSender", "KafkaSender"]
