"""Shared HTTP policy for provider and catalogue traffic."""

from collections.abc import Callable
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class RequestCancelled(RuntimeError):
    """Raised before a request when its owning task has been cancelled."""


class HttpSession(requests.Session):
    """Session with bounded defaults, retry policy and cooperative cancellation."""

    def __init__(
        self,
        timeout: int = 30,
        cancel_requested: Optional[Callable[[], bool]] = None,
        retries: int = 3,
    ):
        super().__init__()
        self._default_timeout = max(5, int(timeout))
        self._cancel_requested = cancel_requested or (lambda: False)
        retry = Retry(
            total=max(0, int(retries)),
            connect=max(0, int(retries)),
            read=max(0, int(retries)),
            status=max(0, int(retries)),
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        self.mount("http://", adapter)
        self.mount("https://", adapter)

    def request(self, method, url, **kwargs):
        if self._cancel_requested():
            raise RequestCancelled("Operação de rede cancelada.")
        kwargs.setdefault("timeout", self._default_timeout)
        response = super().request(method, url, **kwargs)
        if self._cancel_requested():
            response.close()
            raise RequestCancelled("Operação de rede cancelada.")
        return response
