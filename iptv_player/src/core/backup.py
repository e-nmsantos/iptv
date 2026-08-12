"""Password-encrypted, portable application backup format."""

import json
import os
import zlib
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import scrypt

MAGIC = b"IPTVBKP1"
MAX_BACKUP_BYTES = 128 * 1024 * 1024
MAX_JSON_BYTES = 512 * 1024 * 1024


def _derive_key(password: str, salt: bytes) -> bytes:
    if len(password) < 8:
        raise ValueError("A palavra-passe do backup deve ter pelo menos 8 caracteres.")
    return scrypt(password.encode("utf-8"), salt, 32, N=2**15, r=8, p=1)


def create_backup(path: Path, data: dict, password: str):
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    compressed = zlib.compress(raw, level=9)
    if len(compressed) > MAX_BACKUP_BYTES:
        raise ValueError("O backup excede o limite de 128 MB.")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    cipher = AES.new(_derive_key(password, salt), AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(compressed)
    path.write_bytes(MAGIC + salt + nonce + tag + ciphertext)


def read_backup(path: Path, password: str) -> dict:
    if not path.is_file() or path.stat().st_size > MAX_BACKUP_BYTES:
        raise ValueError("Ficheiro de backup inválido ou demasiado grande.")
    payload = path.read_bytes()
    if not payload.startswith(MAGIC) or len(payload) < len(MAGIC) + 44:
        raise ValueError("Formato de backup inválido.")
    offset = len(MAGIC)
    salt = payload[offset : offset + 16]
    nonce = payload[offset + 16 : offset + 28]
    tag = payload[offset + 28 : offset + 44]
    ciphertext = payload[offset + 44 :]
    try:
        cipher = AES.new(_derive_key(password, salt), AES.MODE_GCM, nonce=nonce)
        compressed = cipher.decrypt_and_verify(ciphertext, tag)
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(compressed, MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES or decompressor.unconsumed_tail:
            raise ValueError("Conteúdo do backup demasiado grande.")
        raw += decompressor.flush()
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, zlib.error) as exc:
        raise ValueError("Backup danificado ou palavra-passe incorreta.") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Versão de backup incompatível.")
    return data
