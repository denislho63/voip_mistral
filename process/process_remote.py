"""Remote processing module for domain-specific processing via web service.

This module provides the ability to call external web services for processing
phrases in specific domains. Each domain can have its own endpoint URL and
authentication token configured in the remote_config.json file.

The module sends all parameters (realtime_text, batch_text, client_id, domain, history)
as JSON and returns the response text from the remote service.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import httpx2 as httpx

if TYPE_CHECKING:
    pass

log = logging.getLogger("phone-stream.remote")

# Configuration file path
CONFIG_PATH = Path(__file__).resolve().parent / "config" / "remote_config.json"

# Cache for loaded configuration
_config: dict | None = None


def _load_config() -> dict:
    """Load the remote configuration from JSON file."""
    global _config
    if _config is not None:
        return _config
    
    if not CONFIG_PATH.is_file():
        log.warning("Remote config file not found: %s", CONFIG_PATH)
        _config = {"domains": {}}
        return _config
    
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            _config = json.load(f)
        log.info("Remote configuration loaded from %s", CONFIG_PATH)
        return _config
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Failed to load remote config: %s", exc)
        _config = {"domains": {}}
        return _config


def _get_domain_config(domain: str) -> dict | None:
    """Get configuration for a specific domain."""
    config = _load_config()
    return config.get("domains", {}).get(domain)


def process_remote(
    realtime_text: str,
    batch_text: str,
    client_id: str = "",
    domain: str = "",
    history: list[dict] | None = None,
) -> str:
    """Process a phrase by calling a remote web service.
    
    This function sends all parameters as JSON to the configured endpoint
    for the domain and returns the response text.
    
    Args:
        realtime_text: The realtime transcription
        batch_text: The batch transcription (with vocabulary bias)
        client_id: Client identifier
        domain: The detected domain
        history: Conversation history for context
    
    Returns:
        The response text from the remote service, or empty string on error.
    """
    if not domain:
        log.debug("No domain specified for remote processing")
        return ""
    
    # Get configuration for this domain
    domain_config = _get_domain_config(domain)
    if domain_config is None:
        log.debug("No remote configuration for domain '%s'", domain)
        return ""
    
    url = domain_config.get("url")
    token = domain_config.get("token")
    
    if not url:
        log.warning("No URL configured for domain '%s'", domain)
        return ""
    
    # Build the request payload with all parameters
    payload = {
        "realtime_text": realtime_text,
        "batch_text": batch_text,
        "client_id": client_id,
        "domain": domain,
        "history": history or [],
    }
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    # Add authorization header if token is configured
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    try:
        # Use httpx for synchronous HTTP requests (compatible with async code via threading)
        timeout = httpx.Timeout(10.0, connect=5.0)
        
        log.debug("Calling remote service for domain '%s' at %s", domain, url)
        
        response = httpx.post(
            url,
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        
        # Check for successful response
        response.raise_for_status()
        
        # Parse response JSON
        response_data = response.json()
        
        # Extract the response text - handle different response formats
        if isinstance(response_data, dict):
            # Try common field names
            for field in ["response", "text", "answer", "result", "output"]:
                if field in response_data:
                    return str(response_data[field])
            # If no known field, return the whole dict as string
            return str(response_data)
        elif isinstance(response_data, str):
            return response_data
        else:
            return str(response_data)
            
    except httpx.HTTPStatusError as exc:
        log.error("Remote service returned error for domain '%s': %s %s", 
                  domain, exc.response.status_code, exc.response.text[:200])
        return ""
    except httpx.RequestError as exc:
        log.error("Failed to call remote service for domain '%s': %s", domain, exc)
        return ""
    except (json.JSONDecodeError, ValueError) as exc:
        log.error("Invalid response from remote service for domain '%s': %s", domain, exc)
        return ""
    except Exception as exc:
        log.error("Unexpected error calling remote service for domain '%s': %s", domain, exc)
        return ""
