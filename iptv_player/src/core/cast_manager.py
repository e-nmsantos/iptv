"""Cast & DLNA manager for streaming IPTV content to Smart TVs and Chromecast."""

import http.server
import logging
import re
import socket
import socketserver
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


def get_local_ip() -> str:
    """Get the primary local IPv4 address on the Wi-Fi/LAN interface."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


@dataclass
class CastDevice:
    device_id: str
    name: str
    device_type: str  # "chromecast", "dlna", "smart_tv", "vlc_renderer"
    location: str
    control_url: str = ""
    vlc_renderer: Optional[object] = None
    chromecast_obj: Optional[object] = None


class _ProxyRequestHandler(http.server.BaseHTTPRequestHandler):
    """HTTP Request handler to proxy IPTV streams with custom headers and CORS,
    including on-the-fly HLS packaging for Chromecast compatibility.
    """

    def log_message(self, format, *args):
        logger.debug("CastProxy: " + format, *args)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_HEAD(self):
        self._dispatch(head_only=True)

    def do_GET(self):
        self._dispatch(head_only=False)

    def _dispatch(self, head_only: bool = False):
        server: _CastStreamProxyServer = self.server

        # 1. Live HLS manifest
        if "/hls/live.m3u8" in self.path:
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Content-Type", "application/x-mpegURL")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            if head_only:
                return

            with server.hls_lock:
                seqs = sorted(server.hls_chunks.keys())
                min_seq = seqs[0] if seqs else 1

            host_header = self.headers.get("Host") or f"{server.proxy_instance._local_ip}:{server.proxy_instance._port}"
            manifest_lines = [
                "#EXTM3U",
                "#EXT-X-VERSION:3",
                "#EXT-X-TARGETDURATION:4",
                f"#EXT-X-MEDIA-SEQUENCE:{min_seq}",
            ]
            for s in seqs:
                manifest_lines.append("#EXTINF:3.0,")
                manifest_lines.append(f"http://{host_header}/hls/chunk_{s}.ts")

            body = "\n".join(manifest_lines) + "\n"
            try:
                self.wfile.write(body.encode("utf-8"))
            except (ConnectionResetError, BrokenPipeError):
                pass
            return

        # 2. Live HLS TS chunk
        if "/hls/chunk_" in self.path:
            try:
                chunk_id_str = self.path.split("/hls/chunk_")[1].split(".ts")[0]
                chunk_id = int(chunk_id_str)
            except Exception:
                chunk_id = 0

            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Content-Type", "video/mp2t")
            self.send_header("Accept-Ranges", "bytes")

            with server.hls_lock:
                data = server.hls_chunks.get(chunk_id, b"")

            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if head_only:
                return

            try:
                self.wfile.write(data)
            except (ConnectionResetError, BrokenPipeError):
                pass
            return

        # 3. Direct / Passthrough streaming
        self._serve_direct(head_only=head_only)

    def _serve_direct(self, head_only: bool = False):
        server: _CastStreamProxyServer = self.server
        target_url = server.target_url
        headers = dict(server.target_headers or {})

        if not target_url:
            self.send_error(404, "No active stream")
            return

        range_header = self.headers.get("Range")
        req_headers = dict(headers)
        if range_header:
            req_headers["Range"] = range_header

        try:
            req = urllib.request.Request(target_url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                status = resp.status
                self.send_response(status)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.send_header("Accept-Ranges", "bytes")

                content_type = resp.headers.get("Content-Type")
                if not content_type or "text/plain" in content_type:
                    lower = target_url.lower()
                    if ".m3u8" in lower:
                        content_type = "application/x-mpegURL"
                    elif ".ts" in lower or "extension=ts" in lower or "stream=" in lower:
                        content_type = "video/mp2t"
                    elif ".mp4" in lower:
                        content_type = "video/mp4"
                    elif ".mkv" in lower:
                        content_type = "video/x-matroska"
                    else:
                        content_type = "video/mp2t"

                self.send_header("Content-Type", content_type)

                content_len = resp.headers.get("Content-Length")
                if content_len:
                    self.send_header("Content-Length", content_len)

                content_range = resp.headers.get("Content-Range")
                if content_range:
                    self.send_header("Content-Range", content_range)

                self.end_headers()

                if head_only:
                    return

                buf_size = 64 * 1024
                while getattr(server, "_running", True):
                    chunk = resp.read(buf_size)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (ConnectionResetError, BrokenPipeError):
                        break
        except Exception as e:
            logger.debug("CastProxy forward error: %s", e)
            try:
                if not self.wfile.closed:
                    self.send_error(502, f"Stream proxy error: {e}")
            except Exception:
                pass


class _CastStreamProxyServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, proxy_instance):
        super().__init__(server_address, _ProxyRequestHandler)
        self.proxy_instance: CastStreamProxy = proxy_instance
        self.target_url: str = ""
        self.target_headers: dict = {}
        self._running: bool = True
        self.hls_chunks: dict[int, bytes] = {}
        self.hls_seq: int = 0
        self.hls_lock = threading.Lock()
        self.hls_running: bool = False


class CastStreamProxy:
    """Lightweight local HTTP proxy and live HLS packager for Chromecast & Smart TVs."""

    def __init__(self):
        self._server: Optional[_CastStreamProxyServer] = None
        self._thread: Optional[threading.Thread] = None
        self._hls_thread: Optional[threading.Thread] = None
        self._port: int = 0
        self._local_ip: str = get_local_ip()

    def start(self) -> int:
        if self._server is not None:
            return self._port

        self._local_ip = get_local_ip()
        try:
            self._server = _CastStreamProxyServer(("0.0.0.0", 0), proxy_instance=self)
            self._port = self._server.server_address[1]
            self._server._running = True
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            logger.info("CastStreamProxy listening on %s:%d", self._local_ip, self._port)
            return self._port
        except Exception as e:
            logger.error("Failed to start CastStreamProxy: %s", e)
            return 0

    def set_target(self, url: str, headers: Optional[dict] = None, is_live: bool = True) -> str:
        """Set upstream stream and return local URL. Automatically packages live TS streams into HLS."""
        if not self._server:
            self.start()

        self._stop_hls_streamer()

        if self._server:
            self._server.target_url = url
            self._server.target_headers = headers or {}

        lower = url.lower()
        is_ts_stream = (
            "extension=ts" in lower
            or ".ts" in lower
            or "stream=" in lower
            or is_live
        ) and ".m3u8" not in lower and ".mp4" not in lower and ".mkv" not in lower

        # For live MPEG-TS streams, Chromecast requires HLS container
        if is_ts_stream and is_live:
            self._start_hls_streamer(url, headers or {})
            return f"http://{self._local_ip}:{self._port}/hls/live.m3u8"

        if ".m3u8" in lower:
            ext = "m3u8"
        elif ".mp4" in lower:
            ext = "mp4"
        elif ".mkv" in lower:
            ext = "mkv"
        else:
            ext = "ts"

        return f"http://{self._local_ip}:{self._port}/stream.{ext}"

    def _start_hls_streamer(self, target_url: str, headers: dict):
        """Buffer and segment upstream TS packets into live HLS slices in memory."""
        if not self._server:
            return

        self._server.hls_running = True
        with self._server.hls_lock:
            self._server.hls_chunks.clear()
            self._server.hls_seq = 0

        def worker():
            server = self._server
            if not server:
                return
            logger.info("Starting on-the-fly HLS segmenter for %s", target_url)
            req = urllib.request.Request(target_url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=12) as resp:
                    chunk_size = 188 * 8000
                    while getattr(server, "hls_running", False) and getattr(server, "_running", True):
                        data = resp.read(chunk_size)
                        if not data:
                            break
                        with server.hls_lock:
                            server.hls_seq += 1
                            server.hls_chunks[server.hls_seq] = data
                            if len(server.hls_chunks) > 8:
                                oldest = min(server.hls_chunks.keys())
                                del server.hls_chunks[oldest]
            except Exception as ex:
                logger.debug("HLS segmenter worker ended: %s", ex)

        self._hls_thread = threading.Thread(target=worker, daemon=True)
        self._hls_thread.start()

        # Wait up to 2 seconds for initial chunks to buffer so the manifest isn't empty
        for _ in range(20):
            with self._server.hls_lock:
                if len(self._server.hls_chunks) >= 2:
                    break
            time.sleep(0.1)

    def _stop_hls_streamer(self):
        if self._server:
            self._server.hls_running = False
            with self._server.hls_lock:
                self._server.hls_chunks.clear()
        self._hls_thread = None

    def stop(self):
        self._stop_hls_streamer()
        if self._server:
            try:
                self._server._running = False
                self._server.shutdown()
                self._server.server_close()
            except Exception as e:
                logger.debug("Error stopping proxy server: %s", e)
            self._server = None
            self._thread = None


class CastManager(QObject):
    """Manager for discovering and controlling Cast / DLNA devices on the local network."""

    device_found = Signal(object)  # CastDevice
    device_lost = Signal(str)  # device_id
    casting_state_changed = Signal(bool, str)  # is_casting, device_name

    _instance: Optional["CastManager"] = None

    @classmethod
    def get_instance(cls) -> "CastManager":
        if cls._instance is None:
            cls._instance = CastManager()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._devices: dict[str, CastDevice] = {}
        self._is_discovering = False
        self._active_device: Optional[CastDevice] = None
        self._active_media_player = None
        self._dedicated_player = None
        self._vlc_renderers: dict[str, object] = {}
        self._proxy = CastStreamProxy()
        self._lock = threading.Lock()

    @property
    def is_casting(self) -> bool:
        return self._active_device is not None

    @property
    def active_device(self) -> Optional[CastDevice]:
        return self._active_device

    def list_devices(self) -> list[CastDevice]:
        with self._lock:
            return list(self._devices.values())

    def start_discovery(self, vlc_instance=None):
        """Start discovering local Chromecast and DLNA/UPnP Smart TVs."""
        if self._is_discovering:
            return
        self._is_discovering = True

        # 1. Background SSDP thread for DLNA / Smart TVs
        t = threading.Thread(target=self._ssdp_discovery_worker, daemon=True)
        t.start()

        # 2. LibVLC Chromecast discovery if available
        if vlc_instance and hasattr(vlc_instance, "renderer_discoverer_new"):
            threading.Thread(
                target=self._vlc_renderer_worker,
                args=(vlc_instance,),
                daemon=True,
            ).start()

    def _ssdp_discovery_worker(self):
        """Send SSDP M-SEARCH multicast to discover Smart TVs."""
        ssdp_request = (
            b"M-SEARCH * HTTP/1.1\r\n"
            b"HOST: 239.255.255.250:1900\r\n"
            b'MAN: "ssdp:discover"\r\n'
            b"MX: 2\r\n"
            b"ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n\r\n"
        )

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(3.0)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

        try:
            sock.sendto(ssdp_request, ("239.255.255.250", 1900))
            start_time = time.time()
            while time.time() - start_time < 5.0 and self._is_discovering:
                try:
                    data, addr = sock.recvfrom(2048)
                    response = data.decode("utf-8", errors="ignore")
                    location_match = re.search(r"LOCATION:\s*(http://[^\r\n]+)", response, re.IGNORECASE)
                    if location_match:
                        loc = location_match.group(1).strip()
                        self._resolve_upnp_device(loc)
                except socket.timeout:
                    break
                except Exception as e:
                    logger.debug("SSDP recv error: %s", e)
        except Exception as ex:
            logger.debug("SSDP discovery error: %s", ex)
        finally:
            sock.close()

    def _resolve_upnp_device(self, location_url: str):
        """Query device description XML to get friendly name and AVTransport URL."""
        try:
            req = urllib.request.Request(location_url, headers={"User-Agent": "IPTVPlayer/1.0"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                xml_data = resp.read()

            root = ET.fromstring(xml_data)
            name = "Smart TV"
            for elem in root.iter():
                if elem.tag.endswith("friendlyName") and elem.text:
                    name = elem.text.strip()
                    break

            control_url = ""
            for service in root.iter():
                if service.tag.endswith("service"):
                    stype = ""
                    curl = ""
                    for child in service:
                        if child.tag.endswith("serviceType") and child.text:
                            stype = child.text.strip()
                        elif child.tag.endswith("controlURL") and child.text:
                            curl = child.text.strip()
                    if "AVTransport" in stype:
                        if curl.startswith("http"):
                            control_url = curl
                        else:
                            base = "/".join(location_url.split("/")[:3])
                            control_url = base + ("/" if not curl.startswith("/") else "") + curl
                        break

            dev_id = f"dlna_{location_url}"
            device = CastDevice(
                device_id=dev_id,
                name=f"📺 {name}",
                device_type="smart_tv",
                location=location_url,
                control_url=control_url,
            )

            with self._lock:
                if dev_id not in self._devices:
                    self._devices[dev_id] = device
                    self.device_found.emit(device)
        except Exception as e:
            logger.debug("Failed to resolve UPnP device from %s: %s", location_url, e)

    def _vlc_renderer_worker(self, vlc_instance):
        """Discover Chromecast renderers via LibVLC."""
        try:
            import ctypes

            import vlc

            inst = vlc_instance
            if not inst:
                return

            discoverer = inst.renderer_discoverer_new("microdns_renderer")
            if not discoverer:
                discoverer = inst.renderer_discoverer_new("mdns_renderer")
            if not discoverer:
                return

            def on_item_added(event):
                try:
                    raw_ptr = ctypes.cast(
                        ctypes.byref(event.u), ctypes.POINTER(ctypes.c_void_p)
                    ).contents.value
                    if raw_ptr:
                        r_item = vlc.Renderer(raw_ptr)
                        name_raw = r_item.name()
                        name = (
                            name_raw.decode("utf-8", errors="ignore")
                            if isinstance(name_raw, bytes)
                            else str(name_raw)
                        )
                        dtype_raw = r_item.type()
                        dtype = (
                            dtype_raw.decode("utf-8", errors="ignore")
                            if isinstance(dtype_raw, bytes)
                            else str(dtype_raw)
                        )

                        dev_id = f"vlc_{name}"
                        logger.info("Discovered VLC Renderer: %s (type=%s)", name, dtype)
                        with self._lock:
                            self._vlc_renderers[name] = r_item
                            matched = False
                            for existing in self._devices.values():
                                if (
                                    name.lower() in existing.name.lower()
                                    or existing.name.lower() in name.lower()
                                ):
                                    existing.vlc_renderer = r_item
                                    matched = True
                                    break
                            if not matched:
                                dev = CastDevice(
                                    device_id=dev_id,
                                    name=f"📺 {name}",
                                    device_type="chromecast" if dtype == "chromecast" else "vlc_renderer",
                                    location="vlc",
                                    vlc_renderer=r_item,
                                )
                                self._devices[dev_id] = dev
                                self.device_found.emit(dev)
                except Exception as ex:
                    logger.debug("Error processing VLC renderer item: %s", ex)

            em = discoverer.event_manager()
            em.event_attach(vlc.EventType.RendererDiscovererItemAdded, on_item_added)
            self._rd = discoverer
            discoverer.start()
            for _ in range(10):
                if not self._is_discovering:
                    break
                time.sleep(1)
        except Exception as e:
            logger.debug("LibVLC renderer discovery note: %s", e)

    def cast_to_device(
        self,
        device: CastDevice,
        url: str,
        title: str = "IPTV Stream",
        headers: Optional[dict] = None,
        is_live: bool = True,
        media_player=None,
    ) -> bool:
        """Stream playback to the chosen TV / Chromecast."""
        self._active_device = device
        self._active_media_player = media_player
        logger.info(
            "Casting to %s: %s (headers=%s, is_live=%s, media_player=%s)",
            device.name,
            url,
            bool(headers),
            is_live,
            bool(media_player),
        )

        # 0. Check VLC native renderer
        vlc_renderer = device.vlc_renderer
        if not vlc_renderer:
            with self._lock:
                for r_name, r_item in self._vlc_renderers.items():
                    if (
                        r_name.lower() in device.name.lower()
                        or device.name.lower() in r_name.lower()
                    ):
                        vlc_renderer = r_item
                        device.vlc_renderer = r_item
                        break

        if vlc_renderer:
            if media_player and hasattr(media_player, "set_renderer"):
                success = media_player.set_renderer(vlc_renderer)
                if success:
                    self.casting_state_changed.emit(True, device.name)
                    return True

            # If no media_player or set_renderer not supported, use dedicated VLC instance
            def vlc_cast_worker():
                try:
                    import vlc

                    inst_args = ["--quiet", "--no-video-title-show"]
                    if headers and headers.get("User-Agent"):
                        inst_args.append(f"--http-user-agent={headers['User-Agent']}")
                    inst = vlc.Instance(inst_args)
                    player = inst.media_player_new()
                    player.set_renderer(vlc_renderer)
                    media = inst.media_new(url)
                    player.set_media(media)
                    player.play()
                    self._dedicated_player = player
                    self.casting_state_changed.emit(True, device.name)
                except Exception as ex:
                    logger.error("Dedicated VLC cast worker failed: %s", ex)
                    self.casting_state_changed.emit(False, "")

            threading.Thread(target=vlc_cast_worker, daemon=True).start()
            return True

        # Check if local proxy is needed:
        needs_proxy = (
            bool(headers)
            or "extension=ts" in url.lower()
            or ".ts" in url.lower()
            or "stream=" in url.lower()
            or url.startswith("http://localhost")
            or url.startswith("http://127.0.0.1")
        )
        if needs_proxy:
            play_url = self._proxy.set_target(url, headers, is_live=is_live)
            logger.info("Using local stream proxy: %s", play_url)
        else:
            play_url = url

        # 1. Chromecast / Google TV playback
        if device.device_type == "chromecast" or device.chromecast_obj is not None:
            if media_player and hasattr(media_player, "set_cast_target") and ":" in device.location:
                host_ip = device.location.split(":")[0]
                media_player.set_cast_target(host_ip)
                self.casting_state_changed.emit(True, device.name)
                return True

            def chromecast_play_worker():
                try:
                    cc = device.chromecast_obj
                    if cc is None and ":" in device.location:
                        import uuid

                        import pychromecast

                        host, port = device.location.split(":")
                        cc = pychromecast.get_chromecast_from_host(
                            (host, int(port), uuid.uuid4(), device.name, "Google Cast")
                        )
                        device.chromecast_obj = cc

                    if cc:
                        if hasattr(cc, "wait"):
                            cc.wait(timeout=7)
                        mc = cc.media_controller
                        lower_url = play_url.lower()
                        if ".m3u8" in lower_url:
                            content_type = "application/x-mpegURL"
                        elif ".mp4" in lower_url:
                            content_type = "video/mp4"
                        elif ".mkv" in lower_url:
                            content_type = "video/x-matroska"
                        else:
                            content_type = "application/x-mpegURL" if is_live else "video/mp2t"

                        stream_type = "LIVE" if is_live else "BUFFERED"
                        mc.play_media(
                            play_url,
                            content_type=content_type,
                            title=title or "IPTV Stream",
                            stream_type=stream_type,
                        )
                        self.casting_state_changed.emit(True, device.name)
                    else:
                        raise RuntimeError(f"Could not connect to Chromecast at {device.location}")
                except Exception as ex:
                    logger.error("Failed to cast to Chromecast %s: %s", device.name, ex)
                    self.casting_state_changed.emit(False, "")

            threading.Thread(target=chromecast_play_worker, daemon=True).start()
            self.casting_state_changed.emit(True, device.name)
            return True

        # 2. DLNA AVTransport playback for Smart TVs
        if device.control_url:
            success = self._send_dlna_play(device.control_url, play_url, title)
            if success:
                self.casting_state_changed.emit(True, device.name)
                return True
            else:
                self.casting_state_changed.emit(False, "")
                return False

        self.casting_state_changed.emit(True, device.name)
        return True

    def stop_cast(self) -> bool:
        """Stop active cast playback."""
        dev = self._active_device
        self._active_device = None

        if self._active_media_player:
            try:
                if hasattr(self._active_media_player, "clear_renderer"):
                    self._active_media_player.clear_renderer()
                if hasattr(self._active_media_player, "clear_cast_target"):
                    self._active_media_player.clear_cast_target()
            except Exception as ex:
                logger.debug("Error clearing media_player cast target: %s", ex)
            self._active_media_player = None

        if self._dedicated_player:
            try:
                self._dedicated_player.stop()
            except Exception:
                pass
            self._dedicated_player = None

        if dev:
            if dev.chromecast_obj:
                def stop_cc():
                    try:
                        dev.chromecast_obj.media_controller.stop()
                    except Exception as ex:
                        logger.debug("Error stopping chromecast: %s", ex)
                    try:
                        dev.chromecast_obj.quit_app()
                    except Exception as ex:
                        logger.debug("Error quitting chromecast app: %s", ex)

                threading.Thread(target=stop_cc, daemon=True).start()
            if dev.control_url:
                self._send_dlna_stop(dev.control_url)

        self._proxy.stop()
        self.casting_state_changed.emit(False, "")
        return dev is not None

    def _send_dlna_play(self, control_url: str, stream_url: str, title: str) -> bool:
        """Send UPnP SetAVTransportURI and Play SOAP actions."""
        try:
            soap_body_set = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:SetAVTransportURI xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      <CurrentURI>{stream_url}</CurrentURI>
      <CurrentURIMetaData></CurrentURIMetaData>
    </u:SetAVTransportURI>
  </s:Body>
</s:Envelope>"""

            req = urllib.request.Request(
                control_url,
                data=soap_body_set.encode("utf-8"),
                headers={
                    "Content-Type": 'text/xml; charset="utf-8"',
                    "SOAPAction": '"urn:schemas-upnp-org:service:AVTransport:1#SetAVTransportURI"',
                    "User-Agent": "IPTVPlayer/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=4.0):
                pass

            soap_body_play = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:Play xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      <Speed>1</Speed>
    </u:Play>
  </s:Body>
</s:Envelope>"""

            req2 = urllib.request.Request(
                control_url,
                data=soap_body_play.encode("utf-8"),
                headers={
                    "Content-Type": 'text/xml; charset="utf-8"',
                    "SOAPAction": '"urn:schemas-upnp-org:service:AVTransport:1#Play"',
                    "User-Agent": "IPTVPlayer/1.0",
                },
            )
            with urllib.request.urlopen(req2, timeout=4.0):
                pass

            return True
        except Exception as e:
            logger.warning("DLNA SOAP error: %s", e)
            return False

    def _send_dlna_stop(self, control_url: str) -> bool:
        """Send UPnP Stop SOAP action."""
        try:
            soap_body_stop = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:Stop xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
    </u:Stop>
  </s:Body>
</s:Envelope>"""

            req = urllib.request.Request(
                control_url,
                data=soap_body_stop.encode("utf-8"),
                headers={
                    "Content-Type": 'text/xml; charset="utf-8"',
                    "SOAPAction": '"urn:schemas-upnp-org:service:AVTransport:1#Stop"',
                    "User-Agent": "IPTVPlayer/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=3.0):
                pass
            return True
        except Exception:
            return False
