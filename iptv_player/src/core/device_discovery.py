"""Local network discovery for IPTV Player Android TV pairing instances."""

import logging
import socket
import threading
from typing import Optional
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class DiscoveredTvDevice:
    """Represents an IPTV Player TV pairing session discovered on the local network."""

    def __init__(self, host: str, port: int, pairing_url: str, device_name: str = "Android TV"):
        self.host = host
        self.port = port
        self.pairing_url = pairing_url
        self.device_name = device_name

    def __repr__(self):
        return f"<DiscoveredTvDevice {self.device_name} at {self.host}:{self.port}>"


class DeviceDiscoveryManager:
    """Scans and manages local network pairing discovery."""

    DEFAULT_PORTS = [8080, 8081, 8888, 5000, 3000]

    def __init__(self):
        self._discovered: list[DiscoveredTvDevice] = []
        self._lock = threading.Lock()

    def discover_devices(
        self,
        timeout_seconds: float = 2.0,
        subnet_prefix: Optional[str] = None,
    ) -> list[DiscoveredTvDevice]:
        """Perform a quick local subnet probe for active IPTV Player TV pairing endpoints."""
        devices: list[DiscoveredTvDevice] = []

        # Find local IP address
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
        except Exception:
            local_ip = "127.0.0.1"

        if local_ip == "127.0.0.1":
            return devices

        prefix = subnet_prefix or ".".join(local_ip.split(".")[:3])
        current_last_octet = int(local_ip.split(".")[-1])

        # Probe nearby hosts on common ports
        # Check adjacent IPs first to be fast
        target_hosts = [f"{prefix}.{i}" for i in range(1, 255) if i != current_last_octet]

        def probe_host(host: str, port: int):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.3)
                res = sock.connect_ex((host, port))
                sock.close()
                if res == 0:
                    # Valid open port, check if it responds to HTTP
                    url = f"http://{host}:{port}/"
                    req = Request(url, headers={"User-Agent": "IPTVPlayer-Discovery/1.0"})
                    with urlopen(req, timeout=0.5) as resp:
                        content = resp.read(1024).decode("utf-8", errors="ignore")
                        if "iptv" in content.lower() or "emparelhamento" in content.lower() or "pair" in content.lower():
                            devices.append(DiscoveredTvDevice(host, port, url, f"IPTV TV ({host})"))
            except Exception:
                pass

        threads = []
        # Probe top candidate IPs and common ports concurrently
        for host in target_hosts[:30]:  # Quick probe of first 30 targets
            for port in [8080, 8081]:
                t = threading.Thread(target=probe_host, args=(host, port), daemon=True)
                threads.append(t)
                t.start()

        for t in threads:
            t.join(timeout=timeout_seconds / 2)

        with self._lock:
            self._discovered = devices
        return devices

