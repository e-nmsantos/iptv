"""Brute-force test all possible Stalker API actions."""
import requests
import hashlib
import time
import json
from diagnostic_config import PORTAL, MAC, MAC_CLEAN

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 MAG425",
    "Accept": "*/*",
    "X-User-Agent": "Model: MAG425; Link: WiFi",
})
session.cookies.set("mac", MAC_CLEAN)
session.get(f"{PORTAL}/c/", timeout=15)

# Handshake
nonce = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()[:8]
r = session.post(f"{PORTAL}/server/load.php", data={
    "type": "stb", "action": "handshake", "JsHttpRequest": f"1-xml:{nonce}"
}, timeout=15)
token = json.loads(r.text).get("js", {}).get("token", "")
print(f"Token: {token[:20]}...")

# Try ALL possible actions - both common and obscure
actions = [
    # Channel-related
    "get_all_channels", "itv", "get_itv_list", "get_all_itv",
    "get_ordered_list", "get_channels", "get_channel_list",
    "get_tv_channels", "get_itv_channels", "get_streams",
    "get_all_tv", "get_tv", "get_itv_category",
    "get_itv_categories", "get_categories", "get_genres",
    "get_genre_list", "get_category_list",
    
    # Different parameter styles
    "tv_list", "channel_list", "stream_list", "live_list",
    
    # Data/playlist
    "get_data", "get_storage_data", "get_media_data",
    "get_playlist", "get_all_data", "get_full_data",
    
    # Other known actions
    "get_profile", "get_settings", "get_config",
    "fav_itv", "get_fav_itv", "get_favorites",
    "get_epg", "get_epg_info", "get_epg_list",
    "get_modules", "get_services",
    "check_status", "get_status", "account_info",
]

for action in actions:
    nonce = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()[:8]
    r = session.post(f"{PORTAL}/server/load.php", data={
        "type": "stb", "action": action, "token": token, "mac": MAC,
        "JsHttpRequest": f"1-xml:{nonce}", "p": "1"
    }, timeout=15)
    text = r.text.strip()
    
    # Check if response has meaningful data
    has_data = len(text) > 20 and text != '""'
    if has_data:
        print(f"\n*** {action}: {len(text)} bytes ***")
        try:
            parsed = json.loads(text)
            js = parsed.get("js", parsed)
            if isinstance(js, dict):
                print(f"  Keys: {list(js.keys())}")
                for k, v in js.items():
                    if isinstance(v, list):
                        print(f"  {k}: list of {len(v)} items")
                        if v and isinstance(v[0], dict):
                            print(f"    First item keys: {list(v[0].keys())}")
                    elif isinstance(v, dict):
                        print(f"  {k}: dict with keys {list(v.keys())[:5]}")
                    else:
                        print(f"  {k}: {str(v)[:100]}")
            elif isinstance(js, list):
                print(f"  List of {len(js)} items")
                if js and isinstance(js[0], dict):
                    print(f"  First item: {json.dumps(js[0], indent=2)[:200]}")
        except:
            print(f"  Raw: {text[:200]}")
    else:
        print(f"  {action}: {len(text)} bytes - empty")
