"""Tests for client_history and its wiring into the hooks.

Covers: per-client isolation, per-domain separation, the capped deque,
the registry lifecycle, and — through monkeypatched hooks — that
processText/process_command actually receive client_id, domain and the
domain-filtered history.
"""

from __future__ import annotations

import sys

import client_history as ch
from client_history import ClientHistory, HistoryRegistry, new_client_id
from process_command import process_command
from process_text import processText

sys.path.insert(0, ".")


class TestClientHistory:
    def test_phrases_split_by_domain(self):
        h = ClientHistory("c1")
        h.add_phrase("pastoral", "le berger")
        h.add_phrase("informatique", "le serveur web")
        assert h.texts("pastoral") == ["le berger"]
        assert h.texts("informatique") == ["le serveur web"]

    def test_history_grows_with_each_phrase(self):
        h = ClientHistory("c1")
        h.add_phrase("pastoral", "phrase 1")
        h.add_phrase("pastoral", "phrase 2")
        records = h.get("pastoral")
        assert len(records) == 2
        assert records[0]["text"] == "phrase 1"  # oldest first
        assert records[1]["text"] == "phrase 2"

    def test_response_and_command_recorded(self):
        h = ClientHistory("c1")
        h.add_phrase("pastoral", "p")
        h.add_response("pastoral", "r")
        h.add_command("pastoral", "cmd")
        roles = [r["role"] for r in h.get("pastoral")]
        assert roles == ["phrase", "response", "command"]

    def test_empty_texts_ignored(self):
        h = ClientHistory("c1")
        h.add_phrase("pastoral", "")
        h.add_command("pastoral", "")
        assert len(h) == 0

    def test_max_entries_capped(self, monkeypatch):
        monkeypatch.setenv("PHONE_STREAM_HISTORY", "3")
        import importlib

        importlib.reload(ch)
        h = ch.ClientHistory("c1")
        for i in range(10):
            h.add_phrase("pastoral", f"p{i}")
        assert len(h.get("pastoral")) == 3
        assert h.texts("pastoral") == ["p7", "p8", "p9"]
        monkeypatch.delenv("PHONE_STREAM_HISTORY")
        importlib.reload(ch)

    def test_domains_listed(self):
        h = ClientHistory("c1")
        h.add_phrase("pastoral", "x")
        h.add_phrase("médecine", "y")
        assert set(h.domains()) == {"pastoral", "médecine"}


class TestRegistry:
    def test_isolation_between_clients(self):
        reg = HistoryRegistry()
        ha = reg.register("alice")
        hb = reg.register("bob")
        ha.add_phrase("pastoral", "phrase d'alice")
        assert hb.texts("pastoral") == []
        assert ha.texts("pastoral") == ["phrase d'alice"]

    def test_register_is_idempotent(self):
        reg = HistoryRegistry()
        h1 = reg.register("alice")
        h1.add_phrase("pastoral", "x")
        h2 = reg.register("alice")
        assert h2 is h1

    def test_drop_forgets_client(self):
        reg = HistoryRegistry()
        reg.register("alice").add_phrase("pastoral", "x")
        reg.drop("alice")
        fresh = reg.register("alice")
        assert fresh.texts("pastoral") == []
        assert len(fresh) == 0

    def test_new_client_ids_unique(self):
        ids = {new_client_id() for _ in range(100)}
        assert len(ids) == 100


class TestHookSignatures:
    def test_process_text_receives_context(self, monkeypatch):
        captured = {}

        def fake_process_text(
            realtime_text, batch_text, client_id="", domain="", history=None
        ):
            captured.update(client_id=client_id, domain=domain, history=history)
            return "ok"

        import speech_pipeline

        monkeypatch.setattr(speech_pipeline, "processText", fake_process_text)

        h = ClientHistory("alice")
        h.add_phrase("pastoral", "ancienne phrase")

        class P:
            client_id = "alice"
            history = h

            def _record_phrase(self, domain, realtime_text, batch_text):
                if self.history is None:
                    return None
                self.history.add_phrase(domain, batch_text or realtime_text)
                return self.history.get(domain)

        history = P()._record_phrase("pastoral", "nouvelle phrase", "nouvelle phrase")
        result = speech_pipeline.processText(
            "nouvelle phrase",
            "nouvelle phrase",
            client_id="alice",
            domain="pastoral",
            history=history,
        )
        assert result == "ok"
        assert captured["client_id"] == "alice"
        assert captured["domain"] == "pastoral"
        assert [r["text"] for r in captured["history"]] == [
            "ancienne phrase",
            "nouvelle phrase",
        ]

    def test_process_command_receives_context(self):
        result = process_command(
            "cmd", client_id="alice", domain="pastoral", history=[]
        )
        assert result == "cmd"

    def test_default_hooks_still_work_without_context(self):
        assert processText("rt", "batch") == "batch"
        assert processText("rt", "") == "rt"
        assert process_command("hello") == "hello"


class TestReconnectionPersistence:
    def test_history_resumes_with_same_id(self):
        reg = HistoryRegistry()
        h = reg.register("alice")
        h.add_phrase("pastoral", "phrase 1")
        # disconnect + reconnect with the same client_id
        h2 = reg.register("alice")
        assert h2 is h
        assert h2.texts("pastoral") == ["phrase 1"]

    def test_history_not_dropped_on_disconnect(self):
        reg = HistoryRegistry()
        reg.register("alice").add_phrase("pastoral", "x")
        # the server no longer calls drop() on disconnect
        assert "alice" in reg.client_ids()
        assert reg.get("alice").texts("pastoral") == ["x"]

    def test_ttl_sweeps_inactive_clients(self, monkeypatch):
        import time as time_mod

        reg = HistoryRegistry()
        h = reg.register("alice")
        h.add_phrase("pastoral", "x")
        # simulate long inactivity: last_seen far in the past
        h.last_seen = time_mod.monotonic() - 999999
        # registering bob triggers a sweep that forgets alice
        reg.register("bob")
        assert "alice" not in reg.client_ids()

    def test_ttl_extended_by_activity(self, monkeypatch):
        reg = HistoryRegistry()
        h = reg.register("alice")
        h.add_phrase("pastoral", "x")
        assert not h.expired()
        reg.register("bob")  # sweep runs, alice is fresh
        assert "alice" in reg.client_ids()
