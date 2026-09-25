"""Analyze portal web interface like Stalker Portal Player would."""
import requests
import hashlib
import time
import json
from diagnostic_config import PORTAL, MAC, MAC_CLEAN

def check_web_paths():
    """Check web interface paths with Android User-Agent."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/90.0.4430.210 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })

    # Visit /c/ first
    s.get(f"{PORTAL}/c/", timeout=15)
    s.cookies.set("mac", MAC_CLEAN)

    # Check various paths
    for path in ["/c/", "/c/tv.php", "/c/index.php", "/c/auth.php",
                  "/c/channels.htm", "/c/live.htm", "/c/list.htm",
                  "/c/player_api.php", "/c/xmltv.php"]:
        try:
            r = s.get(f"{PORTAL}{path}", timeout=10)
            print(f"[{r.status_code}] {path}: {len(r.text)} bytes")
        except Exception as e:
            print(f"[ERR] {path}: {e}")

    print()


def check_stb_api_with_android_ua():
    """Try STB API with Android UA instead of STB UA."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36",
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
    print(f"Android UA handshake: token={'OK' if token else 'FAIL'}")

    # Try get_all_channels
    nonce = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()[:8]
    r = s.post(f"{PORTAL}/server/load.php", data={
        "type": "stb", "action": "get_all_channels", "token": token,
        "mac": MAC, "JsHttpRequest": f"1-xml:{nonce}", "p": "1"
    }, timeout=15)
    print(f"Channels with Android UA: {len(r.text)} bytes: '{r.text[:100]}'")

    print()


def check_portal_javascript():
    """Download and analyze portal JS modules."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 MAG425",
        "Accept": "*/*",
    })
    s.cookies.set("mac", MAC_CLEAN)

    # Get the /c/ page and find module references
    r = s.get(f"{PORTAL}/c/", timeout=15)
    html = r.text

    # Extract module names from the page
    import re
    modules = re.findall(r"['\"](\w+)['\"]", html)
    interesting = [m for m in set(modules) if m not in (
        "callback", "scripts", "filesloaded", "filestoload", "i", "script",
        "length", "src", "onerror", "onload", "finishLoad", "onLoadScript",
        "add_pos", "append", "next", "add", "chain", "cur_idx", "head",
        "max_load_percent", "step", "template", "paused", "loaded", "len",
        "type", "href", "id", "name", "data", "title", "class",
        "js", "json", "xml", "text", "html", "css", "image",
        "true", "false", "null", "undefined",
    )]
    print(f"Module names found: {interesting[:20]}")

    # Check if there's a JavaScript file that loads modules
    js_files = ["version.js", "global.js", "player.js", "JsHttpRequest.js",
                 "xpcom.common.js", "xpcom.webkit.js", "keydown.observer.js",
                 "keydown.keycodes.js", "load_bar.js", "watchdog.js",
                 "blocking.js", "usbdisk.js"]

    # Also look for modules in /c/template/ directory
    for js in js_files:
        r = s.get(f"{PORTAL}/{js}", timeout=10)
        if len(r.text) > 10:
            print(f"\n{js}: {len(r.text)} bytes")
            for kw in ["channels", "itv", "tv", "get_all", "action"]:
                if kw in r.text.lower():
                    idx = r.text.lower().index(kw)
                    print(f"  '{kw}' found: ...{r.text[max(0,idx-40):idx+80]}...")


if __name__ == "__main__":
    check_web_paths()
    check_stb_api_with_android_ua()
    check_portal_javascript()
