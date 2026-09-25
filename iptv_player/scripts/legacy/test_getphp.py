"""Try various approaches to access get.php."""
import requests
from diagnostic_config import PORTAL, MAC_CLEAN

def try_approach(description, method, url, data=None, headers=None):
    """Try accessing get.php with different approaches."""
    s = requests.Session()
    
    # Standard headers
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
    }
    if headers:
        default_headers.update(headers)
    s.headers.update(default_headers)

    # Visit /c/ first
    s.get(f"{PORTAL}/c/", timeout=15)

    try:
        if method == "GET":
            r = s.get(url, timeout=15)
        else:
            r = s.post(url, data=data, timeout=15)

        is_m3u = "#EXTM3U" in r.text
        status = r.status_code
        size = len(r.text)
        marker = " *** M3U! ***" if is_m3u else ""

        if is_m3u or status == 200:
            print(f"[{status}] {size}b{marker} {description}")
            if is_m3u:
                print(f"  {r.text[:400]}")
            return True
        else:
            print(f"[{status}] {size}b {description}")
            return False
    except Exception as e:
        print(f"[ERR] {description}: {e}")
        return False


# Test 1: Normal GET
url = f"{PORTAL}/get.php?username={MAC_CLEAN}&password={MAC_CLEAN}&type=m3u_plus"

# Test 2: POST instead of GET
try_approach("POST", "POST", url, data={"username": MAC_CLEAN, "password": MAC_CLEAN, "type": "m3u_plus"})

# Test 3: GET with different parameter names
try_approach("mac param", "GET", f"{PORTAL}/get.php?mac={MAC_CLEAN}&type=m3u_plus")
try_approach("device_id", "GET", f"{PORTAL}/get.php?device_id={MAC_CLEAN}&type=m3u_plus")
try_approach("token param", "GET", f"{PORTAL}/get.php?token={MAC_CLEAN}&type=m3u_plus")

# Test 4: With STB session
try_approach("STB session", "GET", url, headers={
    "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 MAG425",
    "X-User-Agent": "Model: MAG425; Link: WiFi",
})

# Test 5: With mobile user-agent
try_approach("Mobile", "GET", url, headers={
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36",
})

# Test 6: URL encoding
try_approach("URL encoded", "GET", 
    f"{PORTAL}/get.php?username=%30%30%31%61%37%39%61%39%31%32%31%62&password=%30%30%31%61%37%39%61%39%31%32%31%62&type=m3u_plus")

# Test 7: Without type parameter
try_approach("no type", "GET", f"{PORTAL}/get.php?username={MAC_CLEAN}&password={MAC_CLEAN}")

# Test 8: Output m3u8
try_approach("output m3u8", "GET", f"{PORTAL}/get.php?username={MAC_CLEAN}&password={MAC_CLEAN}&type=m3u_plus&output=m3u8")

# Test 9: Different paths
for path in ["/get.php", "/c/get.php", "/stalker_portal/get.php"]:
    try_approach(f"path={path}", "GET", 
        f"{PORTAL}{path}?username={MAC_CLEAN}&password={MAC_CLEAN}&type=m3u_plus",
        headers={"Referer": f"{PORTAL}/c/"})

# Test 10: With cookies from /c/
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
s.get(f"{PORTAL}/c/", timeout=15)
r = s.get(url, timeout=15)
print(f"\nFinal attempt with /c/ session: [{r.status_code}] {len(r.text)} bytes")
if "#EXTM3U" in r.text:
    print("*** M3U FOUND! ***")
    print(r.text[:400])
