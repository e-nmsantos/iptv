"""Privacy-safe, bounded stream availability diagnostics."""

import time
from urllib.parse import urlparse

import requests


def diagnose_channel(channel, timeout: int = 10) -> dict:
    parsed = urlparse(channel.url)
    protocol = parsed.scheme.lower() or "desconhecido"
    result = {
        "name": channel.name,
        "protocol": protocol.upper(),
        "host": parsed.hostname or "",
        "status": "não testado",
        "latency_ms": 0,
        "content_type": "",
    }
    if protocol not in ("http", "https"):
        result["status"] = "protocolo suportado pelo VLC; teste HTTP indisponível"
        return result
    headers = dict(channel.custom_headers or {})
    if channel.user_agent:
        headers["User-Agent"] = channel.user_agent
    if channel.referer:
        headers["Referer"] = channel.referer
    headers["Range"] = "bytes=0-1023"
    started = time.perf_counter()
    try:
        response = requests.get(
            channel.url,
            headers=headers,
            timeout=max(3, min(int(timeout), 30)),
            stream=True,
            allow_redirects=True,
        )
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)
        result["status"] = f"HTTP {response.status_code}"
        result["content_type"] = response.headers.get("Content-Type", "").split(";", 1)[0]
        response.close()
    except requests.RequestException as exc:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)
        result["status"] = type(exc).__name__
    return result


# Statuses that refuse the account rather than one channel: zapping on just hits
# the same wall, so the caller should stop auto-advancing.
_ACCOUNT_STATUSES = {401, 403, 407, 429, 456, 458, 506, 509}


def explain_failure(result: dict) -> tuple[str, bool]:
    """Turn a :func:`diagnose_channel` result into ``(reason, account_level)``.

    ``reason`` is empty when the server answered normally, i.e. the failure lies
    in the stream itself (format, codec) rather than in the provider.
    """
    if result.get("resolve_error"):
        return (
            "O portal não devolveu um link para este canal "
            f"({result['resolve_error']}). A conta ou o canal podem estar inativos.",
            False,
        )
    status = str(result.get("status", ""))
    if status.startswith("HTTP "):
        try:
            code = int(status.split()[1])
        except (IndexError, ValueError):
            return "", False
        if code < 400:
            return "", False
        if code in (401, 403):
            return (
                f"O fornecedor recusou o acesso (HTTP {code}): a conta pode ter expirado "
                "ou o MAC/credenciais foram bloqueados.",
                True,
            )
        if code in _ACCOUNT_STATUSES:
            return (
                f"O fornecedor recusou a ligação (HTTP {code}): normalmente é o limite de "
                "ligações da conta. Fecha a reprodução noutros dispositivos ou apps.",
                True,
            )
        if code in (404, 410):
            return f"O canal já não existe no servidor (HTTP {code}).", False
        if code >= 500:
            return (
                f"O canal está indisponível no servidor (HTTP {code}). Canais de eventos "
                "só emitem durante o evento.",
                False,
            )
        return f"O servidor recusou o canal (HTTP {code}).", False
    if status in ("ConnectTimeout", "ConnectionError", "SSLError"):
        return "O servidor do canal não responde: pode estar em baixo ou inacessível.", False
    if status == "ReadTimeout":
        return "O servidor aceitou a ligação mas não enviou vídeo.", False
    return "", False
