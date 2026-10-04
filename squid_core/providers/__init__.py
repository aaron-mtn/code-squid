"""Provider contracts; concrete transports are imported only by their callers."""

from squid_core.providers.base import BaseProvider, StreamCancelled

__all__ = ["BaseProvider", "StreamCancelled"]
