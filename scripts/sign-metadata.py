#!/usr/bin/env python3
"""
本地元数据签名脚本：聚合源清单、授信列表与精选，生成签名元数据。
正式 CI 就绪前替代 GitHub Actions 签名聚合流程。

用法：
    SIGNING_KEY_HEX=<私钥hex> python3 scripts/sign-metadata.py
"""

import json
import base64
import os
import sys
import datetime
from pathlib import Path

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
except ImportError:
    print("需要安装 cryptography: pip install cryptography", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent


def main():
    key_hex = os.environ.get("SIGNING_KEY_HEX")
    if not key_hex or len(key_hex) != 64:
        print("错误：请设置环境变量 SIGNING_KEY_HEX（32 字节私钥的 hex 编码）", file=sys.stderr)
        sys.exit(1)

    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key_hex))

    source_path = REPO_ROOT / "codex-themer-source.json"
    trusted_path = REPO_ROOT / "trusted-sources.json"
    featured_path = REPO_ROOT / "featured.json"

    with open(source_path) as f:
        official_source = json.load(f)
    with open(trusted_path) as f:
        trusted_data = json.load(f)
    with open(featured_path) as f:
        featured = json.load(f)

    trusted_sources = trusted_data.get("sources", [])

    metadata = {
        "metadataSchemaVersion": 1,
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "officialSource": official_source,
        "trustedSources": trusted_sources,
        "featured": featured,
    }

    metadata_bytes = json.dumps(metadata, indent=2, ensure_ascii=False).encode("utf-8")
    signature = private_key.sign(metadata_bytes)
    sig_b64 = base64.standard_b64encode(signature).decode("ascii")

    out_dir = REPO_ROOT / "metadata"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "metadata-v1.json").write_bytes(metadata_bytes)
    (out_dir / "metadata-v1.json.sig").write_text(sig_b64)

    pub_hex = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()
    print(f"✓ 元数据已签名并写入 metadata/")
    print(f"  公钥: {pub_hex}")
    print(f"  生成时间: {metadata['generatedAt']}")


if __name__ == "__main__":
    main()
