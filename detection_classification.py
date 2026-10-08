"""Domain classification of transcribed phrases.

When a phrase ends, the realtime (streaming) transcription is already
available. We classify that text into a domain (via a small chat model,
deterministic) and pick the custom vocabulary that best matches the
domain before running the batch (second) transcription pass, so the
context_bias contains domain-specific terms instead of a fixed list.

Two layers, usable independently:

- find_domain(phrase): LLM classification, returns a domain label
  ("pastoral", "théologique", "informatique", ...). Falls back to
  DEFAULT_DOMAIN when the model is unavailable or answers oddly.
- vocabulary_for_domain(domain): loads the vocabulary file for a
  domain. Vocabulary files live in vocabularies/<domain>.txt (one term
  per line, '#' starts a comment). Unknown domain or missing file
  yields an empty list (context_bias disabled for that phrase).

Requires mistralai (same client as the rest of the pipeline). Without it,
classification silently degrades to the default vocabulary.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from pathlib import Path

log = logging.getLogger("phone-stream.classification")

ROOT = Path(__file__).resolve().parent

CLASSIFICATION_MODEL = os.environ.get(
    "MISTRAL_CLASSIFICATION_MODEL", "mistral-small-latest"
)

DEFAULT_DOMAIN = "general"

# Domains the classifier is allowed to answer with. Anything else is
# mapped to DEFAULT_DOMAIN (no dedicated vocabulary).
DOMAINS = [
    "pastoral",
    "théologique",
    "automatisation de la maison",
    "astronomie",
    "informatique",
    "médecine",
    "droit",
    "économie",
    "littérature",
    "histoire",
    "géographie",
    "biologie",
    "physique",
    "chimie",
    "arts",
    "musique",
    "sport",
    "politique",
    "philosophie",
    "psychologie",
    "sociologie",
]

VOCABULARY_DIR = ROOT / "vocabularies"

_SYSTEM_PROMPT = (
    "Tu es un expert en classification de textes. Ton rôle est de "
    "déterminer à quel domaine appartient une phrase parmi les "
    "suivants : "
    + ", ".join(DOMAINS)
    + ". Réponds uniquement avec le nom du domaine, sans explication."
)


def _strip_accents(text: str) -> str:
    """Lowercase and remove accents (NFD decomposition, ASCII only)."""
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def _normalize_domain(raw: str) -> str:
    """Map a model answer to a known domain, or DEFAULT_DOMAIN."""
    answer = _strip_accents((raw or "").strip().strip(".!\"' "))
    if not answer:
        return DEFAULT_DOMAIN
    for domain in DOMAINS:
        target = _strip_accents(domain)
        if answer == target:
            return domain
        # tolerate small decorations around the label ("le domaine X")
        if target in answer or answer in target:
            return domain
    return DEFAULT_DOMAIN


def find_domain(phrase: str, client=None) -> str:
    """Classify a phrase into one of the known domains (blocking call).

    Uses a small chat model with temperature 0 for a deterministic
    answer. Returns DEFAULT_DOMAIN if mistralai is unavailable, the key
    is missing, or the call fails — the caller then falls back to the
    global vocabulary, so transcription never breaks because of
    classification.
    """
    phrase = (phrase or "").strip()
    if not phrase:
        return DEFAULT_DOMAIN
    if client is None:
        client = _get_client()
    if client is None:
        return DEFAULT_DOMAIN
    messages = _chat_messages(phrase)
    if messages is None:
        return DEFAULT_DOMAIN
    try:
        response = _chat_complete(client, messages)
        raw = response.choices[0].message.content
    except Exception as exc:
        log.warning("domain classification failed (%s); using %s", exc, DEFAULT_DOMAIN)
        return DEFAULT_DOMAIN
    domain = _normalize_domain(raw)
    log.info("domain of %r: %s", phrase[:60], domain)
    return domain


def _chat_messages(phrase: str):
    """Build the [system, user] messages, across SDK generations."""
    question = f"À quel domaine appartient la phrase suivante : '{phrase}' ?"
    try:
        from mistralai.client.models import (  # type: ignore
            SystemMessage,
            UserMessage,
        )

        return [
            SystemMessage(content=_SYSTEM_PROMPT),
            UserMessage(content=question),
        ]
    except ImportError:
        pass
    try:
        from mistralai.client.models import ChatMessage  # type: ignore

        return [
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(role="user", content=question),
        ]
    except ImportError:
        log.warning("no message class found in mistralai; cannot classify")
        return None


def _chat_complete(client, messages):
    """Call the chat API, across SDK generations."""
    chat = client.chat
    complete = getattr(chat, "complete", None)
    if complete is not None:
        return complete(
            model=CLASSIFICATION_MODEL,
            messages=messages,
            temperature=0.0,
            max_tokens=20,
        )
    return chat(
        model=CLASSIFICATION_MODEL,
        messages=messages,
        temperature=0.0,
        max_tokens=20,
    )


def _get_client():
    """Build a Mistral client lazily, or None when unavailable."""
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        return None
    try:
        from mistralai.client import Mistral  # type: ignore
    except ImportError:
        return None
    return Mistral(api_key=api_key)


def _read_vocabulary_file(path: Path) -> list[str]:
    terms: list[str] = []
    if not path.is_file():
        return terms
    for line in path.read_text(encoding="utf-8").splitlines():
        term = line.split("#", 1)[0].strip()
        if term:
            terms.append(term)
    return terms


def _slug(domain: str) -> str:
    """Filesystem-safe ASCII name for a domain label."""
    slug = _strip_accents(domain).strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    return slug or "general"


def vocabulary_for_domain(domain: str) -> list[str]:
    """Return the custom vocabulary suited to a domain.

    Lookup: vocabularies/<domain slug>.txt, then
    vocabularies/<domain>.txt (e.g. "automatisation de la maison" ->
    automatisation_de_la_maison.txt).

    Empty vocabulary disables the context_bias for the batch pass.
    """
    for candidate in (
        VOCABULARY_DIR / f"{_slug(domain)}.txt",
        VOCABULARY_DIR / f"{domain}.txt",
    ):
        terms = _read_vocabulary_file(candidate)
        if terms:
            return terms
    return []
