"""Gemini AI integration using the google-genai SDK."""

import json
import logging

from google import genai
from google.genai import types

from backend.config import settings

logger = logging.getLogger(__name__)

_PLACEHOLDER_KEYS = {"", "your_gemini_api_key_here"}


def _is_api_key_valid() -> bool:
    return settings.GEMINI_API_KEY not in _PLACEHOLDER_KEYS


def _get_client() -> genai.Client:
    return genai.Client(api_key=settings.GEMINI_API_KEY)


async def analyze_news(articles: list[dict], context: str = "") -> str:
    """Use Gemini to analyze a batch of news articles.

    Returns a structured analysis in Traditional Chinese.
    """
    if not _is_api_key_valid():
        return "⚠️ 請在 .env 設定有效的 GEMINI_API_KEY 以啟用 AI 分析"

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
        response = await client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
        )
        return response.text
    except Exception as e:
        logger.error(f"Gemini analysis error: {e}")
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            return ""
        return ""


async def analyze_news_for_alert(articles: list[dict], positions: list[dict]) -> dict:
    """Analyze news for push notification — returns structured dict with 4 sections.

    Returns:
        {
            "event_summary": str,    # 發生什麼事（150字）
            "exposure_analysis": str, # 部位暴險（AI評估）
            "follow_up": str,        # 後續發展（200字）
        }
    """
    if not _is_api_key_valid():
        return {
            "event_summary": "（需設定 GEMINI_API_KEY 以啟用 AI 分析）",
            "exposure_analysis": "",
            "follow_up": "",
        }

    articles_text = "\n\n".join(
        f"[{a.get('source', '')}] {a.get('title', '')}\n{a.get('content', '')[:400]}"
        for a in articles[:10]
    )

    positions_text = ""
    if positions:
        positions_text = "持倉部位：\n" + "\n".join(
            f"• {p.get('symbol', '')} {p.get('name', '')} × {p.get('quantity', '')} "
            f"均價 {p.get('avg_price', '')} [{p.get('category', '')}]"
            for p in positions[:20]
        )

    prompt = f"""你是一位資深金融分析師。請閱讀以下新聞內文，以繁體中文進行結構化分析。

最新新聞（含內文）：
{articles_text}

{positions_text}

請用以下 JSON 格式回覆（不要有其他文字）：
{{
  "event_summary": "閱讀以上新聞內文後，整合濃縮成150字以內的事件摘要，說明目前發生了什麼事，勿只列出標題",
  "exposure_analysis": "部位暴險分析：上述持倉中哪些受影響、影響方向與程度，若無持倉則分析一般投資人暴險",
  "follow_up": "後續發展推演，以列點方式呈現三個情境：\\n• 樂觀情境：...\\n• 基本情境：...\\n• 悲觀情境：..."
}}"""

    try:
        client = _get_client()
        response = await client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        result = json.loads(response.text)
        return {
            "event_summary": result.get("event_summary", ""),
            "exposure_analysis": result.get("exposure_analysis", ""),
            "follow_up": result.get("follow_up", ""),
        }
    except Exception as e:
        logger.error(f"Gemini alert analysis error: {e}")
        return {}


_CHINESE_NUMS = "一二三四五六七八九十"


async def analyze_news_groups(groups: list[list[dict]], positions: list[dict]) -> str:
    """Analyze multiple topic groups separately. Returns formatted analysis text with 【】sections."""
    if not _is_api_key_valid():
        return "（需設定 GEMINI_API_KEY 以啟用 AI 分析）"

    if len(groups) == 1:
        result = await analyze_news_for_alert(groups[0], positions)
        if result.get("event_summary"):
            return (
                f"【事件摘要】\n{result['event_summary']}\n\n"
                f"【部位暴險】\n{result['exposure_analysis']}\n\n"
                f"【後續發展】\n{result['follow_up']}"
            )
        return ""

    groups_text = ""
    for i, group in enumerate(groups[:8], 1):
        num = _CHINESE_NUMS[i - 1] if i <= len(_CHINESE_NUMS) else str(i)
        articles_block = "\n".join(
            f"  • [{a.get('source', '')}] {a.get('title', '')}\n    {a.get('content', '')[:300]}"
            for a in group[:5]
        )
        groups_text += f"主題{num}（{len(group)}則）：\n{articles_block}\n\n"

    positions_text = ""
    if positions:
        positions_text = "持倉部位：\n" + "\n".join(
            f"• {p.get('symbol', '')} {p.get('name', '')} × {p.get('quantity', '')} "
            f"均價 {p.get('avg_price', '')} [{p.get('category', '')}]"
            for p in positions[:20]
        )

    n = len(groups[:8])
    prompt = f"""你是資深金融分析師。以下新聞已按主題分組，請對每組分別進行結構化分析，不同主題之間不得混合。

{groups_text}{positions_text}

請用以下 JSON 格式回覆（groups 陣列須有 {n} 個元素，不要有其他文字）：
{{
  "groups": [
    {{
      "event_summary": "閱讀內文後整合濃縮，150字以內，勿只列出標題",
      "exposure_analysis": "部位暴險分析：上述持倉中哪些受影響、方向與程度",
      "follow_up": "• 樂觀情境：一句話\\n• 基本情境：一句話\\n• 悲觀情境：一句話"
    }}
  ]
}}"""

    try:
        client = _get_client()
        response = await client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        result = json.loads(response.text)
        parts = []
        for i, g in enumerate(result.get("groups", []), 1):
            num = _CHINESE_NUMS[i - 1] if i <= len(_CHINESE_NUMS) else str(i)
            parts.append(
                f"【主題{num} 事件摘要】\n{g.get('event_summary', '')}\n\n"
                f"【主題{num} 部位暴險】\n{g.get('exposure_analysis', '')}\n\n"
                f"【主題{num} 後續發展】\n{g.get('follow_up', '')}"
            )
        return "\n\n".join(parts)
    except Exception as e:
        logger.error(f"Gemini group analysis error: {e}")
        return ""


async def search_and_analyze(query: str, context: str = "") -> dict:
    """Use Gemini with Google Search grounding to find and analyze real-time information.

    Returns structured analysis with source citations.
    """
    if not _is_api_key_valid():
        return {
            "analysis": "⚠️ 請在 .env 設定有效的 GEMINI_API_KEY 以啟用 AI 搜尋分析",
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
        response = await client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )

        analysis = response.text
        sources = []

        # Extract grounding metadata if available
        try:
            for candidate in (response.candidates or []):
                meta = getattr(candidate, "grounding_metadata", None)
                if meta:
                    for chunk in getattr(meta, "grounding_chunks", []):
                        web = getattr(chunk, "web", None)
                        if web:
                            sources.append({
                                "title": getattr(web, "title", ""),
                                "url": getattr(web, "uri", ""),
                            })
        except Exception:
            pass

        return {"analysis": analysis, "sources": sources}
    except Exception as e:
        logger.error(f"Gemini search error: {e}")
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
        return "⚠️ 請在 .env 設定有效的 GEMINI_API_KEY 以啟用 AI 分析"

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
        response = await client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
        )
        return response.text
    except Exception as e:
        logger.error(f"Gemini market analysis error: {e}")
        return f"分析暫時無法使用：{e}"
