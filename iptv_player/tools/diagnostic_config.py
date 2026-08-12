"""Configuration shared by manual network diagnostic scripts.

Set IPTV_TEST_PORTAL and IPTV_TEST_MAC before running a script. The safe
defaults only target a closed local port, preventing accidental requests to a
real third-party service.
"""

import os


PORTAL = os.environ.get("IPTV_TEST_PORTAL", "http://127.0.0.1:9").rstrip("/")
MAC = os.environ.get("IPTV_TEST_MAC", "00:00:00:00:00:00")
MAC_CLEAN = MAC.lower().replace(":", "")
