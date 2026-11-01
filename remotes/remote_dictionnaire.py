"""Dictionnaire remote service - Example service for word definitions.

This service receives text (a word or a question containing a word) and returns
its definition from a mock database.

Usage:
    # Configure in remote_config.json:
    {
      "domains": {
        "general": {
          "url": "http://localhost:8001/process",
          "token": "your-token"
        }
      }
    }
    
    # Run the service:
    python remotes/remote_dictionnaire.py
    
    # Or with custom config:
    python remotes/remote_dictionnaire.py --port 8001

The service will:
1. Extract a word from the input text (handles questions like "Qu'est-ce que X ?")
2. Look up the word in the mock database
3. Return the definition as JSON response
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .remote_generic import RemoteService

log = logging.getLogger("phone-stream.remote.dictionnaire")


class DictionnaireService(RemoteService):
    """Dictionnaire (dictionary) service for word definitions.
    
    Extends RemoteService to provide word lookup functionality.
    Uses a mock database of definitions.
    """
    
    # Authentication - override these in production
    ALLOWED_IPS = ["127.0.0.1", "::1"]
    TOKEN = "dictionnaire-secret-token"
    
    # Server configuration
    HOST = "0.0.0.0"
    PORT = 8001
    
    # Mock database of word definitions (French)
    DEFINITIONS: dict[str, str] = {
        # General words
        "chien": "Animal domestique, mammifere canide, souvent garde comme animal de compagnie.",
        "chat": "Petit mammifere domestique, felin, souvent garde comme animal de compagnie.",
        "maison": "Batiment destine a servir d'habitation a des personnes.",
        "voiture": "Vehicule automobile a quatre roues, destine au transport de personnes.",
        "arbre": "Plante vivace, caracterisee par un tronc et des branches portant des feuilles.",
        
        # IT terms
        "api": "Interface de Programmation d'Application. Ensemble de definitions et de protocoles permettant a des applications de communiquer.",
        "serveur": "Ordinateur ou systeme qui fournit des ressources, des donnees ou des services a d'autres ordinateurs (clients) sur un reseau.",
        "internet": "Reseau mondial de reseaux informatiques interconnectes, utilisant le protocole IP.",
        "reseau": "Systeme de communication qui permet l'echange d'informations entre differents appareils.",
        "ordinateur": "Machine electronique capable de traiter automatiquement des informations.",
        
        # Religious terms
        "bible": "Ensemble des ecrits sacres du christianisme, divise en Ancien et Nouveau Testament.",
        "evangile": "Recit de la vie et des enseignements de Jesus-Christ, dans le Nouveau Testament.",
        "priere": "Acte religieux consistant a s'adresser a Dieu ou a une divinite.",
        "foi": "Croyance en quelque chose sans preuve tangible, souvent associee a la religion.",
        "eglise": "Communaute des croyants en Jesus-Christ, ou batiment ou ils se reunissent.",
        
        # Theological terms
        "theologie": "Etude systematique des questions relatives a Dieu, a la religion et a la spiritualite.",
        "dieu": "Etre supreme, createur de l'univers dans les religions monotheistes.",
        "peche": "Acte ou pensee consideree comme mauvaise ou contraire a la loi divine.",
        "grace": "Faveur divine, aide spirituelle accordee par Dieu.",
        "saint": "Personne reconnue pour sa saintete ou son lien particulier avec le divin.",
    }
    
    def __init__(self):
        """Initialize the dictionary service."""
        super().__init__()
        # Load additional definitions from environment if available
        self._load_custom_definitions()
    
    def _load_custom_definitions(self):
        """Load additional definitions from environment variables.
        
        Set DICT_DEFINITIONS as JSON string to add custom definitions.
        Example: DICT_DEFINITIONS='{"mot": "definition"}'
        """
        import os
        import json
        
        custom_defs = os.environ.get("DICT_DEFINITIONS")
        if custom_defs:
            try:
                additional = json.loads(custom_defs)
                if isinstance(additional, dict):
                    self.DEFINITIONS.update(additional)
                    log.info("Loaded %d custom definitions from environment", len(additional))
            except (json.JSONDecodeError, ValueError) as exc:
                log.error("Failed to load custom definitions: %s", exc)
    
    def process(self, data: dict) -> dict:
        """Process incoming data and return word definition.
        
        Extracts a word from the input text and returns its definition.
        Handles various input formats:
        - Direct word: "chien"
        - Question: "Qu'est-ce qu'un chien ?"
        - Phrase: "Peux-tu me dire ce qu'est un chien ?"
        
        Args:
            data: Request data containing:
                - realtime_text: The transcribed text
                - batch_text: The batch-processed text
                - client_id: Client identifier
                - domain: Domain classification
                - history: Conversation history
        
        Returns:
            Dictionary with 'response' field containing the definition,
            or an error message if word not found.
        """
        # Get the text to process (prefer batch_text if available)
        text = data.get("batch_text") or data.get("realtime_text", "")
        
        if not text:
            return {"response": "Aucun texte recu."}
        
        # Extract word from text
        word = self._extract_word(text)
        
        if not word:
            return {"response": "Je n'ai pas puisse identifier de mot a definir."}
        
        # Look up definition
        definition = self.DEFINITIONS.get(word.lower())
        
        if definition:
            log.info("Definition found for '%s'", word)
            return {"response": definition}
        else:
            log.warning("No definition found for '%s'", word)
            return {"response": f"Je ne connais pas la definition de '{word}'."}
    
    def _extract_word(self, text: str) -> str:
        """Extract a word to look up from the input text.
        
        Handles various formats:
        - "word" -> "word"
        - "Qu'est-ce qu'un word ?" -> "word"
        - "C'est quoi un word ?" -> "word"
        - "Peux-tu me dire ce qu'est un word ?" -> "word"
        - "Definition de word" -> "word"
        
        Returns the extracted word in lowercase.
        """
        if not text:
            return ""
        
        text_lower = text.lower().strip()
        
        # Remove punctuation for easier matching, but keep apostrophes
        # This preserves "qu'est" and "c'est" 
        text_clean = re.sub(r'[\"\`\?\!\.,;:]', '', text_lower)
        # Also remove backticks if any
        text_clean = text_clean.replace('`', '')
        
        # Common question patterns - try to match word after question prefix
        # Pattern: everything before the last word is a question prefix
        # We look for common prefixes and extract what comes after
        
        prefixes = [
            "qu'est-ce qu'un ",
            "qu'est-ce qu'une ",
            "qu'est-ce que ",
            "c'est quoi un ",
            "c'est quoi une ",
            "c'est quoi ",
            "qu'est ",
            "definition de ",
            "quel est le sens de ",
            "donne la definition de ",
            "défini ",
            "defini ",
            "peux-tu me dire ce qu'est un ",
            "peux tu me dire ce qu'est un ",
        ]
        
        for prefix in prefixes:
            if text_clean.startswith(prefix):
                # Extract what comes after the prefix
                word = text_clean[len(prefix):].strip()
                # Get the first word
                if word:
                    first_word = word.split()[0]
                    # Remove any remaining punctuation
                    first_word = re.sub(r"['`]", "", first_word)
                    if first_word:
                        return first_word.lower()
        
        # If no pattern matched, try to find the most significant word
        # (filter out common words)
        words = text_clean.split()
        if words:
            # Filter out common question words
            stop_words = {
                'que', 'est', 'ce', 'un', 'une', 'le', 'la', 'les', 'des',
                'de', 'pour', 'tu', 'peux', 'me', 'dire', 'svp', "s'il",
                'te', 'donner', 'du', 'au', 'dans', 'ou', 'qui', 'quoi',
                'qu', 'c', 'est',
            }
            
            significant_words = [w for w in words if w not in stop_words and len(w) > 2]
            
            if significant_words:
                # Return the first significant word
                return significant_words[0].lower()
        
        # Fallback: return the first word
        if words:
            return words[0].lower()
        
        return ""


# Allow running as standalone service
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Dictionnaire remote service")
    parser.add_argument("--host", type=str, default=DictionnaireService.HOST, help="Server host")
    parser.add_argument("--port", type=int, default=DictionnaireService.PORT, help="Server port")
    args = parser.parse_args()
    
    DictionnaireService.run(host=args.host, port=args.port)
