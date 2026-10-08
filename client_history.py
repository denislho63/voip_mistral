"""Per-client, per-domain history of texts and commands.

Each connected client gets a stable identifier (client_id) so that
concurrent sessions can be told apart. Every finished phrase and every
user-typed command is recorded, indexed by the domain detected by the
classification (detection_classification). When a new phrase is
classified, the history of that domain for that client is provided to
the process_text / process_command hooks so they can use it as context.

Storage is in-memory only (cleared on server restart). A client's
history is dropped when it disconnects.
"""

from __future__ import annotations

import logging
import os
import secrets
from collections import defaultdict, deque
from collections.abc import Callable

log = logging.getLogger("phone-stream.history")

# Maximum entries kept per (client, domain) pair.
MAX_HISTORY_PER_DOMAIN = int(os.environ.get("PHONE_STREAM_HISTORY", "50"))

Record = dict  # {"role": "phrase"|"response"|"command", "text": str, "domain": str}


class ClientHistory:
    """History of one client, split by domain."""

    def __init__(self, client_id: str):
        self.client_id = client_id
        self._by_domain: dict[str, deque[Record]] = defaultdict(
            lambda: deque(maxlen=MAX_HISTORY_PER_DOMAIN)
        )

    def add_phrase(self, domain: str, text: str) -> None:
        """Record a transcribed phrase (after classification)."""
        if text:
            self._by_domain[domain].append(
                {"role": "phrase", "text": text, "domain": domain}
            )

    def add_command(self, domain: str, text: str) -> None:
        """Record a user-typed command."""
        if text:
            self._by_domain[domain].append(
                {"role": "command", "text": text, "domain": domain}
            )

    def add_response(self, domain: str, text: str) -> None:
        """Record the response produced for a phrase/command."""
        if text:
            self._by_domain[domain].append(
                {"role": "response", "text": text, "domain": domain}
            )

    def get(self, domain: str) -> list[Record]:
        """History of one domain, oldest first (list of records)."""
        return list(self._by_domain.get(domain, ()))

    def texts(self, domain: str) -> list[str]:
        """History of one domain as plain texts, oldest first."""
        return [record["text"] for record in self.get(domain)]

    def domains(self) -> list[str]:
        """Domains that have at least one record."""
        return list(self._by_domain.keys())

    def __len__(self) -> int:
        return sum(len(entries) for entries in self._by_domain.values())


class HistoryRegistry:
    """All clients' histories, keyed by client_id."""

    def __init__(self):
        self._clients: dict[str, ClientHistory] = {}
        self._on_record: Callable[[str, Record], None] | None = None

    def set_listener(self, listener: Callable[[str, Record], None]) -> None:
        """Optional hook called with (client_id, record) after each add."""
        self._on_record = listener

    def register(self, client_id: str) -> ClientHistory:
        """Get (creating if needed) the history of a client."""
        if client_id not in self._clients:
            self._clients[client_id] = ClientHistory(client_id)
            log.info("history opened for client %s", client_id)
        return self._clients[client_id]

    def drop(self, client_id: str) -> None:
        """Forget a client entirely (on disconnect)."""
        if self._clients.pop(client_id, None) is not None:
            log.info("history dropped for client %s", client_id)

    def get(self, client_id: str) -> ClientHistory:
        return self.register(client_id)

    def client_ids(self) -> list[str]:
        return list(self._clients.keys())


REGISTRY = HistoryRegistry()


def new_client_id() -> str:
    """Generate a short, unique, non-guessable client identifier."""
    return secrets.token_urlsafe(8)
