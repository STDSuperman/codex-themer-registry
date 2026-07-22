#!/usr/bin/env python3
"""
聚合源清单、授信列表与精选，生成签名元数据。

用法：
    SIGNING_KEY_HEX=<私钥hex> python3 scripts/sign-metadata.py
"""

import json
import base64
import os
import sys
import datetime
import tempfile
from pathlib import Path

from metadata_bundle import write_bundle

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
except ImportError:
    print("需要安装 cryptography==46.0.7", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent


def main():
    key_hex = os.environ.get("SIGNING_KEY_HEX")
    if not key_hex or len(key_hex) != 64 or any(char not in "0123456789abcdefABCDEF" for char in key_hex):
        print("错误：请设置环境变量 SIGNING_KEY_HEX（32 字节私钥的 hex 编码）", file=sys.stderr)
        sys.exit(1)

    try:
        private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key_hex))
    except ValueError as error:
        print(f"错误：索引私钥不可用：{error}", file=sys.stderr)
        sys.exit(1)

    public_hex = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()
    expected_public_hex = (REPO_ROOT / "index-public-key.txt").read_text(encoding="utf-8").strip().lower()
    if public_hex != expected_public_hex:
        print(
            "错误：索引私钥导出的公钥与 index-public-key.txt 不一致，拒绝生成客户端无法验证的目录",
            file=sys.stderr,
        )
        sys.exit(1)

    def atomic_write(path: Path, content: bytes):
        path.parent.mkdir(exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

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
    atomic_write(out_dir / "metadata-v1.json", metadata_bytes)
    atomic_write(out_dir / "metadata-v1.json.sig", sig_b64.encode("ascii"))
    write_bundle(REPO_ROOT)

    print(f"✓ 元数据已签名并写入 metadata/，Release 单文件镜像已同步生成")
    print(f"  公钥: {public_hex}")
    print(f"  生成时间: {metadata['generatedAt']}")


if __name__ == "__main__":
    main()
