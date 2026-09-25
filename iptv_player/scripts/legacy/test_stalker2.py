"""Test all possible Stalker channel endpoints."""
import requests
import hashlib
import time
import json
from diagnostic_config import PORTAL, MAC

def try_all():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 MAG425",
        "Accept": "*/*",
        "X-User-Agent": "Model: MAG425; Link: WiFi",
    })
    mac_clean = MAC.lower().replace(":", "")
    session.cookies.set("mac", mac_clean)

    # Handshake
    nonce = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()[:8]
    r = session.post(f"{PORTAL}/server/load.php", data={
        "type": "stb", "action": "handshake",
        "JsHttpRequest": f"1-xml:{nonce}"
    }, timeout=15)
    token = json.loads(r.text).get("js", {}).get("token", "")
    print(f"Token OK: {token[:20]}...")

    # Try EVERY possible action and parameter combo
    actions = [
        {"action": "get_all_channels"},
        {"action": "get_all_channels", "p": "1"},
        {"action": "get_all_channels", "force": "1"},
        {"action": "get_all_channels", "fav": "0"},
        {"action": "get_all_channels", "type": "all"},
        {"action": "itv"},
        {"action": "itv", "p": "1"},
        {"action": "itv", "all": "1"},
        {"action": "get_itv_list"},
        {"action": "get_itv_list", "p": "1"},
        {"action": "get_all_itv"},
        {"action": "get_ordered_list"},
        {"action": "get_ordered_list", "p": "1"},
        {"action": "get_channels"},
        {"action": "get_channels", "genre": ""},
    ]

    found = False
    for params in actions:
        nonce = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()[:8]
        data = {
            "type": "stb",
            "token": token,
            "mac": MAC,
            "JsHttpRequest": f"1-xml:{nonce}",
        }
        data.update(params)

        r = session.post(f"{PORTAL}/server/load.php", data=data, timeout=15)
        text = r.text.strip()
        
        # Check if response has meaningful content (not empty and not the handshake page)
        has_content = len(text) > 20 and "loadRequiredFiles" not in text
        print(f"  {params['action']}: {len(text)} bytes", end="")
        if has_content:
            print(f" - HAS DATA! {text[:200]}")
            found = True
        else:
            print()

    if not found:
        print("\nNo channel data found via STB API.")

    # -- Now try completely different approach --
    print("\n--- Trying to access the portal directly ---")
    
    # Access /c/ and look for embedded data
    r = session.get(f"{PORTAL}/c/", timeout=15)
    html = r.text
    
    # Look for any JSON-like data in the page
    json_patterns = ['"channels"', '"data"', '"itv"', '"tv"', 'channels:', 'data:']
    for pattern in json_patterns:
        if pattern in html:
            idx = html.index(pattern)
            print(f"Found '{pattern}' at position {idx}: ...{html[max(0,idx-30):idx+100]}...")


if __name__ == "__main__":
    try_all()
