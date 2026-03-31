"""AI service factory — selects Gemini or Claude based on config."""

from backend.config import settings


def get_ai_service():
    """Return the active AI service module (gemini_ai or claude_ai).

    Both modules expose the same async function signatures:
      analyze_news(articles, context) -> str
      analyze_news_for_alert(articles, positions) -> dict
      search_and_analyze(query, context) -> dict
      analyze_market_signal(symbol, name, value, change_percent, threshold_type) -> str
    """
    if settings.DEFAULT_AI_MODEL == "gemini":
        from backend.services import gemini_ai
        return gemini_ai
    from backend.services import claude_ai
    return claude_ai
