"""Test bypassing Cloudflare on get.php."""
import requests
from diagnostic_config import PORTAL, MAC, MAC_CLEAN

def test_with_headers():
    """Test with full browser headers."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": f"{PORTAL}/c/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
    }

    session = requests.Session()
    session.headers.update(headers)

    # Visit portal first
    session.get(f"{PORTAL}/c/", timeout=15)

    # Try get.php
    url = f"{PORTAL}/get.php?username={MAC_CLEAN}&password={MAC_CLEAN}&type=m3u_plus"
    r = session.get(url, timeout=15)
    print(f"get.php: {r.status_code}, {len(r.text)} bytes")
    if r.status_code == 200:
        if "#EXTM3U" in r.text:
            print("*** M3U FOUND! ***")
            print(r.text[:500])
        else:
            print(f"Content: {r.text[:300]}")
    else:
        print(f"Not 200 - CF protected or error")


def test_with_get_params():
    """Test different get.php parameter formats."""
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"})

    formats = [
        f"{PORTAL}/get.php?username={MAC_CLEAN}&password={MAC_CLEAN}&type=m3u_plus",
        f"{PORTAL}/get.php?username={MAC}&password={MAC}&type=m3u_plus",
        f"{PORTAL}/get.php?username={MAC_CLEAN}&password={MAC_CLEAN}&type=m3u_plus&output=ts",
        f"{PORTAL}/get.php?username={MAC_CLEAN}&password={MAC_CLEAN}&type=m3u",
        f"{PORTAL}/get.php?mac={MAC_CLEAN}&type=m3u_plus",
        f"{PORTAL}/get.php?mac={MAC}&type=m3u_plus",
        f"{PORTAL}/c/get.php?username={MAC_CLEAN}&password={MAC_CLEAN}&type=m3u_plus",
    ]

    for url in formats:
        try:
            r = session.get(url, timeout=15)
            is_m3u = "#EXTM3U" in r.text
            marker = " <-- M3U!" if is_m3u else ""
            print(f"[{r.status_code}] {len(r.text)}b{marker} {url.split('?')[1][:60]}")
            if is_m3u:
                print(f"  Content: {r.text[:300]}")
        except Exception as e:
            print(f"[ERR] {url.split('?')[1][:60]}: {e}")


if __name__ == "__main__":
    test_with_headers()
    print()
    test_with_get_params()
