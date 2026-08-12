"""Find alternative API endpoints on the portal."""
import requests
from diagnostic_config import PORTAL, MAC, MAC_CLEAN

def check_paths():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

    paths = [
        "/api/", "/api/v1/", "/api/v2/",
        "/json/", "/data/", "/channels/", "/streams/",
        "/c/index.php", "/c/auth.php", "/c/login.php",
        "/api.php", "/json.php", "/data.php", "/channels.php",
        "/live/", "/live.json",
        "/c/channels.json", "/c/data.json",
        "/c/api/", "/c/api.php",
        "/stalker_api/", "/stalker_api.php",
        "/api/live/", "/api/channels/",
        "/server/api/", "/server/api.php",
        "/list/", "/playlist/",
        "/playlist.php", "/list.php",
        "/c/live/",
        "/enigma.php",
        "/tv.php", "/c/tv.php",
        "/xml/", "/tv.xml",
    ]

    for path in paths:
        url = f"{PORTAL}{path}"
        try:
            r = s.get(url, timeout=10, allow_redirects=True)
            if r.status_code not in (404, 520, 521, 502, 503) or len(r.text) > 1000:
                print(f"[{r.status_code}] {path}: {len(r.text)} bytes")
                if r.status_code == 200 and len(r.text) < 500:
                    print(f"  Content: {r.text[:200]}")
        except Exception as e:
            pass

    print("\nDone scanning paths.")


if __name__ == "__main__":
    check_paths()
