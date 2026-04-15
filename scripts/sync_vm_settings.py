#!/usr/bin/env python3
"""
VM 設定同步腳本
從本地 SQLite 資料庫讀取設定，透過 VM REST API 同步到正式機。

使用方法：
  python scripts/sync_vm_settings.py http://<VM_IP>
  python scripts/sync_vm_settings.py http://<VM_IP>:8000

前置條件：
  pip install requests
"""

import json
import sqlite3
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("請先安裝 requests：pip install requests")
    sys.exit(1)

# ── 設定 ─────────────────────────────────────────────────────────────────────
LOCAL_DB = Path(__file__).parent.parent / "data" / "financial_radar.db"
# ─────────────────────────────────────────────────────────────────────────────


def get_vm_url() -> str:
    if len(sys.argv) < 2:
        print("用法：python scripts/sync_vm_settings.py http://<VM_IP>")
        print("範例：python scripts/sync_vm_settings.py http://34.75.12.34")
        sys.exit(1)
    url = sys.argv[1].rstrip("/")
    if not url.startswith("http"):
        url = "http://" + url
    return url


def api(vm: str, method: str, path: str, data: dict = None):
    url = vm + path
    try:
        if method == "GET":
            r = requests.get(url, timeout=15)
        elif method == "PUT":
            r = requests.put(url, json=data, timeout=15)
        elif method == "POST":
            r = requests.post(url, json=data, timeout=15)
        elif method == "DELETE":
            r = requests.delete(url, timeout=15)
        else:
            raise ValueError(f"Unknown method: {method}")
        r.raise_for_status()
        return r.json()
    except requests.ConnectionError:
        print(f"  [錯誤] 連線失敗：{url}")
        return None
    except requests.HTTPError as e:
        print(f"  [錯誤] HTTP {e.response.status_code}：{url}")
        return None
    except Exception as e:
        print(f"  [錯誤] {e}")
        return None


def load_local_db():
    conn = sqlite3.connect(str(LOCAL_DB))
    conn.row_factory = sqlite3.Row

    # system_config
    configs = {}
    for row in conn.execute("SELECT key, value FROM system_config"):
        configs[row["key"]] = row["value"]

    # monitor_sources (排除 research 類型由 _migrate_db 處理)
    sources = []
    for row in conn.execute(
        "SELECT id, name, type, url, keywords, is_active, fetch_all "
        "FROM monitor_sources WHERE type != 'research' ORDER BY id"
    ):
        sources.append({
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "url": row["url"],
            "keywords": json.loads(row["keywords"]) if row["keywords"] else [],
            "is_active": bool(row["is_active"]),
            "fetch_all": bool(row["fetch_all"]) if row["fetch_all"] is not None else False,
        })

    # topics
    topics = []
    for row in conn.execute(
        "SELECT id, name, keywords, is_active FROM topics ORDER BY id"
    ):
        topics.append({
            "id": row["id"],
            "name": row["name"],
            "keywords": json.loads(row["keywords"]) if row["keywords"] else [],
            "is_active": bool(row["is_active"]),
        })

    conn.close()
    return configs, sources, topics


def sync_system_config(vm: str, configs: dict):
    print("\n── 1. 同步系統設定 (system_config) ──────────────────────────────────────")

    # 1a. radar topics + hours + interval + rss_only
    topics_tw = json.loads(configs.get("radar_topics", "[]"))
    topics_us = json.loads(configs.get("radar_topics_us", "[]"))
    hours_back = int(configs.get("radar_hours_back", "24"))
    interval = int(configs.get("radar_interval_minutes", "5"))
    rss_only = configs.get("radar_rss_only", "false") == "true"

    result = api(vm, "PUT", "/api/settings/radar-topics", {
        "topics": topics_tw,
        "topics_us": topics_us,
        "hours_back": hours_back,
        "interval_minutes": interval,
        "rss_only": rss_only,
    })
    if result:
        print(f"  ✓ radar_topics：{len(topics_tw)} 個 TW + {len(topics_us)} 個 US，"
              f"hours_back={hours_back}，interval={interval}min，rss_only={rss_only}")
    else:
        print("  ✗ radar_topics 同步失敗")

    # 1b. severity keywords
    crit_kw = json.loads(configs.get("severity_critical_kw", "[]"))
    high_kw = json.loads(configs.get("severity_high_kw", "[]"))
    if crit_kw or high_kw:
        result = api(vm, "PUT", "/api/settings/severity-keywords", {
            "critical": crit_kw,
            "high": high_kw,
        })
        if result:
            print(f"  ✓ severity_keywords：critical={len(crit_kw)} 個，high={len(high_kw)} 個")
        else:
            print("  ✗ severity_keywords 同步失敗")

    # 1c. severity rules
    rules = json.loads(configs.get("severity_rules", "[]"))
    result = api(vm, "PUT", "/api/settings/severity-rules", {"rules": rules})
    if result is not None:
        print(f"  ✓ severity_rules：{len(rules)} 條規則")
    else:
        print("  ✗ severity_rules 同步失敗")

    # 1d. finance filter
    ff_enabled = configs.get("finance_filter_enabled", "false") == "true"
    ff_threshold = float(configs.get("finance_relevance_threshold", "0.15"))
    result = api(vm, "PUT", "/api/settings/finance-filter", {
        "enabled": ff_enabled,
        "threshold": ff_threshold,
    })
    if result:
        print(f"  ✓ finance_filter：enabled={ff_enabled}，threshold={ff_threshold}")
    else:
        print("  ✗ finance_filter 同步失敗")

    # 1e. GN critical only
    gn_critical = configs.get("gn_critical_only", "false") == "true"
    result = api(vm, "PUT", "/api/settings/gn-critical-only", {"enabled": gn_critical})
    if result is not None:
        print(f"  ✓ gn_critical_only：{gn_critical}")
    else:
        print("  ✗ gn_critical_only 同步失敗")

    # 1f. RSS priority min_articles
    rss_min = int(configs.get("radar_rss_min_articles", "0"))
    result = api(vm, "PUT", "/api/settings/rss-priority", {"min_articles": rss_min})
    if result is not None:
        print(f"  ✓ rss_priority：min_articles={rss_min}")
    else:
        print("  ✗ rss_priority 同步失敗")


def sync_sources(vm: str, local_sources: list):
    print("\n── 2. 同步資料來源 (monitor_sources) ───────────────────────────────────")

    # 取 VM 現有來源
    vm_sources = api(vm, "GET", "/api/settings/sources")
    if vm_sources is None:
        print("  ✗ 無法取得 VM 資料來源列表，跳過")
        return

    # 建立 VM 來源索引：{url: {id, name, type, is_active, fetch_all, ...}}
    vm_by_url = {}
    for s in vm_sources:
        if s.get("url"):
            vm_by_url[s["url"]] = s

    # 特殊 URL 別名對應（本地 URL → VM 可能有的舊 URL）
    url_aliases = {
        # 本地用 trumpstruth.org，VM 可能還是 truthsocial
        "https://www.trumpstruth.org/feed": [
            "https://truthsocial.com/@realDonaldTrump.rss",
        ],
        # 本地用 /news/feed/，VM 可能有 /feed/
        "https://www.whitehouse.gov/news/feed/": [
            "https://www.whitehouse.gov/feed/",
        ],
        # 鉅亨網 - 總經：VM 可能有 macro 舊 URL
        "https://api.cnyes.com/media/api/v1/newslist/category/headline": [
            "https://api.cnyes.com/media/api/v1/newslist/category/macro",
        ],
        # World Bank：VM 可能有舊 RSS URL
        "https://search.worldbank.org/api/v2/news?format=json&rows=30&os=0": [
            "https://www.worldbank.org/en/rss/home",
        ],
        # FSC：VM 可能有舊 RSS URL
        "https://www.fsc.gov.tw/ch/home.jsp?id=96&parentpath=0,2&mcustomize=news_list.jsp": [
            "https://www.fsc.gov.tw/rss/rss_news.xml",
            "https://www.fsc.gov.tw/fckdowndoc?file=/rss/news_rss.xml",
        ],
        # Caixin：VM 可能有舊 RSS URL
        "https://www.caixinglobal.com/news/": [
            "https://www.caixinglobal.com/rss",
        ],
    }

    created = updated = skipped = 0

    for local in local_sources:
        url = local["url"]
        if not url:
            continue

        # 找 VM 對應來源（先精確 URL，再找別名）
        vm_entry = vm_by_url.get(url)
        if vm_entry is None:
            for alias in url_aliases.get(url, []):
                vm_entry = vm_by_url.get(alias)
                if vm_entry:
                    break

        if vm_entry:
            # 比對 is_active、fetch_all、name、type、url 是否有差異
            vm_id = vm_entry["id"]
            needs_update = (
                vm_entry.get("is_active") != local["is_active"]
                or vm_entry.get("fetch_all", False) != local["fetch_all"]
                or vm_entry.get("name") != local["name"]
                or vm_entry.get("type") != local["type"]
                or vm_entry.get("url") != local["url"]  # URL 可能需要更新
            )
            if needs_update:
                result = api(vm, "PUT", f"/api/settings/sources/{vm_id}", {
                    "name": local["name"],
                    "type": local["type"],   # 同步 type（rss/website/social/mops）
                    "url": local["url"],     # 更新為本地正確 URL
                    "keywords": local["keywords"],
                    "is_active": local["is_active"],
                    "fetch_all": local["fetch_all"],
                })
                if result:
                    changes = []
                    if vm_entry.get("is_active") != local["is_active"]:
                        changes.append(f"active={local['is_active']}")
                    if vm_entry.get("fetch_all", False) != local["fetch_all"]:
                        changes.append(f"fetch_all={local['fetch_all']}")
                    if vm_entry.get("name") != local["name"]:
                        changes.append(f"name={local['name']!r}")
                    if vm_entry.get("type") != local["type"]:
                        changes.append(f"type={vm_entry.get('type')}→{local['type']}")
                    if vm_entry.get("url") != local["url"]:
                        changes.append(f"url updated")
                    print(f"  ✓ 更新 [{local['name']}] {', '.join(changes)}")
                    updated += 1
                else:
                    print(f"  ✗ 更新失敗：{local['name']}")
            else:
                skipped += 1
        else:
            # VM 沒有此來源 → 新增
            # 只新增本地啟用的來源（停用的不需要新增到 VM）
            if local["is_active"]:
                result = api(vm, "POST", "/api/settings/sources", {
                    "name": local["name"],
                    "type": local["type"],
                    "url": local["url"],
                    "keywords": local["keywords"],
                    "fetch_all": local["fetch_all"],
                })
                if result:
                    print(f"  ✓ 新增 [{local['name']}] type={local['type']}")
                    created += 1
                else:
                    print(f"  ✗ 新增失敗：{local['name']}")

    print(f"\n  來源同步完成：更新 {updated} 個，新增 {created} 個，無需變更 {skipped} 個")


def sync_topics(vm: str, local_topics: list):
    print("\n── 3. 同步主題追蹤 (topics) ──────────────────────────────────────────────")

    vm_topics = api(vm, "GET", "/api/topics/")
    if vm_topics is None:
        print("  ✗ 無法取得 VM 主題列表，跳過")
        return

    # 建立 VM 主題索引：{name: {id, keywords, is_active}}
    vm_by_name = {t["name"]: t for t in vm_topics}

    created = updated = skipped = 0

    for local in local_topics:
        vm_entry = vm_by_name.get(local["name"])
        if vm_entry:
            needs_update = (
                vm_entry.get("is_active") != local["is_active"]
                or vm_entry.get("keywords") != local["keywords"]
            )
            if needs_update:
                result = api(vm, "PUT", f"/api/topics/{vm_entry['id']}", {
                    "name": local["name"],
                    "keywords": local["keywords"],
                    "is_active": local["is_active"],
                })
                if result:
                    print(f"  ✓ 更新主題 [{local['name']}]")
                    updated += 1
                else:
                    print(f"  ✗ 更新主題失敗：{local['name']}")
            else:
                skipped += 1
        else:
            # 新增主題
            result = api(vm, "POST", "/api/topics/", {
                "name": local["name"],
                "keywords": local["keywords"],
            })
            if result:
                print(f"  ✓ 新增主題 [{local['name']}]")
                created += 1
            else:
                print(f"  ✗ 新增主題失敗：{local['name']}")

    print(f"\n  主題同步完成：更新 {updated} 個，新增 {created} 個，無需變更 {skipped} 個")


def main():
    vm = get_vm_url()
    print(f"目標 VM：{vm}")

    # 健康檢查
    print("\n>> 健康檢查...")
    health = api(vm, "GET", "/api/health")
    if health is None:
        print("VM API 無法連線，請確認 VM 已啟動且 IP/port 正確。")
        sys.exit(1)
    print(f"   VM 狀態：{health}")

    # 讀取本地 DB
    print(f"\n>> 讀取本地 DB：{LOCAL_DB}")
    if not LOCAL_DB.exists():
        print(f"找不到本地資料庫：{LOCAL_DB}")
        sys.exit(1)
    configs, local_sources, local_topics = load_local_db()
    print(f"   system_config：{len(configs)} 個設定")
    print(f"   monitor_sources：{len(local_sources)} 個（非 research）")
    print(f"   topics：{len(local_topics)} 個")

    # 同步
    sync_system_config(vm, configs)
    sync_sources(vm, local_sources)
    sync_topics(vm, local_topics)

    print("\n✅ 同步完成！")
    print("\n下一步：在 VM 上執行以下命令重啟服務（使 _migrate_db 修正所有 URL）：")
    print("  sudo systemctl restart financial-radar")


if __name__ == "__main__":
    main()
