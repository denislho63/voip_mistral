"""process_ai hook: LLM-powered text processing for unhandled phrases.

This module provides an AI-based fallback for processText() when no other
treatment has produced output. It uses the Mistral API to generate a natural,
concise response that is optimized for voice reading.

Key features:
- Concise responses suitable for speech synthesis
- Numbered lists for easy voice navigation
- Clear section markers and keywords for voice interaction
- Context-aware based on domain and history
- Graceful degradation when Mistral API is unavailable
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

log = logging.getLogger("phone-stream.ai")

# Configuration
AI_MODEL = os.environ.get("PHONE_STREAM_AI_MODEL", "mistral-large-4")
AI_TEMPERATURE = float(os.environ.get("PHONE_STREAM_AI_TEMPERATURE", "0.3"))
AI_MAX_TOKENS = int(os.environ.get("PHONE_STREAM_AI_MAX_TOKENS", "256"))

# System prompt for voice-optimized responses
# Encourages: concise answers, numbered lists, voice navigation keywords
_SYSTEM_PROMPT = """Tu es un assistant vocal qui répond de manière claire et concise, adaptée à la lecture à voix haute.

Règles importantes :
1. Sois BREF et direct. Une phrase courante, pas un essai.
2. Si la réponse contient une liste, NUMÉROTE toujours les éléments (1., 2., 3.) pour faciliter la navigation vocale.
3. Utilise des mots-clés de navigation pour la voix : "D'abord", "Ensuite", "Enfin", "Premièrement", "Deuxièmement", "Pour résumer", "En conclusion".
4. Évite les paragraphes longs. Préfère des phrases courtes et claires.
5. Si tu donnes des instructions, utilise des étapes numérotées.
6. Adapté au domaine spécifié dans le contexte.
7. Si le domaine est inconnu ou vide, réponds de manière générique mais utile.
8. N'inclue JAMAIS de balises Markdown, HTML, ou de formatage spécial.
9. Réponds UNIQUEMENT dans la langue de la question.

Exemples de bonnes réponses :
- "Voici les étapes : 1. Ouvre l'application. 2. Va dans les paramètres. 3. Sélectionne l'onglet réseau."
- "La capitale de la France est Paris."
- "D'abord, vérifie la connexion. Ensuite, redémarre l'appareil. Enfin, teste à nouveau."

Exemples de mauvaises réponses :
- "Je pense que..." (trop hésitant)
- "Voici ce que je trouvais..." (trop long)
- "- Point un\n- Point deux" (pas numéroté)
- "Tu pourrais essayer de..." (pose une question implicite)"""


def _get_client():
    """Build a Mistral client if API key is available, else None."""
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        return None
    try:
        from mistralai.client import Mistral
        return Mistral(api_key=api_key)
    except ImportError:
        return None


def _build_messages(
    realtime_text: str,
    batch_text: str,
    domain: str,
    history: list[dict] | None,
) -> list[dict]:
    """Build the conversation context for the LLM.
    
    Includes:
    - System prompt for voice-optimized responses
    - Domain context
    - Conversation history (if available)
    - The current phrase to respond to
    """
    messages = []
    
    # System message
    messages.append({"role": "system", "content": _SYSTEM_PROMPT})
    
    # Domain context (helps the model adapt its style)
    if domain:
        messages.append({
            "role": "system",
            "content": f"Domaine de la conversation : {domain}. "
                       "Adapte ton vocabulaire et ton style à ce domaine."
        })
    
    # History context (previous exchanges in this domain)
    if history:
        history_texts = []
        for record in history[-10:]:  # Last 10 records for context
            role = record.get("role", "")
            text = record.get("text", "")
            if text:
                if role == "phrase":
                    history_texts.append(f"Utilisateur: {text}")
                elif role in ("response", "command"):
                    history_texts.append(f"Assistant: {text}")
        
        if history_texts:
            messages.append({
                "role": "system",
                "content": "Contexte de la conversation : " + " | ".join(history_texts[-5:])
            })
    
    # User message - use batch_text if available, else realtime_text
    user_text = batch_text or realtime_text
    if not user_text:
        return []
    
    messages.append({
        "role": "user",
        "content": user_text
    })
    
    return messages


def process_ai(
    realtime_text: str,
    batch_text: str,
    client_id: str = "",
    domain: str = "",
    history: list[dict] | None = None,
) -> str:
    """Process a phrase using Mistral LLM to generate a voice-optimized response.
    
    This is designed to be called from processText() as a fallback when no
    other processing has occurred. It returns a concise, voice-friendly response.
    
    Args:
        realtime_text: The realtime transcription of the phrase
        batch_text: The batch transcription (with vocabulary bias)
        client_id: Identifier for the connected client
        domain: The detected domain for vocabulary context
        history: Previous exchanges in this domain for context
    
    Returns:
        The AI-generated response text, optimized for voice reading.
        Returns an empty string if the AI call fails or is unavailable.
    
    Features:
        - Concise, direct responses
        - Numbered lists for easy voice navigation
        - Domain-specific vocabulary adaptation
        - Context-aware based on conversation history
    """
    client = _get_client()
    if client is None:
        log.debug("Mistral client not available for process_ai")
        return ""
    
    # Log that history was received for debugging
    if history:
        log.debug("process_ai received history with %d records for domain '%s'", len(history), domain)
    
    messages = _build_messages(realtime_text, batch_text, domain, history)
    if not messages:
        return ""
    
    try:
        response = client.chat.complete(
            model=AI_MODEL,
            messages=messages,
            temperature=AI_TEMPERATURE,
            top_p=1.0 if AI_TEMPERATURE == 0 else 0.9,
            max_tokens=AI_MAX_TOKENS,
            reasoning_effort="none",
        )
        # Extract the response text
        if response and response.choices:
            content = response.choices[0].message.content
            if content:
                # Ensure content is a string before processing
                if isinstance(content, str):
                    # Clean up the response
                    result = content.strip()
                    
                    # Ensure we end with a sentence-ending punctuation for TTS
                    if result and result[-1] not in ('.', '!', '?', ';', ':'):
                        result += '.'
                    
                    log.info("AI response for '%s': %s", (batch_text or realtime_text)[:50], result[:100])
                    return result
                else:
                    log.warning("AI returned non-string content: %s", type(content))

    except Exception as exc:
        log.warning("AI processing failed: %s", exc)
    
    return ""
