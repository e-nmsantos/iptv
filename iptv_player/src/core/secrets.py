"""Encryption of sensitive database values using an OS-protected master key."""

import base64
import binascii
import os
from typing import Optional

from Crypto.Cipher import AES


class SecretStore:
    """Encrypt values with AES-GCM.

    The random master key is stored by ``keyring`` in the operating system's
    credential manager. Only encrypted values are written to SQLite.
    """

    PREFIX = "enc:v1:"
    SERVICE = "IPTV Player"
    ACCOUNT = "database-encryption-key-v1"

    def __init__(self, key: Optional[bytes] = None):
        self._key = key or self._load_or_create_system_key()
        if len(self._key) != 32:
            raise ValueError("A chave de cifra tem de ter 32 bytes.")

    @classmethod
    def for_tests(cls, key: bytes = b"\x01" * 32) -> "SecretStore":
        """Create an isolated store without accessing the OS credential manager."""
        return cls(key=key)

    @classmethod
    def _load_or_create_system_key(cls) -> bytes:
        try:
            import keyring
            from keyring.errors import KeyringError
        except ImportError as exc:
            raise RuntimeError(
                "A dependência 'keyring' é necessária para proteger as credenciais. "
                "Executa: pip install -r requirements.txt"
            ) from exc

        try:
            encoded = keyring.get_password(cls.SERVICE, cls.ACCOUNT)
            if encoded:
                try:
                    return base64.urlsafe_b64decode(encoded.encode("ascii"))
                except (ValueError, binascii.Error, UnicodeEncodeError) as exc:
                    raise RuntimeError(
                        "A chave guardada no gestor de credenciais é inválida."
                    ) from exc

            key = os.urandom(32)
            keyring.set_password(
                cls.SERVICE,
                cls.ACCOUNT,
                base64.urlsafe_b64encode(key).decode("ascii"),
            )
            return key
        except KeyringError as exc:
            raise RuntimeError(
                "Não foi possível aceder ao gestor de credenciais do sistema. "
                "As credenciais não serão guardadas sem proteção."
            ) from exc

    def encrypt(self, value: str) -> str:
        """Encrypt a string; empty values are unchanged.

        Values already carrying the encryption prefix are verified with an
        actual decryption attempt: genuine ciphertext passes through
        unchanged, while plaintext that merely happens to start with the
        prefix (e.g. a URL like "enc:v1:...") is still encrypted.
        """
        if not value:
            return value
        if value.startswith(self.PREFIX):
            try:
                self.decrypt(value)
                return value
            except (RuntimeError, ValueError):
                pass

        nonce = os.urandom(12)
        cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(value.encode("utf-8"))
        payload = base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii")
        return self.PREFIX + payload

    def decrypt(self, value: str) -> str:
        """Decrypt a stored value, preserving legacy plaintext values."""
        if not value or not value.startswith(self.PREFIX):
            return value

        try:
            payload = base64.urlsafe_b64decode(
                value[len(self.PREFIX):].encode("ascii")
            )
            nonce, tag, ciphertext = payload[:12], payload[12:28], payload[28:]
            cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
            return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError(
                "Não foi possível decifrar dados da aplicação. "
                "A chave do gestor de credenciais pode ter sido removida."
            ) from exc
