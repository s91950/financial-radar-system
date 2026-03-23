"""Claude AI integration for analysis and web search."""

import json
import logging

import anthropic

from backend.config import settings

logger = logging.getLogger(__name__)

_PLACEHOLDER_KEYS = {"", "your_anthropic_api_key_here"}


def _is_api_key_valid() -> bool:
    return settings.ANTHROPIC_API_KEY not in _PLACEHOLDER_KEYS


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


async def analyze_news(articles: list[dict], context: str = "") -> str:
    """Use Claude to analyze a batch of news articles.

    Returns a structured analysis in Traditional Chinese.
    """
    if not _is_api_key_valid():
        return "⚠️ 請在 .env 設定有效的 ANTHROPIC_API_KEY 以啟用 AI 分析"

    articles_text = "\n\n".join(
        f"【{a.get('source', 'Unknown')}】{a.get('title', '')}\n{a.get('content', '')[:500]}"
        for a in articles[:10]
    )

    prompt = f"""你是一位資深金融分析師。請分析以下新聞/資訊，以繁體中文回覆：

{f"背景脈絡：{context}" if context else ""}

新聞資料：
{articles_text}

請提供：
1. **重點摘要**：最重要的 3-5 個要點
2. **市場影響**：對股市、債市、匯市可能的影響
3. **風險評估**：潛在風險等級（低/中/高/極高）與原因
4. **建議關注**：後續應該關注的發展方向"""

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"Claude analysis error: {e}")
        return f"AI 分析暫時無法使用：{e}"


async def search_and_analyze(query: str, context: str = "") -> dict:
    """Use Claude with web search to find and analyze real-time information.

    Returns structured analysis with source citations.
    """
    if not _is_api_key_valid():
        return {
            "analysis": "⚠️ 請在 .env 設定有效的 ANTHROPIC_API_KEY 以啟用 AI 搜尋分析",
            "sources": [],
        }

    prompt = f"""你是一位資深金融分析師。請搜尋並分析以下主題的最新資訊，以繁體中文回覆：

主題：{query}
{f"額外脈絡：{context}" if context else ""}

請提供：
1. **事件摘要**：目前發生了什麼事
2. **市場影響分析**：對各類資產的影響評估
3. **部位暴險評估**：持有相關部位的投資人面臨的風險
4. **後續發展預測**：未來可能的走向（樂觀/基本/悲觀情境）
5. **應對建議**：具體的投資建議與風險管理措施

請引用具體的資料來源。"""

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            tools=[{"type": "web_search_20250305"}],
            messages=[{"role": "user", "content": prompt}],
        )

        analysis = ""
        sources = []
        for block in response.content:
            if block.type == "text":
                analysis += block.text
            elif block.type == "web_search_tool_result":
                for search_result in getattr(block, "content", []):
                    if hasattr(search_result, "url"):
                        sources.append({
                            "title": getattr(search_result, "title", ""),
                            "url": search_result.url,
                        })

        return {"analysis": analysis, "sources": sources}
    except Exception as e:
        logger.error(f"Claude search error: {e}")
        return {"analysis": f"AI 搜尋暫時無法使用：{e}", "sources": []}


async def analyze_market_signal(
    symbol: str,
    name: str,
    value: float,
    change_percent: float,
    threshold_type: str,
) -> str:
    """Analyze a market signal that triggered an alert."""
    if not _is_api_key_valid():
        return "⚠️ 請在 .env 設定有效的 ANTHROPIC_API_KEY 以啟用 AI 分析"

    prompt = f"""你是一位資深金融分析師。以下市場指標觸發了警報：

指標：{name} ({symbol})
當前值：{value}
漲跌幅：{change_percent:+.2f}%
觸發條件：{threshold_type}

請簡要分析（繁體中文，200字內）：
1. 這個信號代表什麼
2. 可能的市場影響
3. 建議的應對動作"""

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"Claude market analysis error: {e}")
        return f"分析暫時無法使用：{e}"
