"""Tests for detection_classification: domain mapping and vocabulary lookup.

The LLM call itself is mocked: these tests cover the normalization of
model answers, the fallback chain of vocabulary files, and that
find_domain degrades gracefully without an API key.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

import detection_classification as dc


class TestNormalizeDomain:
    def test_exact_match(self):
        assert dc._normalize_domain("pastoral") == "pastoral"

    def test_case_and_punctuation(self):
        assert dc._normalize_domain("Pastoral.") == "pastoral"
        assert dc._normalize_domain('  "Médecine"! ') == "médecine"

    def test_unknown_becomes_default(self):
        assert dc._normalize_domain("cuisine") == dc.DEFAULT_DOMAIN
        assert dc._normalize_domain("") == dc.DEFAULT_DOMAIN


class TestFindDomain:
    def test_empty_phrase(self):
        assert dc.find_domain("") == dc.DEFAULT_DOMAIN

    def test_no_api_key_falls_back(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        assert dc.find_domain("le berger garde son troupeau") == dc.DEFAULT_DOMAIN

    def test_client_failure_falls_back(self, monkeypatch):
        class BrokenClient:
            def chat(self, **kwargs):
                raise RuntimeError("api down")

        assert dc.find_domain("une phrase", client=BrokenClient()) == dc.DEFAULT_DOMAIN

    def test_mocked_answer_normalized(self, monkeypatch):
        class OkClient:
            class chat:
                @staticmethod
                def complete(**kwargs):
                    class Msg:
                        content = "Théologique."

                    class Choice:
                        message = Msg()

                    class Resp:
                        choices = (Choice(),)

                    return Resp()

        assert (
            dc.find_domain("la providence divine", client=OkClient()) == "théologique"
        )


class TestVocabularyForDomain:
    def test_pastoral_file_exists(self):
        vocab = dc.vocabulary_for_domain("pastoral")
        assert vocab and "berger" in vocab

    def test_slug_lookup_accents(self):
        # "théologique" -> slug theologique: file is named théologique.txt
        vocab = dc.vocabulary_for_domain("théologique")
        assert vocab and "trinité" in vocab

    def test_unknown_domain_yields_empty(self):
        vocab = dc.vocabulary_for_domain("astronomie")  # no dedicated file
        assert vocab == []

    def test_default_domain_yields_empty(self):
        assert dc.vocabulary_for_domain(dc.DEFAULT_DOMAIN) == []


class TestSlug:
    def test_spaces_and_accents(self):
        assert dc._slug("automatisation de la maison") == "automatisation_de_la_maison"
        assert dc._slug("Théologique") == "theologique"
