"""process_domain: Domain-specific processing dispatcher.

This module provides the main entry point for domain-specific processing.
It imports domain processors from their respective modules and dispatches
to the appropriate function based on the detected domain.

If a domain function returns an empty string, the caller should fall back
to process_ai() for generic AI processing.

To add a new domain processor:
1. Create a new file process_<domain>.py with a process_<domain>() function
2. Add the import and mapping in this file
"""

from __future__ import annotations

import logging

log = logging.getLogger("phone-stream.domain")

# Import domain-specific processors
try:
    from .process_informatique import process_informatique
except ImportError:
    process_informatique = None

try:
    from .process_pastoral import process_pastoral
except ImportError:
    process_pastoral = None

try:
    from .process_theologique import process_theologique
except ImportError:
    process_theologique = None

# Dictionary mapping domains to their processing functions
# Keys use both accented and non-accented versions for robustness
_DOMAIN_PROCESSORS = {
    # IT
    "informatique": process_informatique,
    # Pastoral
    "pastoral": process_pastoral,
    # Theology - handle both accented and non-accented
    "theologique": process_theologique,
    "théologique": process_theologique,
    # Other domains (no custom processors yet)
    "automatisation de la maison": None,
    "astronomie": None,
    "medecine": None,
    "médecine": None,
    "droit": None,
    "economie": None,
    "économie": None,
    "litterature": None,
    "littérature": None,
    "histoire": None,
    "geographie": None,
    "géographie": None,
    "biologie": None,
    "physique": None,
    "chimie": None,
    "arts": None,
    "musique": None,
    "sport": None,
    "politique": None,
    "philosophie": None,
    "psychologie": None,
    "sociologie": None,
}


def process_domain(
    realtime_text: str,
    batch_text: str,
    client_id: str = "",
    domain: str = "",
    history: list[dict] | None = None,
) -> str:
    """Process a phrase using domain-specific logic.
    
    This function dispatches to domain-specific processors if available.
    If no processor exists for the domain or the processor returns an empty
    string, the caller should fall back to process_ai().
    
    Args:
        realtime_text: The realtime transcription
        batch_text: The batch transcription (with vocabulary bias)
        client_id: Client identifier
        domain: The detected domain
        history: Conversation history for context
    
    Returns:
        The domain-specific response text, or empty string if no custom
        processing is available for this domain.
    """
    if not domain:
        log.debug("No domain specified, skipping domain processing")
        return ""
    
    # Look up the processor for this domain
    processor = _DOMAIN_PROCESSORS.get(domain)
    
    if processor is None:
        log.debug("No custom processor for domain '%s'", domain)
        return ""
    
    # Call the domain-specific processor
    try:
        result = processor(
            realtime_text=realtime_text,
            batch_text=batch_text,
            client_id=client_id,
            domain=domain,
            history=history,
        )
        
        if result:
            log.info("Domain processor '%s' returned: %s", domain, result[:80])
        else:
            log.debug("Domain processor '%s' returned empty", domain)
        
        return result
        
    except Exception as exc:
        log.warning("Domain processor '%s' failed: %s", domain, exc)
        return ""
