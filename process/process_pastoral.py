"""Domain-specific processor for 'pastoral' (religious/spiritual) domain.

This module provides custom responses for pastoral care, biblical references,
prayers, and spiritual questions.
When a phrase is classified as 'pastoral', this processor is called first
before falling back to process_ai().

Return a non-empty string for a custom response, or empty string to let
process_ai() handle it.
"""

from __future__ import annotations


def process_pastoral(
    realtime_text: str,
    batch_text: str,
    client_id: str = "",
    domain: str = "",
    history: list[dict] | None = None,
) -> str:
    """Process phrases in the 'pastoral' domain.
    
    Handles religious/spiritual questions and can provide specific responses
    for pastoral care, biblical references, prayers, etc.
    
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
    
    # Prayers
    if any(kw in lower_text for kw in ["notre pere", "notre père", "priere notre pere",
                                         "je vous salue marie", "priere mariale"]):
        if "notre pere" in lower_text or "notre père" in lower_text:
            return "Notre Pere qui es aux cieux, que ton nom soit sanctifie, que ton regne vienne, que ta volonte soit faite sur la terre comme au ciel. Donne-nous aujourd'hui notre pain de ce jour, pardonne-nous nos offenses comme nous pardonnons aussi a ceux qui nous ont offensés, et ne nous laisse pas succomber a la tentation, mais delivre-nous du mal. Amen."
        return "Je peux te guider dans la priere. Quelle priere souhaites-tu ?"
    
    # Blessing
    if any(kw in lower_text for kw in ["benediction", "benis-moi", 
                                         "demande une benediction"]):
        return "Que le Seigneur te benisse et te garde. Que sa face brille sur toi et t'accorde sa grace. Que le Seigneur tourne son visage vers toi et te donne la paix."
    
    # Confession/Repentance
    if any(kw in lower_text for kw in ["confession", "je veux me confesser",
                                         "pardon de mes peches", "repentir"]):
        return "Le pardon est toujours disponible. Parle a ton pasteur ou pretre pour une confession complete. Dieu attend ton retour avec amour."
    
    # Bible readings
    if any(kw in lower_text for kw in ["psaume 23", "psaume vingt-trois"]):
        return "Psaume 23 : Le Seigneur est mon berger. Je ne manquerai de rien. Il me fait reposer dans de verts paturages. Il me dirige pres des eaux paisibles. Il restaure mon ame."
    
    if any(kw in lower_text for kw in ["esau et jacob", "esaü et jacob"]):
        return "Esau et Jacob etaient les fils d'Isaac et Rebecca. Esau, l'aine, vendit son droit d'ainesse a Jacob pour un plat de lentilles. Leur histoire illustre les choix et les consequences dans la vie."
    
    if any(kw in lower_text for kw in ["sermon sur la montagne"]):
        return "Le Sermon sur la Montagne, dans l'Evangile de Matthieu, contient les Beatitudes et l'enseignement central de Jesus sur le Royaume des cieux. Heureux les pauvres en esprit, car le royaume des cieux est a eux."
    
    # Verse of the day
    if any(kw in lower_text for kw in ["verset du jour", "verset biblique",
                                         "passage du jour"]):
        return "Le verset du jour est : Confie-toi en l'Eternel de tout ton coeur, et ne t'appuie pas sur ta sagesse. Proverbes 3:5."
    
    # Guided meditation
    if any(kw in lower_text for kw in ["meditation guidee", "mediter",
                                         "temps de meditation"]):
        return "Assieds-toi en silence. Ferme les yeux. Concentre-toi sur ta respiration. Laisse Dieu te parler dans le calme. Commence par 5 minutes chaque jour."
    
    # Shepherd/flock theme
    if any(kw in lower_text for kw in ["berger", "troupeau", "brebis"]):
        return "Le Seigneur est mon berger. Il me connait par mon nom. Il veille sur moi et me guide vers les bons paturages. Je suis en securite dans ses mains."
    
    # No specific match
    return ""
