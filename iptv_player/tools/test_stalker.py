"""Test script for Stalker Portal debugging."""
import requests
import hashlib
import time
import json
from diagnostic_config import PORTAL, MAC

def test_endpoints():
    """Test various Stalker endpoints and approaches."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 MAG425",
        "Accept": "*/*",
        "X-User-Agent": "Model: MAG425; Link: WiFi",
    })

    mac_clean = MAC.lower().replace(":", "")
    session.cookies.set("mac", mac_clean)

    # 1. Handshake
    nonce = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()[:8]
    r = session.post(f"{PORTAL}/server/load.php", data={
        "type": "stb", "action": "handshake",
        "JsHttpRequest": f"1-xml:{nonce}"
    }, timeout=15)
    result = json.loads(r.text)
    token = result.get("js", {}).get("token", "")
    print(f"Handshake OK, token={token[:20]}...")

    # 2. Try standard STB actions that might return channels
    actions = [
        "get_all_channels", "itv", "get_itv_list", "get_ordered_list",
        "get_genres", "get_categories", "get_itv_categories",
        "get_all_itv", "get_data", "get_storage_data",
    ]

    for action in actions:
        nonce = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()[:8]
        r = session.post(f"{PORTAL}/server/load.php", data={
            "type": "stb", "action": action, "token": token, "mac": MAC,
            "JsHttpRequest": f"1-xml:{nonce}", "p": "1",
        }, timeout=15)
        text = r.text.strip()
        print(f"  {action}: {len(text)} bytes - {text[:150] if text else 'EMPTY'}")

    # 3. Try fetching JS API files
    for js in ["version.js", "global.js", "player.js"]:
        r = session.get(f"{PORTAL}/{js}", timeout=10)
        print(f"  {js}: {len(r.text)} bytes")

    # 4. Try M3U endpoints with Windows User-Agent
    win_session = requests.Session()
    win_session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    })
    
    test_urls = [
        f"{PORTAL}/get.php?username={mac_clean}&password={mac_clean}&type=m3u_plus",
        f"{PORTAL}/get.php?username={MAC}&password={MAC}&type=m3u_plus",
        f"{PORTAL}/c/?format=m3u",
        f"{PORTAL}/c/index.html?type=m3u",
    ]
    
    for url in test_urls:
        try:
            r = win_session.get(url, timeout=10)
            is_m3u = "#EXTM3U" in r.text
            marker = " *** M3U! ***" if is_m3u else ""
            print(f"  [{r.status_code}] {url}: {len(r.text)} bytes{marker}")
            if is_m3u:
                print(f"    Content: {r.text[:300]}")
        except Exception as e:
            print(f"  [ERR] {url}: {e}")


if __name__ == "__main__":
    test_endpoints()
