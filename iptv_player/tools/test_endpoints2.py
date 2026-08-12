"""Investigate found endpoints."""
import requests
from diagnostic_config import PORTAL, MAC, MAC_CLEAN

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
s.headers.update({"Referer": f"{PORTAL}/c/"})

# Visit /c/ first
s.get(f"{PORTAL}/c/", timeout=15)

# Try playlist.php with various params
params_list = [
    {},
    {"mac": MAC_CLEAN},
    {"mac": MAC},
    {"username": MAC_CLEAN, "password": MAC_CLEAN},
    {"username": MAC_CLEAN, "password": MAC_CLEAN, "type": "m3u_plus"},
    {"type": "m3u"},
    {"type": "m3u_plus"},
    {"format": "json"},
    {"action": "list"},
]

for params in params_list:
    url = f"{PORTAL}/playlist.php"
    try:
        r = s.get(url, params=params, timeout=15)
        is_m3u = "#EXTM3U" in r.text
        marker = " M3U!" if is_m3u else ""
        print(f"[{r.status_code}] {params} -> {len(r.text)}b{marker}")
        if is_m3u:
            print(f"  Content: {r.text[:300]}")
        elif r.status_code == 200 and r.text:
            print(f"  Content: {r.text[:200]}")
    except Exception as e:
        print(f"[ERR] {params}: {e}")

# Also check if maybe the portal uses a different base URL
# Some portals hide the real API behind /stalker_portal/
print("\n--- Checking /stalker_portal/ paths ---")
for path in ["/stalker_portal/server/load.php", "/stalker_portal/get.php",
             "/stalker_portal/c/", "/stalker_portal/api.php"]:
    url = f"{PORTAL}{path}"
    params = {"username": MAC_CLEAN, "password": MAC_CLEAN, "type": "m3u_plus"}
    try:
        r = s.get(url, params=params, timeout=15)
        print(f"[{r.status_code}] {path}: {len(r.text)} bytes")
    except Exception as e:
        print(f"[ERR] {path}: {e}")
