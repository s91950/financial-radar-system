"""VM 端 Gemini 定時新聞深度分析服務。

取代本地 NotebookLM 腳本的雲端替代方案：
- 直接在 VM 上用 Gemini API 分析近 N 小時新聞
- 使用與 NLM 相同的分析師合議 SKILL 框架
- 結果獨立存放（report_type="gemini_news" / "gemini_yt"），不覆蓋 NLM 報告
"""

import logging
from datetime import datetime, timedelta, timezone

from backend.config import settings
from backend.database import Article, NlmReport, SessionLocal, SystemConfig, YoutubeVideo

logger = logging.getLogger(__name__)

# 嚴重度關鍵字（與 notebooklm_hourly.py 對齊）
_CRIT_KWS = {"崩盤", "暴跌", "暴漲", "危機", "緊急", "衝擊", "崩潰", "戰爭", "制裁", "封鎖", "違約", "破產"}
_HIGH_KWS = {"下跌", "上漲", "升息", "降息", "通膨", "衰退", "波動", "警告", "風險", "貶值", "升值",
             "利率", "匯率", "油價", "黃金", "股市", "台積", "輝達", "聯準"}


def _article_severity(title: str) -> str:
    if any(k in title for k in _CRIT_KWS):
        return "critical"
    if any(k in title for k in _HIGH_KWS):
        return "high"
    return "low"


def _effective_sev(a) -> str:
    """從 Article ORM 物件取得嚴重度。"""
    db_sev = getattr(a, "severity", None)
    if db_sev in ("critical", "high", "low"):
        return db_sev
    return _article_severity(a.title or "")


def _build_news_prompt(article_count: int) -> str:
    """建構 Gemini 新聞分析提示詞（與 NLM SKILL 框架對齊）。"""
    max_cat = "1" if article_count < 10 else "3"

    return (
        "你是一個「定期市場新聞分析簡報」系統，由多名頂尖金融專業人士組成的分析團隊執行。\n\n"
        "【分析師合議框架】\n"
        "運作方式等同於召集一組各有 20-30 年底蘊的賣方/買方分析師舉行圓桌會議，"
        "針對本時段新聞交叉討論，最後由總編輯整併成一份流暢的合議報告。\n\n"
        "核心分析師池：總經/央行分析師、利率/固收策略師、FX 策略師、"
        "信用分析師、台股/亞股策略師、跨市場總編。\n"
        "根據新聞性質動態加入：能源分析師、半導體產業分析師、日本市場專家、"
        "中國市場專家、私募信貸專家、數位資產策略師等。\n\n"
        "四層思考（每類別必須涵蓋）：\n"
        "1. 各市場視角：同一事件在債、匯、股、信用市場的不同解讀\n"
        "2. 市場參與者行為：誰在買、誰在賣、誰被迫調整\n"
        "3. 國別關聯：跨國傳導路徑（美國→日本→亞洲→台灣）\n"
        "4. 產業/公司層級：具體點名代表性公司或機構\n\n"
        "【本次執行指示】\n"
        f"本批次共 {article_count} 篇新聞。"
        f"請從五大類別（總經/央行政策、台股/亞股、信用市場/私募信貸、"
        f"FX/大宗商品/地緣政治、財金總經綜合）中，"
        f"選出最重要的 1～{max_cat} 個有料類別進行分析；無料類別直接省略，不得硬湊。\n\n"
        "【三段式格式（嚴格遵守）】\n"
        "每個類別固定輸出三點，對應：\n"
        "① 事件 + 市場反應（What + How，含具體數據、幅度、時序）\n"
        "② 分析師合議解讀（Why it matters，必須點名具體公司/機構，"
        "呈現跨市場/跨國別傳導路徑，禁止「金融股」「科技股」等模糊詞）\n"
        "③ 後續觀察（What to watch，具體可驗證的追蹤項目，含時間/數字/明確關卡，"
        "禁止「持續觀察」「值得關注」等空話）\n\n"
        "【來源標注規則】\n"
        "• 每點結尾附 1-2 則核心新聞網址，格式：[1][2]\n"
        "• 報告末尾統一列出【關鍵新聞來源】區塊，格式：[1] https://...\n"
        "• 同一網址全份報告只出現一次，不得重複引用\n"
        "• 只能根據本次提供的新聞進行分析，禁止引用或虛構未提供的文章\n\n"
        "【用詞紀律】\n"
        "• 避免「今日」「盤前」「盤後」，改用「本時段」「前一時段」「近數小時」\n"
        "• 開頭標註涵蓋時段\n"
        "• 每類別 ≤ 350 字，每點約 100 字\n\n"
        "全程使用繁體中文撰寫。"
    )


def _build_yt_prompt() -> str:
    """建構 Gemini YouTube 分析提示詞。"""
    return (
        "你是一個「YouTube 金融影片定期簡報」系統，由多名頂尖金融專業人士組成的分析團隊執行。\n\n"
        "【分析師合議框架】\n"
        "運作方式等同於召集資深分析師圓桌會議，針對影片內容做深度解讀。"
        "四層思考：各市場視角、市場參與者行為、國別關聯、產業/公司層級。\n\n"
        "【報告格式（嚴格遵守）】\n"
        "• 每支影片獨立一個段落，標題格式：「一、【頻道名稱】影片標題」（依清單順序編號）\n"
        "• 每支影片列「①②③」共 3 個分析點：\n"
        "  ① 內容摘要 + 市場訊號（What：影片主張、關鍵數據、觀點方向）\n"
        "  ② 分析師合議解讀（Why：跨市場傳導路徑、具體點名公司/機構、"
        "參與者行為邏輯；禁止「金融股」「科技股」等模糊詞）\n"
        "  ③ 後續觀察（Watch：具體可驗證項目、價格關卡、時間節點；"
        "禁止「持續觀察」「值得關注」等空話）\n"
        "  每點約 80-100 字\n"
        "• 來源規則：只能分析本次提供的影片，禁止引用未提供的內容\n"
        "• 報告末尾統一列出「影片來源」區塊，"
        "格式「一. 【頻道名稱】標題（URL）」，不得省略此區塊\n"
        "• 全程使用繁體中文撰寫"
    )


def _build_articles_text(articles: list, cutoff: datetime) -> str:
    """將文章清單轉為 Gemini 可讀的純文字輸入。"""
    tw = timezone(timedelta(hours=8))
    now_tw = datetime.now(timezone.utc).astimezone(tw).strftime("%Y/%m/%d %H:%M")
    since_tw = cutoff.astimezone(tw).strftime("%m/%d %H:%M")

    lines = [
        f"# 金融偵測新聞摘要（{now_tw} UTC+8）",
        f"**分析時段**：{since_tw} 起 | **共 {len(articles)} 篇**",
        "---",
        "",
    ]
    for i, a in enumerate(articles, 1):
        title = a.title or ""
        source = a.source or ""
        url = a.source_url or ""
        fetched = ""
        if a.fetched_at:
            try:
                fetched = a.fetched_at.replace(tzinfo=timezone.utc).astimezone(tw).strftime("%m/%d %H:%M")
            except Exception:
                pass
        lines.append(f"### {i}. {title}")
        lines.append(f"**來源**：{source} | **時間**：{fetched}")
        if url:
            lines.append(f"**連結**：{url}")
        # 附上部分內容（若有）
        content = getattr(a, "content", "") or ""
        if content:
            lines.append(f"**內容摘要**：{content[:300]}")
        lines.append("")

    return "\n".join(lines)


def _build_videos_text(videos: list, cutoff: datetime) -> str:
    """將影片清單轉為 Gemini 可讀的純文字輸入。"""
    tw = timezone(timedelta(hours=8))
    now_tw = datetime.now(timezone.utc).astimezone(tw).strftime("%Y/%m/%d %H:%M")
    since_tw = cutoff.astimezone(tw).strftime("%m/%d %H:%M")

    lines = [
        f"# 金融頻道影片清單（{now_tw} UTC+8）",
        f"**分析時段**：{since_tw} 起 | **共 {len(videos)} 支影片**",
        "",
    ]
    for i, v in enumerate(videos, 1):
        pub = ""
        if v.published_at:
            try:
                pub = v.published_at.replace(tzinfo=timezone.utc).astimezone(tw).strftime("%m/%d %H:%M")
            except Exception:
                pass
        channel = v.channel.name if v.channel else ""
        lines.append(f"- [{channel}] {v.title} ({pub})")
        if v.url:
            lines.append(f"  {v.url}")

    return "\n".join(lines)


async def run_gemini_news_analysis(hours_back: int = 3, min_severity: str = "low") -> str | None:
    """在 VM 上執行 Gemini 新聞深度分析。

    Returns:
        分析報告 Markdown 文字，或 None（無文章/API 失敗）。
    """
    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY in ("", "your_gemini_api_key_here"):
        logger.warning("[Gemini分析] 未設定 GEMINI_API_KEY，跳過")
        return None

    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=hours_back)

        # 取得近 N 小時文章
        all_articles = (
            db.query(Article)
            .filter(Article.fetched_at >= cutoff)
            .order_by(Article.fetched_at.desc())
            .limit(500)
            .all()
        )

        # 嚴重度篩選
        sev_rank = {"critical": 3, "high": 2, "low": 0}
        min_rank = sev_rank.get(min_severity, 0)
        articles = [a for a in all_articles if sev_rank.get(_effective_sev(a), 0) >= min_rank]

        # 自動縮減：超過 120 篇時只取 high+
        if len(articles) > 120:
            articles = [a for a in articles if _effective_sev(a) in ("critical", "high")]
            logger.info("[Gemini分析] 文章數超過 120，縮減至 high+ 共 %d 篇", len(articles))

        if not articles:
            logger.info("[Gemini分析] 無符合條件的新聞文章，跳過")
            return None

        logger.info("[Gemini分析] 開始分析 %d 篇新聞...", len(articles))

        # 建構輸入
        articles_text = _build_articles_text(articles, cutoff)
        prompt = _build_news_prompt(len(articles))
        full_prompt = f"{prompt}\n\n---\n\n以下是本時段的新聞資料：\n\n{articles_text}"

        # 呼叫 Gemini API
        from google import genai

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = await client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=full_prompt,
        )
        report = response.text
        if not report:
            logger.warning("[Gemini分析] API 回傳空白結果")
            return None

        logger.info("[Gemini分析] 完成，共 %d 字", len(report))

        # 存入 DB（report_type="gemini_news"，獨立於 NLM）
        now_utc = datetime.now(timezone.utc)
        tw = timezone(timedelta(hours=8))
        source_title = f"Gemini新聞_{now_utc.astimezone(tw).strftime('%Y%m%d_%H%M')}"

        db.add(NlmReport(
            report_type="gemini_news",
            content=report,
            generated_at=now_utc,
            source_title=source_title,
        ))
        # 更新 SystemConfig（供 LINE bot 快速取用）
        for key, value in [
            ("gemini_latest_report", report),
            ("gemini_report_generated_at", now_utc.isoformat()),
            ("gemini_report_source_title", source_title),
        ]:
            row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
            if row:
                row.value = value
            else:
                db.add(SystemConfig(key=key, value=value))
        db.commit()

        return report

    except Exception as e:
        logger.error("[Gemini分析] 失敗：%s", e, exc_info=True)
        return None
    finally:
        db.close()


async def run_gemini_yt_analysis(hours_back: int = 3) -> str | None:
    """在 VM 上執行 Gemini YouTube 影片深度分析。"""
    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY in ("", "your_gemini_api_key_here"):
        logger.warning("[Gemini YT分析] 未設定 GEMINI_API_KEY，跳過")
        return None

    db = SessionLocal()
    try:
        from backend.database import YoutubeChannel
        cutoff = datetime.utcnow() - timedelta(hours=hours_back)

        videos = (
            db.query(YoutubeVideo)
            .join(YoutubeVideo.channel)
            .filter(YoutubeVideo.published_at >= cutoff)
            .order_by(YoutubeVideo.published_at.desc())
            .limit(15)
            .all()
        )

        if not videos:
            logger.info("[Gemini YT分析] 無新影片，跳過")
            return None

        logger.info("[Gemini YT分析] 開始分析 %d 支影片...", len(videos))

        videos_text = _build_videos_text(videos, cutoff)
        prompt = _build_yt_prompt()
        full_prompt = f"{prompt}\n\n---\n\n以下是本時段的影片清單：\n\n{videos_text}"

        from google import genai

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = await client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=full_prompt,
        )
        report = response.text
        if not report:
            logger.warning("[Gemini YT分析] API 回傳空白結果")
            return None

        logger.info("[Gemini YT分析] 完成，共 %d 字", len(report))

        now_utc = datetime.now(timezone.utc)
        tw = timezone(timedelta(hours=8))
        source_title = f"Gemini_YT_{now_utc.astimezone(tw).strftime('%Y%m%d_%H%M')}"

        db.add(NlmReport(
            report_type="gemini_yt",
            content=report,
            generated_at=now_utc,
            source_title=source_title,
        ))
        for key, value in [
            ("gemini_yt_latest_report", report),
            ("gemini_yt_report_generated_at", now_utc.isoformat()),
            ("gemini_yt_report_source_title", source_title),
        ]:
            row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
            if row:
                row.value = value
            else:
                db.add(SystemConfig(key=key, value=value))
        db.commit()

        return report

    except Exception as e:
        logger.error("[Gemini YT分析] 失敗：%s", e, exc_info=True)
        return None
    finally:
        db.close()
