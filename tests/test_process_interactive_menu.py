"""Tests for the menu-command recognition in process_interactive."""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from process import process_interactive as pi_module


class TestNormalize:
    def test_lowercase_accents_punctuation(self):
        assert pi_module._normalize("État du serveur !") == "etat du serveur"
        assert pi_module._normalize("Explique la Trinité.") == "explique la trinite"
        assert pi_module._normalize("  Concile   de  Nicée  ") == "concile de nicee"


class TestMenuIndex:
    def test_index_built_from_commands_json(self):
        assert len(pi_module.MENU_COMMANDS) > 0
        match = pi_module.MENU_COMMANDS[pi_module._normalize("Notre Père")]
        assert match == ("Pastoral", "Prières", "Notre Père")

    def test_match_exact(self):
        assert pi_module.match_menu_command("Notre Père") == (
            "Pastoral",
            "Prières",
            "Notre Père",
        )

    def test_match_spoken_loosely(self):
        # spoken transcription with punctuation/case drift still matches
        assert pi_module.match_menu_command("notre pere!") == (
            "Pastoral",
            "Prières",
            "Notre Père",
        )

    def test_no_match(self):
        assert pi_module.match_menu_command("il fait beau aujourd'hui") is None


class TestDispatch:
    def test_default_handler_says_fait(self):
        assert pi_module.run_menu_command("Pastoral", "Prières", "Notre Père") == "Fait"

    def test_custom_handler_dispatched_with_three_levels(self, monkeypatch):
        captured = {}

        def fake_handler(theme, sub_theme, command):
            captured.update(theme=theme, sub_theme=sub_theme, command=command)
            return "Traitement personnalisé."

        monkeypatch.setitem(pi_module.HANDLERS, "Notre Père", fake_handler)
        result = pi_module.run_menu_command("Pastoral", "Prières", "Notre Père")
        assert result == "Traitement personnalisé."
        assert captured == {
            "theme": "Pastoral",
            "sub_theme": "Prières",
            "command": "Notre Père",
        }

    def test_handler_exception_falls_back_to_fait(self, monkeypatch):
        def broken_handler(theme, sub_theme, command):
            raise RuntimeError("boom")

        monkeypatch.setitem(pi_module.HANDLERS, "Notre Père", broken_handler)
        assert pi_module.run_menu_command("Pastoral", "Prières", "Notre Père") == "Fait"

    def test_handler_empty_return_falls_back_to_fait(self, monkeypatch):
        monkeypatch.setitem(pi_module.HANDLERS, "Notre Père", lambda *a: "")
        assert pi_module.run_menu_command("Pastoral", "Prières", "Notre Père") == "Fait"


class TestProcessInteractive:
    def test_menu_command_returns_handler_result(self):
        result = pi_module.process_interactive(
            "Redémarre le service.", client_id="c1", domain="informatique"
        )
        assert result == "Fait"

    def test_non_menu_text_returns_empty(self):
        assert pi_module.process_interactive("bonjour comment allez-vous") == ""

    def test_context_kwargs_accepted(self):
        assert (
            pi_module.process_interactive(
                "une phrase", client_id="c1", domain="pastoral", history=[]
            )
            == ""
        )
