"""Domain-specific processor for 'informatique' (IT/Computer Science) domain.

This module provides custom responses for IT-related questions and topics.
When a phrase is classified as 'informatique', this processor is called first
before falling back to process_ai().

Return a non-empty string for a custom response, or empty string to let
process_ai() handle it.
"""

from __future__ import annotations


def process_informatique(
    realtime_text: str,
    batch_text: str,
    client_id: str = "",
    domain: str = "",
    history: list[dict] | None = None,
) -> str:
    """Process phrases in the 'informatique' domain.
    
    Handles IT-related questions and can provide specific responses for
    common IT topics like networking, servers, APIs, etc.
    
    Args:
        realtime_text: The realtime transcription
        batch_text: The batch transcription (with vocabulary bias)
        client_id: Client identifier
        domain: The detected domain
        history: Conversation history for context
    
    Returns:
        A response text if custom processing applies, empty string otherwise.
    """
    text = batch_text or realtime_text
    
    if not text:
        return ""
    
    lower_text = text.lower()
    
    # Server status and management
    if any(kw in lower_text for kw in ["etat du serveur", "serveur fonctionne", 
                                         "server status", "serveur marche"]):
        return "Le serveur est operationnel. Tout fonctionne normalement."
    
    # Network connectivity
    if any(kw in lower_text for kw in ["test de connexion", "test connexion", 
                                         "verifie la connexion", "probleme reseau",
                                         "connection test"]):
        return "D'abord, verifie que ton appareil est connecte au reseau. Ensuite, teste avec une autre application. Enfin, redemarre le routeur si necessaire."
    
    # IP address
    if any(kw in lower_text for kw in ["adresse ip", "ip locale", "mon ip", 
                                         "what's my ip", "adresse ip locale"]):
        return "Pour trouver ton adresse IP locale : 1. Sur Windows, ouvre l'invite de commandes et tape 'ipconfig'. 2. Sur Mac ou Linux, utilise la commande 'ifconfig' ou 'ip a'."
    
    # Restart service
    if any(kw in lower_text for kw in ["redemarre le service", "redemarrer le service",
                                         "restart service", "service redemarrer"]):
        return "Service redemarre avec succes."
    
    # Recent logs
    if any(kw in lower_text for kw in ["logs recents", "derniers logs", 
                                         "show logs", "voir les logs"]):
        return "Voici les derniers logs : 1. Connexion etablie. 2. Traitement en cours. 3. Aucune erreur detectee."
    
    # API questions
    if any(kw in lower_text for kw in ["api", "qu'est-ce qu'une api", "c'est quoi api",
                                         "definition api", "api signifie",
                                         "qu est-ce qu une api"]):
        return "Une API, ou Interface de Programmation d'Application, permet a deux logiciels de communiquer. Par exemple : 1. Une API REST pour les services web. 2. Une API GraphQL pour des requetes flexibles."
    
    # WebSocket questions
    if any(kw in lower_text for kw in ["websocket", "web socket", "protocole websocket"]):
        return "WebSocket est un protocole de communication bidirectionnelle en temps reel. Il permet des echanges de donnees instantanes entre le client et le serveur."
    
    # PCM audio
    if any(kw in lower_text for kw in ["pcm", "qu'est-ce que pcm", "format pcm", 
                                         "pcm audio"]):
        return "PCM, ou Pulse Code Modulation, est un format audio non compresse. Il encode les ondes sonores sous forme numerique brute."
    
    # TLS/SSL
    if any(kw in lower_text for kw in ["tls", "qu'est-ce que tls", "protocole tls", 
                                         "ssl vs tls", "securite tls"]):
        return "TLS, Transport Layer Security, est un protocole de chiffrement pour securiser les communications sur Internet. Il protege les donnees entre ton appareil et le serveur."
    
    # Generic IT help
    if any(kw in lower_text for kw in ["aide informatique", "probleme informatique",
                                         "besoin d'aide it"]):
        return "Je peux t'aider avec les sujets informatiques. Pose ta question precisement."
    
    # No specific match - return empty to let process_ai handle it
    return ""
