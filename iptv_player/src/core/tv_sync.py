"""Two-way favourites/resume sync with the Android TV app over the home network.

The TV advertises its pairing server as ``_iptv-pair._tcp`` (port only) while
its "Telemóvel ou computador" screen is open, and shows a 6-digit PIN.
``GET /sync/<pin>`` returns the TV's credential-free state and
``POST /sync/<pin>`` merges ours; five wrong PINs end the TV's session.
"""

import ipaddress
import json
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import requests

SERVICE_TYPE = "_iptv-pair._tcp.local."


@dataclass(frozen=True)
class TvEndpoint:
    name: str
    host: str
    port: int

    @property
    def label(self) -> str:
        return f"{self.name} ({self.host})"


def _is_local_address(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def discover_tvs(timeout_seconds: float = 3.0) -> list[TvEndpoint]:
    """Browse the LAN for TVs with their pairing screen open."""
    from zeroconf import ServiceBrowser, Zeroconf

    found: dict[str, TvEndpoint] = {}
    zeroconf = Zeroconf()

    class _Listener:
        def add_service(self, zc, service_type, name):
            info = zc.get_service_info(service_type, name, timeout=1500)
            if not info or not info.port:
                return
            for raw in info.addresses:
                if len(raw) != 4:
                    continue
                host = socket.inet_ntoa(raw)
                if _is_local_address(host):
                    label = name.removesuffix("." + service_type).strip() or "TV"
                    found[name] = TvEndpoint(label, host, int(info.port))
                    break

        def update_service(self, zc, service_type, name):
            self.add_service(zc, service_type, name)

        def remove_service(self, zc, service_type, name):
            found.pop(name, None)

    try:
        ServiceBrowser(zeroconf, SERVICE_TYPE, _Listener())
        time.sleep(max(0.5, timeout_seconds))
    finally:
        zeroconf.close()
    return sorted(found.values(), key=lambda endpoint: endpoint.name.casefold())


def exchange_with_tv(endpoint: TvEndpoint, pin: str, build_desktop_state, timeout: float = 10.0) -> str:
    """Fetch the TV state, then send ours; returns the TV state JSON.

    ``build_desktop_state(tv_state)`` is called between the two requests so the
    caller can merge the TV's state first and send back the union.
    """
    pin = pin.strip().replace(" ", "")
    if not (len(pin) == 6 and pin.isdigit()):
        raise ValueError("O PIN tem 6 algarismos (aparece no ecrã da TV).")
    if not _is_local_address(endpoint.host):
        raise ValueError("Só é possível sincronizar com TVs da rede local.")
    url = f"http://{endpoint.host}:{endpoint.port}/sync/{pin}"
    response = requests.get(url, timeout=timeout)
    if response.status_code == 403:
        raise ValueError("PIN incorreto. Confirma o número no ecrã da TV.")
    response.raise_for_status()
    tv_state = response.text
    json.loads(tv_state)  # reject anything that isn't JSON before merging it
    desktop_state = build_desktop_state(tv_state)
    response = requests.post(
        url,
        data=urlencode({"source_type": "sync", "sync_data": desktop_state}),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=timeout,
    )
    if response.status_code == 409:
        raise ValueError("Este PIN já foi usado. Cria um novo código na TV.")
    response.raise_for_status()
    return tv_state
