"""
fanta-lab Copilot — Model-Agnostic LLM Tactical Engine.

Provider priority: Ollama → OpenAI-compatible → Gemini → Heuristic fallback.
"""

from copilot.providers import get_copilot_provider, get_copilot_diagnostics, test_all_providers, CopilotProvider
from copilot.prompts import build_system_prompt, build_user_prompt

__all__ = ["get_copilot_response", "get_copilot_provider", "get_copilot_diagnostics", "test_all_providers"]


def get_copilot_response(prompt: str, team_context: dict, top_players: list, budget_total: int = 1000, is_personal: bool = False) -> dict | None:
    """
    Query the active copilot provider with grounded context.
    Returns dict with {type, title, text, engine} or None if LLM unavailable.
    """
    provider = get_copilot_provider()
    if provider is None:
        return None

    system_prompt = build_system_prompt(team_context, budget_total, is_personal=is_personal)
    user_prompt = build_user_prompt(prompt, top_players)

    try:
        reply = provider.query(system_prompt, user_prompt)
        if reply:
            engine_name = getattr(provider, "last_successful_engine", None) or provider.engine_name
            bot_title = "Risposta Tattica Personalizzata" if is_personal else "Risposta Tattica FantaMoneyball AI"
            return {
                "type": "llm_chat",
                "title": bot_title,
                "text": reply,
                "engine": engine_name
            }
    except Exception:
        pass

    return None
