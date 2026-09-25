"""Test ext_module.php with various auth approaches."""
import requests
import hashlib
import time
import json
from diagnostic_config import PORTAL, MAC, MAC_CLEAN

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 MAG425",
    "Accept": "*/*",
})
s.cookies.set("mac", MAC_CLEAN)

# Handshake
nonce = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()[:8]
r = s.post(f"{PORTAL}/server/load.php", data={
    "type": "stb", "action": "handshake",
    "JsHttpRequest": f"1-xml:{nonce}"
}, timeout=15)
token = json.loads(r.text).get("js", {}).get("token", "")
print(f"Token OK: {token[:20]}...")

# Try ext_module with various approaches
approaches = [
    (f"{PORTAL}/server/api/ext_module.php?name=tv&mac={MAC_CLEAN}", {}),
    (f"{PORTAL}/server/api/ext_module.php?name=tv&mac={MAC_CLEAN}&token={token}", {}),
    (f"{PORTAL}/server/api/ext_module.php?name=tv", {}),
    (f"{PORTAL}/api/ext_module.php?name=tv&mac={MAC_CLEAN}", {}),
    (f"{PORTAL}/c/api/ext_module.php?name=tv&mac={MAC_CLEAN}", {}),
    (f"{PORTAL}/ext_module.php?name=tv&mac={MAC_CLEAN}", {}),
]

for url, extra_headers in approaches:
    try:
        r = s.get(url, timeout=15, headers=extra_headers)
        print(f"[{r.status_code}] {url.split(PORTAL)[1]}: {len(r.text)} bytes")
        if r.status_code == 200 and r.text:
            print(f"  Content: {r.text[:200]}")
    except Exception as e:
        print(f"[ERR] {url.split(PORTAL)[1]}: {e}")

# Also check if /c/ is a directory by checking /c/../server/load.php
r = s.get(f"{PORTAL}/c/../server/load.php", timeout=15)
print(f"\n/c/../server/load.php: {r.status_code} ({len(r.text)} bytes)")

# Check /c without trailing slash
r = s.get(f"{PORTAL}/c", timeout=15, allow_redirects=False)
print(f"/c: {r.status_code} location={r.headers.get('location', 'none')}")

# Try server/api/ directory listing
r = s.get(f"{PORTAL}/server/api/", timeout=15)
print(f"/server/api/: {r.status_code} ({len(r.text)} bytes)")

# Try the module loading with STB-like parameters
for mod in ["tv", "itv", "radio", "vclub"]:
    r = s.get(f"{PORTAL}/server/api/ext_module.php", params={
        "name": mod, "mac": MAC_CLEAN
    }, timeout=15)
    print(f"/server/api/ext_module.php?name={mod}: {r.status_code} ({len(r.text)} bytes)")
