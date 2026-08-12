"""Small, backend-agnostic release manifest and integrity verifier."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

MAX_MANIFEST_BYTES = 256 * 1024
VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


@dataclass(frozen=True)
class ReleaseArtifact:
    platform: str
    filename: str
    url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    published_at: str
    notes_url: str
    artifacts: tuple[ReleaseArtifact, ...]


def version_tuple(version: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.fullmatch(version.strip())
    if not match:
        raise ValueError("Versão inválida; é esperado o formato X.Y.Z.")
    return tuple(int(part) for part in match.groups())


def is_newer_version(candidate: str, current: str) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def parse_manifest(data: dict) -> ReleaseInfo:
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Manifesto de atualização incompatível.")
    version = str(data.get("version", ""))
    version_tuple(version)
    raw_artifacts = data.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise ValueError("O manifesto não contém artefactos.")

    artifacts = []
    for raw in raw_artifacts:
        if not isinstance(raw, dict):
            raise ValueError("Artefacto de atualização inválido.")
        sha256 = str(raw.get("sha256", "")).lower()
        filename = Path(str(raw.get("filename", ""))).name
        size = int(raw.get("size", 0))
        url = str(raw.get("url", ""))
        if not filename or not re.fullmatch(r"[0-9a-f]{64}", sha256) or size < 1:
            raise ValueError("Metadados de artefacto inválidos.")
        if url and urlparse(url).scheme != "https":
            raise ValueError("Os artefactos remotos têm de usar HTTPS.")
        artifacts.append(
            ReleaseArtifact(
                platform=str(raw.get("platform", "")),
                filename=filename,
                url=url,
                sha256=sha256,
                size=size,
            )
        )
    notes_url = str(data.get("notes_url", ""))
    if notes_url and urlparse(notes_url).scheme != "https":
        raise ValueError("As notas de versão têm de usar HTTPS.")
    return ReleaseInfo(
        version=version,
        published_at=str(data.get("published_at", "")),
        notes_url=notes_url,
        artifacts=tuple(artifacts),
    )


def fetch_manifest(url: str, timeout: int = 15) -> ReleaseInfo:
    if urlparse(url).scheme != "https":
        raise ValueError("O manifesto de atualização tem de usar HTTPS.")
    response = requests.get(url, timeout=timeout, stream=True)
    response.raise_for_status()
    content_length = int(response.headers.get("Content-Length", 0) or 0)
    if content_length > MAX_MANIFEST_BYTES:
        raise ValueError("Manifesto de atualização demasiado grande.")
    payload = bytearray()
    for chunk in response.iter_content(16 * 1024):
        payload.extend(chunk)
        if len(payload) > MAX_MANIFEST_BYTES:
            raise ValueError("Manifesto de atualização demasiado grande.")
    return parse_manifest(json.loads(payload))


def verify_artifact(path: Path, artifact: ReleaseArtifact) -> bool:
    if not path.is_file():
        return False
    if path.stat().st_size != artifact.size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == artifact.sha256
