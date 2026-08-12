"""Integration tests using a local HTTP server; no external traffic."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from src.core.epg_loader import load_xmltv
from src.parsers.m3u_parser import M3UParser
from src.parsers.xtream_parser import XtreamParser


class _ProviderHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/playlist.m3u":
            payload = (
                b'#EXTM3U x-tvg-url="/guide.xml"\n'
                b'#EXTINF:-1 tvg-id="local.one",Local Channel\n'
                b"http://127.0.0.1/live.ts\n"
            )
            content_type = "audio/x-mpegurl"
        elif parsed.path == "/guide.xml":
            payload = (
                b'<tv><programme channel="local.one" '
                b'start="20260803120000 +0000" stop="20260803130000 +0000">'
                b"<title>Local programme</title></programme></tv>"
            )
            content_type = "application/xml"
        elif parsed.path == "/player_api.php":
            action = parse_qs(parsed.query, keep_blank_values=True).get(
                "action", [""]
            )[0]
            if action == "get_live_streams":
                data = [
                    {
                        "stream_id": 7,
                        "name": "Local Xtream",
                        "container_extension": "ts",
                        "epg_channel_id": "local.xtream",
                    }
                ]
            else:
                data = {
                    "user_info": {"auth": 1},
                    "server_info": {
                        "url": "127.0.0.1",
                        "server_protocol": "http",
                        "port": self.server.server_port,
                    },
                }
            payload = json.dumps(data).encode()
            content_type = "application/json"
        else:
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class LocalProviderIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_m3u_and_epg_over_http(self):
        playlist = M3UParser().parse(f"{self.base_url}/playlist.m3u")
        epg = load_xmltv(f"{self.base_url}/guide.xml")

        self.assertEqual(playlist.channels[0].name, "Local Channel")
        self.assertEqual(
            epg.get_programs("local.one")[0].title, "Local programme"
        )

    def test_xtream_authentication_and_lazy_live_import(self):
        parser = XtreamParser(self.base_url, "user", "password")
        parser.authenticate()
        playlist = parser.get_full_playlist(
            include_vod=False, include_series=False
        )

        self.assertEqual(len(playlist.channels), 1)
        self.assertEqual(playlist.channels[0].name, "Local Xtream")


if __name__ == "__main__":
    unittest.main()
