#!/usr/bin/env python3
"""Generate the release key pair or sign an update manifest (release tooling).

Usage:
    # 1. Create a key pair once and paste the printed public key into
    #    config/__init__.py (RELEASE_PUBLIC_KEY), keeping the private key offline.
    python scripts/sign_manifest.py --generate release-key.pem

    # 2. Sign the manifest after editing its contents (adds "signature").
    python scripts/sign_manifest.py --sign release-key.pem release/update-manifest.json
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Crypto.PublicKey import ECC  # noqa: E402
from Crypto.Signature import eddsa  # noqa: E402

from src.core.update_manager import SIGNATURE_FIELD, canonical_payload  # noqa: E402


def generate_keypair(key_path: Path) -> None:
    key = ECC.generate(curve="Ed25519")
    key_path.write_text(key.export_key(format="PEM"), encoding="ascii")
    public_key = base64.b64encode(
        key.public_key().export_key(format="raw")
    ).decode("ascii")
    print(f"Chave privada escrita em: {key_path}")
    print("Publica esta chave em config/__init__.py (RELEASE_PUBLIC_KEY):")
    print(public_key)


def sign_manifest(key_path: Path, manifest_path: Path) -> None:
    key = ECC.import_key(key_path.read_text(encoding="ascii"))
    # utf-8-sig: release.ps1 writes the manifest with a BOM on PowerShell 5.1.
    data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    data.pop(SIGNATURE_FIELD, None)
    signature = eddsa.new(key, "rfc8032").sign(canonical_payload(data))
    data[SIGNATURE_FIELD] = base64.b64encode(signature).decode("ascii")
    manifest_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Manifesto assinado: {manifest_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", metavar="PRIVATE_KEY", type=Path)
    parser.add_argument("--sign", metavar="PRIVATE_KEY", type=Path)
    parser.add_argument("manifest", nargs="?", type=Path)
    args = parser.parse_args()

    if args.generate:
        generate_keypair(args.generate)
        return 0
    if args.sign and args.manifest:
        sign_manifest(args.sign, args.manifest)
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
