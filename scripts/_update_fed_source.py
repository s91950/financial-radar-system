"""
1. Update VM ID=1 (聯準會 press_all RSS) to website type + recentpostings.htm
2. Group all Fed-related sources together via sort_order
"""
import urllib.request, urllib.error, json, ssl

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
BASE = "http://34.23.154.194"

def get_sources():
    with urllib.request.urlopen(f"{BASE}/api/settings/sources", timeout=10) as r:
        return json.loads(r.read())

def put_source(sid, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE}/api/settings/sources/{sid}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="PUT"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def reorder_sources(id_list):
    data = json.dumps(id_list).encode()
    req = urllib.request.Request(
        f"{BASE}/api/settings/sources/reorder",
        data=data,
        headers={"Content-Type": "application/json"},
        method="PUT"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

sources = get_sources()
print(f"Total sources: {len(sources)}")

# --- Step 1: Update ID=1 to website type + recentpostings.htm ---
s1 = next((s for s in sources if s["id"] == 1), None)
if s1:
    print(f"\nBefore: ID=1  type={s1['type']}  url={s1.get('url','')[:70]}")
    result = put_source(1, {
        "name": s1["name"],
        "url": "https://www.federalreserve.gov/recentpostings.htm",
        "type": "website",
        "is_active": s1["is_active"],
        "keywords": s1.get("keywords") or [],
        "fetch_all": s1.get("fetch_all", False),
        "fixed_severity": s1.get("fixed_severity"),
    })
    print(f"After:  ID=1  type={result['type']}  url={result.get('url','')[:70]}")
else:
    print("ID=1 not found!")

# --- Step 2: Identify all Fed-related sources ---
# Refresh after update
sources = get_sources()

fed_ids = []
for s in sources:
    name_lower = s.get("name", "").lower()
    url_lower = (s.get("url") or "").lower()
    if (
        "fed" in name_lower
        or "federalreserve" in url_lower
        or "recentpostings" in url_lower
        or "press_monetary" in url_lower
        or s["id"] == 93  # Fed Monetary Policy RSS
    ):
        fed_ids.append(s["id"])
        print(f"  Fed source: ID={s['id']:3d} sort={s['sort_order']:3d}  {s['name']:<35} {url_lower[:55]}")

print(f"\nFed source IDs: {fed_ids}")

# --- Step 3: Build new sort_order — put all Fed sources at the top ---
# Current order by sort_order
ordered = sorted(sources, key=lambda x: x["sort_order"])
non_fed_ids = [s["id"] for s in ordered if s["id"] not in fed_ids]

# Fed sources sorted by current sort_order (preserve relative order among themselves)
fed_sorted = sorted([s for s in sources if s["id"] in fed_ids], key=lambda x: x["sort_order"])
fed_order = [s["id"] for s in fed_sorted]

new_order = fed_order + non_fed_ids
print(f"\nNew order (first 20): {new_order[:20]}")
print(f"Total: {len(new_order)}")

result = reorder_sources(new_order)
print(f"\nReorder result: {result}")

# Verify
sources2 = get_sources()
fed_sources2 = sorted(
    [s for s in sources2 if s["id"] in fed_ids],
    key=lambda x: x["sort_order"]
)
print("\n=== Fed sources after reorder ===")
for s in fed_sources2:
    print(f"  sort={s['sort_order']:3d}  ID={s['id']:3d}  {s['name']:<35} type={s['type']}")
