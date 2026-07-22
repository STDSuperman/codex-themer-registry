#!/usr/bin/env python3
"""把已签名的官方元数据封装为可原子读取的单文件传输包。"""

import base64
import json
import os
import tempfile
from pathlib import Path


BUNDLE_SCHEMA_VERSION = 1


def encode_bundle(metadata_bytes: bytes, signature_text: str) -> bytes:
    """保留被签名字节原文，仅为 GitHub Release 传输增加一层严格信封。"""
    signature_text = signature_text.strip()
    signature = base64.b64decode(signature_text, validate=True)
    if len(signature) != 64:
        raise ValueError("metadata signature must be 64 bytes")
    bundle = {
        "bundleSchemaVersion": BUNDLE_SCHEMA_VERSION,
        "metadataBase64": base64.b64encode(metadata_bytes).decode("ascii"),
        "signatureBase64": signature_text,
    }
    return json.dumps(bundle, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")


def atomic_write(path: Path, content: bytes) -> None:
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


def write_bundle(repo_root: Path) -> Path:
    metadata_dir = repo_root / "metadata"
    metadata_bytes = (metadata_dir / "metadata-v1.json").read_bytes()
    signature_text = (metadata_dir / "metadata-v1.json.sig").read_text(encoding="ascii")
    output = metadata_dir / "metadata-v1.bundle.json"
    atomic_write(output, encode_bundle(metadata_bytes, signature_text))
    return output


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    path = write_bundle(root)
    print(f"✓ 官方目录传输信封已写入 {path.relative_to(root)}")
