"""Test both portals side by side."""
import requests
import hashlib
import time
import json
import os
from diagnostic_config import PORTAL, MAC

portals = [
    (PORTAL, MAC),
]
if os.environ.get("IPTV_TEST_PORTAL_2"):
    portals.append((
        os.environ["IPTV_TEST_PORTAL_2"].rstrip("/"),
        os.environ.get("IPTV_TEST_MAC_2", MAC),
    ))

for portal_url, mac in portals:
    mac_clean = mac.lower().replace(":", "")
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 MAG425",
    })
    s.cookies.set("mac", mac_clean)
    s.get(f"{portal_url}/c/", timeout=15)

    # Handshake
    nonce = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()[:8]
    r = s.post(f"{portal_url}/server/load.php", data={
        "type": "stb", "action": "handshake",
        "JsHttpRequest": f"1-xml:{nonce}"
    }, timeout=15)
    token = json.loads(r.text).get("js", {}).get("token", "")
    hostname = portal_url.split("/")[2]
    print(f"{hostname}: token OK")

    # STB API - get_all_channels
    nonce = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()[:8]
    r = s.post(f"{portal_url}/server/load.php", data={
        "type": "stb", "action": "get_all_channels", "token": token,
        "mac": mac, "JsHttpRequest": f"1-xml:{nonce}", "p": "1"
    }, timeout=15)
    print(f"  STB get_all_channels: {len(r.text)} bytes")
    if r.text:
        print(f"  Response: {r.text[:200]}")
    else:
        print(f"  -> EMPTY")

    # get.php M3U
    r = s.get(
        f"{portal_url}/get.php?username={mac_clean}&password={mac_clean}&type=m3u_plus",
        timeout=15,
    )
    is_m3u = "#EXTM3U" in r.text
    print(f"  get.php M3U: [{r.status_code}] {len(r.text)} bytes")
    if is_m3u:
        print(f"  *** M3U FOUND via get.php! ***")
        print(f"  First 300 chars: {r.text[:300]}")
    print()
