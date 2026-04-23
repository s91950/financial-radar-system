#!/usr/bin/env python3
"""
從 VM 拉取最新設定同步到本地 SQLite 資料庫（反向同步）。
VM 上的設定為最新版本，本地端以 VM 為準。

使用方法：
  python scripts/pull_from_vm.py http://34.23.154.194
  python scripts/pull_from_vm.py  # 使用 .env.local 中的 API_BASE_URL

同步項目：
  1. monitor_sources — 來源清單（關鍵字、fetch_all、fixed_severity、is_active、名稱）
  2. system_config   — radar_topics、severity keywords/rules、hours_back 等
  3. topics         — 主題追蹤關鍵字
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

LOCAL_DB = Path(__file__).parent.parent / "data" / "financial_radar.db"
ENV_LOCAL = Path(__file__).parent / ".env.local"


def get_vm_url() -> str:
    if len(sys.argv) >= 2:
        url = sys.argv[1].rstrip("/")
        return "http://" + url if not url.startswith("http") else url
    # 從 .env.local 讀取
    if ENV_LOCAL.exists():
        for line in ENV_LOCAL.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("API_BASE_URL="):
                url = line.split("=", 1)[1].strip().rstrip("/")
                print(f"使用 .env.local 的 VM 位址：{url}")
                return url
    print("用法：python scripts/pull_from_vm.py http://<VM_IP>")
    sys.exit(1)


def api_get(vm: str, path: str):
    try:
        r = requests.get(vm + path, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [錯誤] GET {path}：{e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
def sync_sources(vm: str, conn: sqlite3.Connection):
    print("\n── 1. 同步來源 (monitor_sources) ────────────────────────────────────────")
    vm_sources = api_get(vm, "/api/settings/sources")
    if not vm_sources:
        print("  ✗ 無法取得 VM 來源列表，跳過")
        return

    # 非研究類
    vm_sources = [s for s in vm_sources if s.get("type") != "research"]

    # 本地來源 index by URL
    local_rows = conn.execute(
        "SELECT id, url, name, type, keywords, is_active, fetch_all, fixed_severity "
        "FROM monitor_sources WHERE type != 'research'"
    ).fetchall()
    local_by_url = {row[1]: row for row in local_rows}

    updated = inserted = skipped = 0

    for vs in vm_sources:
        url = vs.get("url", "")
        if not url:
            continue
        kw_json = json.dumps(vs.get("keywords") or [], ensure_ascii=False)
        fa = 1 if vs.get("fetch_all") else 0
        active = 1 if vs.get("is_active") else 0
        fixed_sev = vs.get("fixed_severity") or None
        name = vs.get("name", "")
        typ = vs.get("type", "rss")

        local = local_by_url.get(url)
        if local:
            local_id, _, local_name, local_type, local_kw, local_active, local_fa, local_sev = local
            # 比對差異（以 VM 為準）
            changed = (
                local_name != name
                or local_type != typ
                or local_kw != kw_json
                or bool(local_active) != bool(active)
                or bool(local_fa) != bool(fa)
                or local_sev != fixed_sev
            )
            if changed:
                conn.execute(
                    "UPDATE monitor_sources SET name=?, type=?, keywords=?, is_active=?, "
                    "fetch_all=?, fixed_severity=? WHERE id=?",
                    (name, typ, kw_json, active, fa, fixed_sev, local_id)
                )
                changes = []
                if local_name != name: changes.append(f"name={name!r}")
                if local_type != typ: changes.append(f"type={typ}")
                if local_kw != kw_json: changes.append("keywords updated")
                if bool(local_active) != bool(active): changes.append(f"active={bool(active)}")
                if bool(local_fa) != bool(fa): changes.append(f"fetch_all={bool(fa)}")
                if local_sev != fixed_sev: changes.append(f"fixed_severity={fixed_sev}")
                print(f"  ✓ 更新 [{name}] {', '.join(changes)}")
                updated += 1
            else:
                skipped += 1
        else:
            # 本地沒有，新增
            conn.execute(
                "INSERT INTO monitor_sources (name, type, url, keywords, is_active, fetch_all, fixed_severity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, typ, url, kw_json, active, fa, fixed_sev)
            )
            print(f"  ✓ 新增 [{name}] type={typ} url={url[:60]}")
            inserted += 1

    conn.commit()
    print(f"\n  來源同步完成：更新 {updated} 個，新增 {inserted} 個，無需變更 {skipped} 個")


# ─────────────────────────────────────────────────────────────────────────────
def _upsert_config(conn: sqlite3.Connection, key: str, value: str):
    existing = conn.execute(
        "SELECT key FROM system_config WHERE key=?", (key,)
    ).fetchone()
    if existing:
        conn.execute("UPDATE system_config SET value=? WHERE key=?", (value, key))
    else:
        conn.execute("INSERT INTO system_config (key, value) VALUES (?, ?)", (key, value))


def sync_system_config(vm: str, conn: sqlite3.Connection):
    print("\n── 2. 同步系統設定 (system_config) ──────────────────────────────────────")

    # 2a. radar topics
    data = api_get(vm, "/api/settings/radar-topics")
    if data:
        _upsert_config(conn, "radar_topics", json.dumps(data.get("topics", []), ensure_ascii=False))
        _upsert_config(conn, "radar_topics_us", json.dumps(data.get("topics_us", []), ensure_ascii=False))
        _upsert_config(conn, "radar_hours_back", str(data.get("hours_back", 24)))
        _upsert_config(conn, "radar_interval_minutes", str(data.get("interval_minutes", 5)))
        _upsert_config(conn, "radar_rss_only", "true" if data.get("rss_only") else "false")
        excl = data.get("exclusion_keywords", [])
        _upsert_config(conn, "radar_exclusion_keywords", json.dumps(excl, ensure_ascii=False))
        print(f"  ✓ radar_topics：TW {len(data.get('topics',[]))} 個，US {len(data.get('topics_us',[]))} 個")
        print(f"  ✓ hours_back={data.get('hours_back')}, rss_only={data.get('rss_only')}")
        print(f"  ✓ exclusion_keywords：{len(excl)} 個")

    # 2b. severity keywords
    kw_data = api_get(vm, "/api/settings/severity-keywords")
    if kw_data:
        crit = kw_data.get("critical", [])
        high = kw_data.get("high", [])
        _upsert_config(conn, "severity_critical_keywords", json.dumps(crit, ensure_ascii=False))
        _upsert_config(conn, "severity_high_keywords", json.dumps(high, ensure_ascii=False))
        print(f"  ✓ severity_keywords：critical={len(crit)}，high={len(high)}")

    # 2c. severity rules
    rules_data = api_get(vm, "/api/settings/severity-rules")
    if rules_data is not None:
        rules = rules_data.get("rules", [])
        _upsert_config(conn, "severity_rules", json.dumps(rules, ensure_ascii=False))
        print(f"  ✓ severity_rules：{len(rules)} 條")

    # 2d. finance filter
    ff = api_get(vm, "/api/settings/finance-filter")
    if ff:
        _upsert_config(conn, "finance_filter_enabled", "true" if ff.get("enabled") else "false")
        _upsert_config(conn, "finance_relevance_threshold", str(ff.get("threshold", 0.15)))
        print(f"  ✓ finance_filter：enabled={ff.get('enabled')}，threshold={ff.get('threshold')}")

    # 2e. GN critical only
    gn = api_get(vm, "/api/settings/gn-critical-only")
    if gn is not None:
        _upsert_config(conn, "gn_critical_only", "true" if gn.get("enabled") else "false")
        print(f"  ✓ gn_critical_only：{gn.get('enabled')}")

    # 2f. RSS priority
    rp = api_get(vm, "/api/settings/rss-priority")
    if rp is not None:
        _upsert_config(conn, "radar_rss_min_articles", str(rp.get("min_articles", 0)))
        print(f"  ✓ rss_min_articles：{rp.get('min_articles')}")

    conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
def sync_topics(vm: str, conn: sqlite3.Connection):
    print("\n── 3. 同步主題追蹤 (topics) ──────────────────────────────────────────────")
    vm_topics = api_get(vm, "/api/topics/")
    if vm_topics is None:
        print("  ✗ 無法取得 VM 主題列表，跳過")
        return

    local_topics = conn.execute(
        "SELECT id, name, keywords, is_active FROM topics"
    ).fetchall()
    local_by_name = {row[1]: row for row in local_topics}

    updated = inserted = skipped = 0
    for vt in vm_topics:
        name = vt.get("name", "")
        kw_json = json.dumps(vt.get("keywords", []), ensure_ascii=False)
        active = 1 if vt.get("is_active") else 0

        local = local_by_name.get(name)
        if local:
            local_id, _, local_kw, local_active = local
            if local_kw != kw_json or bool(local_active) != bool(active):
                conn.execute(
                    "UPDATE topics SET keywords=?, is_active=? WHERE id=?",
                    (kw_json, active, local_id)
                )
                print(f"  ✓ 更新主題 [{name}]")
                updated += 1
            else:
                skipped += 1
        else:
            conn.execute(
                "INSERT INTO topics (name, keywords, is_active) VALUES (?, ?, ?)",
                (name, kw_json, active)
            )
            print(f"  ✓ 新增主題 [{name}]")
            inserted += 1

    conn.commit()
    print(f"\n  主題同步完成：更新 {updated} 個，新增 {inserted} 個，無需變更 {skipped} 個")


# ─────────────────────────────────────────────────────────────────────────────
def main():
    vm = get_vm_url()
    print(f"來源 VM：{vm}")

    # 健康檢查
    health = api_get(vm, "/api/health")
    if health is None:
        print("VM API 無法連線，請確認 VM 已啟動且 IP 正確。")
        sys.exit(1)
    print(f"VM 狀態：{health}")

    if not LOCAL_DB.exists():
        print(f"找不到本地資料庫：{LOCAL_DB}")
        sys.exit(1)

    conn = sqlite3.connect(str(LOCAL_DB))
    try:
        sync_sources(vm, conn)
        sync_system_config(vm, conn)
        sync_topics(vm, conn)
    finally:
        conn.close()

    print("\n✅ 完成！本地端已與 VM 同步。")
    print("重啟本地後端以套用設定：pkill -f uvicorn && uvicorn backend.main:app ...")


if __name__ == "__main__":
    main()
