"""Deep analysis of Stalker portal HTML."""
import requests
import re
from diagnostic_config import PORTAL, MAC

def analyze():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    
    # Get the portal page
    r = session.get(f"{PORTAL}/c/", timeout=15)
    html = r.text
    
    print(f"Page size: {len(html)} bytes")
    
    # Look for all URLs, links, API endpoints
    urls = re.findall(r'(?:src|href|action)=["\']([^"\']+)["\']', html, re.IGNORECASE)
    print(f"\nURLs found in page:")
    for url in set(urls):
        print(f"  {url}")
    
    # Look for JavaScript variables/objects
    vars_found = re.findall(r'var\s+(\w+)\s*[=:]', html)
    print(f"\nJS variables:")
    for v in sorted(set(vars_found)):
        print(f"  {v}")
    
    # Look for any JSON-like data
    json_like = re.findall(r'\{[^{}]*\}', html)
    for j in json_like:
        if len(j) > 20 and len(j) < 500:
            print(f"\nJSON-like fragment ({len(j)} chars): {j[:300]}")
    
    # Look for server paths/endpoints
    paths = re.findall(r'["\']([a-zA-Z0-9_/.-]+\.php[^"\']*)["\']', html)
    print(f"\nPHP endpoints:")
    for p in sorted(set(paths)):
        print(f"  {p}")
    
    # Check if there's a login mechanism
    print(f"\nSearching for login/forms...")
    if "login" in html.lower():
        login_idx = html.lower().index("login")
        print(f"  'login' found at {login_idx}")
        print(f"  Context: {html[max(0,login_idx-100):login_idx+200]}")
    
    if "form" in html.lower():
        forms = re.findall(r'<form[^>]*>', html, re.IGNORECASE)
        print(f"  Forms found: {len(forms)}")
        for f in forms:
            print(f"    {f}")
    
    # Search for channel-related keywords
    keywords = ["channel", "canal", "tv", "stream", "m3u", "playlist", "json", "api"]
    for kw in keywords:
        if kw in html.lower():
            idx = html.lower().index(kw)
            print(f"  Keyword '{kw}' at {idx}: ...{html[max(0,idx-40):idx+80]}...")


if __name__ == "__main__":
    analyze()
