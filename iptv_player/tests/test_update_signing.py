"""Release manifest signing: Ed25519 verification, canonical payload."""

import base64
import json

import pytest
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from src.core.update_manager import (
    canonical_payload,
    parse_manifest,
    verify_manifest_signature,
)


def _manifest(**overrides):
    data = {
        "schema_version": 1,
        "version": "9.9.9",
        "published_at": "2026-01-01T00:00:00Z",
        "notes_url": "https://example.test/notes",
        "artifacts": [
            {
                "platform": "windows-x86_64",
                "filename": "IPTV-Setup.exe",
                "url": "https://example.test/IPTV-Setup.exe",
                "sha256": "a" * 64,
                "size": 1024,
            }
        ],
    }
    data.update(overrides)
    return data


def _keypair():
    key = ECC.generate(curve="Ed25519")
    public_b64 = base64.b64encode(
        key.public_key().export_key(format="raw")
    ).decode("ascii")
    return key, public_b64


def _sign(key, data):
    return base64.b64encode(eddsa.new(key, "rfc8032").sign(canonical_payload(data))).decode(
        "ascii"
    )


class TestCanonicalPayload:
    def test_signature_field_is_excluded(self):
        data = _manifest(signature="abc")

        payload = canonical_payload(data)

        assert b"signature" not in payload
        assert payload == canonical_payload(_manifest())

    def test_key_order_does_not_matter(self):
        first = _manifest()
        second = dict(reversed(list(_manifest().items())))

        assert canonical_payload(first) == canonical_payload(second)


class TestSignatureVerification:
    def test_valid_signature_is_accepted(self):
        key, public_b64 = _keypair()
        data = _manifest()

        assert verify_manifest_signature(data, _sign(key, data), public_b64)

    def test_tampered_manifest_is_rejected(self):
        key, public_b64 = _keypair()
        data = _manifest()
        signature = _sign(key, data)
        data["version"] = "9.9.10"

        assert not verify_manifest_signature(data, signature, public_b64)

    def test_other_key_is_rejected(self):
        key, _ = _keypair()
        _, other_public = _keypair()
        data = _manifest()

        assert not verify_manifest_signature(data, _sign(key, data), other_public)

    @pytest.mark.parametrize("signature", ["", "não-é-base64!", "YWJj"])
    def test_malformed_signatures_are_rejected(self, signature):
        _, public_b64 = _keypair()

        assert not verify_manifest_signature(_manifest(), signature, public_b64)


class TestParseManifestPolicy:
    def test_unsigned_manifest_is_accepted_without_a_configured_key(self):
        info = parse_manifest(_manifest(), public_key="")

        assert info.version == "9.9.9"
        assert len(info.artifacts) == 1

    def test_signed_manifest_is_accepted_with_a_configured_key(self):
        key, public_b64 = _keypair()
        data = _manifest()
        data["signature"] = _sign(key, data)

        info = parse_manifest(data, public_key=public_b64)

        assert info.version == "9.9.9"

    def test_unsigned_manifest_is_rejected_when_a_key_is_configured(self):
        _, public_b64 = _keypair()

        with pytest.raises(ValueError, match="Assinatura do manifesto"):
            parse_manifest(_manifest(), public_key=public_b64)

    def test_tampered_signed_manifest_is_rejected(self):
        key, public_b64 = _keypair()
        data = _manifest()
        data["signature"] = _sign(key, data)
        data["version"] = "9.9.10"

        with pytest.raises(ValueError, match="Assinatura do manifesto"):
            parse_manifest(data, public_key=public_b64)

    def test_signature_field_is_not_needed_by_the_parser(self):
        key, public_b64 = _keypair()
        data = _manifest()
        data["signature"] = _sign(key, data)

        info = parse_manifest(data, public_key=public_b64)

        assert json.loads(json.dumps(data))["signature"] == data["signature"]
        assert info.published_at == "2026-01-01T00:00:00Z"
