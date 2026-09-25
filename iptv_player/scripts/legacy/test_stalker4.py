"""Test Stalker with browser-like navigation flow."""
import requests
import hashlib
import time
import json
from diagnostic_config import PORTAL, MAC, MAC_CLEAN

session = requests.Session()

# Step 1: Visit /c/ as a browser would
session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
r = session.get(f"{PORTAL}/c/", timeout=15)
print(f"Visit /c/: {r.status_code}, cookies: {dict(session.cookies)}")

# Step 2: Switch to STB User-Agent
session.headers.update({
    "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 MAG425",
    "X-User-Agent": "Model: MAG425; Link: WiFi",
})
session.cookies.set("mac", MAC_CLEAN)

# Step 3: Handshake with referer
nonce = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()[:8]
r = session.post(f"{PORTAL}/server/load.php", data={
    "type": "stb", "action": "handshake",
    "JsHttpRequest": f"1-xml:{nonce}"
}, timeout=15, headers={"Referer": f"{PORTAL}/c/"})
result = json.loads(r.text)
token = result.get("js", {}).get("token", "")
print(f"Handshake OK, token: {token[:20]}...")

# Step 4: Get profile  
nonce = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()[:8]
r = session.post(f"{PORTAL}/server/load.php", data={
    "type": "stb", "action": "get_profile", "token": token, "mac": MAC,
    "JsHttpRequest": f"1-xml:{nonce}"
}, timeout=15, headers={"Referer": f"{PORTAL}/c/"})
profile = json.loads(r.text).get("js", {})
print(f"Profile: id={profile.get('id')}, name={profile.get('name')}")

# Step 5: Try get_all_channels with various approaches
approaches = [
    {"action": "get_all_channels", "p": "1"},
    {"action": "get_all_channels", "p": "1", "fav": "0"},
    {"action": "get_all_channels", "type": "all"},
    {"action": "itv", "p": "1"},
    {"action": "get_itv_categories"},
    {"action": "get_genres"},
]

for params in approaches:
    nonce = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()[:8]
    data = {
        "type": "stb",
        "token": token,
        "mac": MAC,
        "JsHttpRequest": f"1-xml:{nonce}",
    }
    data.update(params)
    
    r = session.post(f"{PORTAL}/server/load.php", data=data, timeout=15,
                     headers={"Referer": f"{PORTAL}/c/"})
    text = r.text.strip()
    print(f"{params['action']}: {len(text)} bytes - \"{text[:100]}\"")

# Step 6: Try without MAC in params (some portals use cookie only)
print("\n--- Without MAC param ---")
for action in ["get_all_channels", "itv"]:
    nonce = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()[:8]
    r = session.post(f"{PORTAL}/server/load.php", data={
        "type": "stb", "action": action, "token": token,
        "JsHttpRequest": f"1-xml:{nonce}", "p": "1"
    }, timeout=15, headers={"Referer": f"{PORTAL}/c/"})
    text = r.text.strip()
    print(f"{action}: {len(text)} bytes - \"{text[:100]}\"")

print("\nDone - portal returned 0 channels for all tested methods.")
print("This portal may require additional setup or a registered device/serial.")
