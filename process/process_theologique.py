"""Domain-specific processor for 'theologique' (theology) domain.

This module provides custom responses for theological questions about
Doctrine, church history, theological concepts, etc.
When a phrase is classified as 'theologique' (or 'théologique'), this processor
is called first before falling back to process_ai().

Return a non-empty string for a custom response, or empty string to let
process_ai() handle it.
"""

from __future__ import annotations


def process_theologique(
    realtime_text: str,
    batch_text: str,
    client_id: str = "",
    domain: str = "",
    history: list[dict] | None = None,
) -> str:
    """Process phrases in the 'theologique' domain.
    
    Handles theological questions about doctrine, church history,
    theological concepts, etc.
    
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
    
    # Trinity
    if any(kw in lower_text for kw in ["trinite", "trinité", "sainte trinite", "sainte trinité",
                                         "pere fils saint esprit", "trois personnes"]):
        return "La Trinite est un seul Dieu en trois personnes : 1. Le Pere. 2. Le Fils. 3. Le Saint-Esprit. Trois personnes distinctes mais une seule essence divine."
    
    # Incarnation
    if any(kw in lower_text for kw in ["incarnation", "jesus s'est fait homme",
                                         "verbe s'est fait chair"]):
        return "L'Incarnation est le dogme qui affirme que Jesus-Christ, le Fils de Dieu, a pris nature humaine dans le sein de Marie. Il est vrai Dieu et vrai homme."
    
    # Justification vs Sanctification
    if any(kw in lower_text for kw in ["difference justification", 
                                         "justification sanctification",
                                         "justifie vs sanctifie"]):
        return "La justification est l'acte par lequel Dieu nous declare justes par la foi en Christ. La sanctification est le processus par lequel il nous rend effectivement saints. La justification est instantanee, la sanctification est progressive."
    
    # Council of Nicaea
    if any(kw in lower_text for kw in ["concile de nicee", "nicee 325",
                                         "credo de nicee"]):
        return "Le Concile de Nicee en 325 a affirme la divinite du Christ contre l'heresie d'Arius. Il a produit le Credo de Nicee, fondement de la foi chretienne en la Trinite."
    
    # Protestant Reformation
    if any(kw in lower_text for kw in ["reforme protestante", "martin luther",
                                         "1517", "95 these"]):
        return "La Reforme protestante a commence en 1517 avec Martin Luther. Elle a souligne : 1. La justification par la foi seule. 2. L'autorite de l'Ecriture seule. 3. Le sacerdoce universel des croyants."
    
    # Soteriology
    if any(kw in lower_text for kw in ["soteriologie", "sauvetage", "salut"]):
        return "La soteriologie est l'etude du salut. Elle explore comment Dieu sauve l'humanite du peche par la grace, a travers la mort et la resurrection de Jesus-Christ."
    
    # Eschatology
    if any(kw in lower_text for kw in ["eschatologie", "fin des temps", 
                                         "retour de christ", "jugement dernier"]):
        return "L'eschatologie traite des choses dernieres : 1. Le retour du Christ. 2. La resurrection des morts. 3. Le jugement final. 4. La creation nouvelle."
    
    # Ecclesiology
    if any(kw in lower_text for kw in ["ecclesiologie", "eglise", 
                                         "corps du christ"]):
        return "L'ecclesiologie est l'etude de l'Eglise. L'Eglise est le corps du Christ, la communaute des croyants, appelee a etre sel et lumiere dans le monde."
    
    # Christology
    if any(kw in lower_text for kw in ["christologie", "nature du christ",
                                         "jesus dieu et homme"]):
        return "La christologie etudie la personne et l'oeuvre de Jesus-Christ. Il est a la fois pleinement Dieu et pleinement homme, une seule personne avec deux natures."
    
    # No specific match
    return ""
