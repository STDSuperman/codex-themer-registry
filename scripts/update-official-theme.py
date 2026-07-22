#!/usr/bin/env python3
"""用 ctheme-check 报告确定性、不可变地更新官方主题源清单。"""

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NAMESPACE = "stdsuperman"
MAX_PACK_BYTES = 40 * 1024 * 1024
MAX_CARD_BYTES = 512 * 1024
REPORT_KEYS = {
    "reportSchemaVersion", "distributionId", "namespace", "name", "version",
    "displayName", "description", "tags", "license", "minSchemaVersion",
    "releaseTag", "asset", "size", "sha256", "cardAsset", "cardSize",
    "cardSha256", "packContentHash", "publishedAt",
}
THEME_KEYS = {"name", "displayName", "description", "tags", "license", "versions"}
VERSION_KEYS = {
    "version", "minSchemaVersion", "releaseTag", "asset", "size", "sha256",
    "publishedAt", "yanked", "yankReason",
}
NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
SEMVER_RE = re.compile(r"^(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,199}$")


class RegistryError(ValueError):
    pass


def semver(value):
    match = SEMVER_RE.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise RegistryError(f"版本必须是严格 semver：{value!r}")
    return tuple(int(part) for part in match.groups())


def require(condition, message):
    if not condition:
        raise RegistryError(message)


def validate_report(report):
    require(isinstance(report, dict) and set(report) == REPORT_KEYS, "ctheme-check 报告字段不完整或含未知字段")
    require(type(report["reportSchemaVersion"]) is int and report["reportSchemaVersion"] == 1, "不支持的 ctheme-check 报告版本")
    require(report["namespace"] == NAMESPACE, f"官方主题 namespace 必须是 {NAMESPACE}")
    require(isinstance(report["name"], str) and NAME_RE.fullmatch(report["name"]), "主题名无效")
    require(report["distributionId"] == f'{NAMESPACE}/{report["name"]}', "分发 ID 与 namespace/name 不一致")
    semver(report["version"])
    name = report["name"]
    version = report["version"]
    require(report["releaseTag"] == f"{name}-v{version}", "releaseTag 不符合不可变命名约定")
    require(report["asset"] == f"{name}-{version}.ctpack", "分享包 asset 名不符合约定")
    require(report["cardAsset"] == f"{name}-{version}-card.webp", "卡片 asset 名不符合约定")
    require(type(report["size"]) is int and 0 < report["size"] <= MAX_PACK_BYTES, "分享包体积无效")
    require(type(report["cardSize"]) is int and 0 < report["cardSize"] <= MAX_CARD_BYTES, "卡片图体积无效")
    require(type(report["minSchemaVersion"]) is int and report["minSchemaVersion"] > 0, "minSchemaVersion 无效")
    require(isinstance(report["displayName"], str) and 0 < len(report["displayName"].strip()) <= 80, "展示名无效")
    require(isinstance(report["description"], str) and len(report["description"]) <= 2000, "描述必须是不超过 2000 字符的字符串")
    require(isinstance(report["license"], str) and 0 < len(report["license"].strip()) <= 64, "license 无效")
    require(isinstance(report["tags"], list) and len(report["tags"]) <= 16 and all(isinstance(tag, str) and 0 < len(tag) <= 40 for tag in report["tags"]), "tags 无效")
    for field in ("sha256", "cardSha256", "packContentHash"):
        require(isinstance(report[field], str) and SHA_RE.fullmatch(report[field]), f"{field} 无效")
    require(isinstance(report["publishedAt"], str) and report["publishedAt"].endswith("Z"), "publishedAt 必须是 UTC RFC3339")
    try:
        datetime.fromisoformat(report["publishedAt"].replace("Z", "+00:00"))
    except ValueError as error:
        raise RegistryError("publishedAt 不是有效 RFC3339") from error


def verify_asset(assets_dir, name, expected_size, expected_sha):
    root = assets_dir.resolve()
    candidate = root / name
    require(candidate.parent == root, f"asset 路径越界：{name}")
    try:
        info = candidate.lstat()
    except FileNotFoundError as error:
        raise RegistryError(f"Release 缺少 asset：{name}") from error
    require(stat.S_ISREG(info.st_mode) and not candidate.is_symlink(), f"asset 必须是普通文件：{name}")
    content = candidate.read_bytes()
    require(len(content) == expected_size, f"asset 体积与预检报告不一致：{name}")
    require(hashlib.sha256(content).hexdigest() == expected_sha, f"asset sha256 与预检报告不一致：{name}")


def validate_source(source):
    require(isinstance(source, dict) and set(source) == {"sourceSchemaVersion", "namespace", "themes"}, "源清单顶层字段无效")
    require(type(source["sourceSchemaVersion"]) is int and source["sourceSchemaVersion"] == 1 and source["namespace"] == NAMESPACE, "源清单版本或 namespace 无效")
    themes = source["themes"]
    require(isinstance(themes, list) and len(themes) <= 64, "源清单主题数量无效")
    seen_names = set()
    for theme in themes:
        require(isinstance(theme, dict) and set(theme) == THEME_KEYS, "主题条目字段无效")
        name = theme["name"]
        require(isinstance(name, str) and NAME_RE.fullmatch(name) and name not in seen_names, f"主题名无效或重复：{name!r}")
        seen_names.add(name)
        require(isinstance(theme["displayName"], str) and 0 < len(theme["displayName"].strip()) <= 80, f"主题 {name} 展示名无效")
        require(isinstance(theme["description"], str) and len(theme["description"]) <= 2000, f"主题 {name} 描述无效")
        require(isinstance(theme["tags"], list) and len(theme["tags"]) <= 16 and all(isinstance(tag, str) and 0 < len(tag) <= 40 for tag in theme["tags"]), f"主题 {name} tags 无效")
        require(isinstance(theme["license"], str) and 0 < len(theme["license"].strip()) <= 64, f"主题 {name} license 无效")
        versions = theme["versions"]
        require(isinstance(versions, list) and 0 < len(versions) <= 100, f"主题 {name} 版本数量无效")
        seen_versions = set()
        for version in versions:
            require(isinstance(version, dict) and set(version) == VERSION_KEYS, f"主题 {name} 版本字段无效")
            parsed = semver(version["version"])
            require(parsed not in seen_versions, f"主题 {name} 版本重复：{version['version']}")
            seen_versions.add(parsed)
            require(type(version["minSchemaVersion"]) is int and version["minSchemaVersion"] > 0, "minSchemaVersion 无效")
            require(isinstance(version["releaseTag"], str) and COMPONENT_RE.fullmatch(version["releaseTag"]), "releaseTag 无效")
            require(isinstance(version["asset"], str) and COMPONENT_RE.fullmatch(version["asset"]), "asset 无效")
            require(type(version["size"]) is int and 0 < version["size"] <= MAX_PACK_BYTES, "版本体积无效")
            require(isinstance(version["sha256"], str) and SHA_RE.fullmatch(version["sha256"]), "版本 sha256 无效")
            require(isinstance(version["publishedAt"], str) and version["publishedAt"].endswith("Z"), "publishedAt 无效")
            require(type(version["yanked"]) is bool, "yanked 必须是布尔值")
            require(version["yankReason"] is None or isinstance(version["yankReason"], str), "yankReason 无效")


def atomic_write_json(path, value):
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_report(repo_root, report, assets_dir, featured=False):
    validate_report(report)
    verify_asset(assets_dir, report["asset"], report["size"], report["sha256"])
    verify_asset(assets_dir, report["cardAsset"], report["cardSize"], report["cardSha256"])

    source_path = repo_root / "codex-themer-source.json"
    featured_path = repo_root / "featured.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    featured_ids = json.loads(featured_path.read_text(encoding="utf-8"))
    validate_source(source)
    require(isinstance(featured_ids, list) and all(isinstance(item, str) for item in featured_ids) and len(featured_ids) == len(set(featured_ids)), "featured.json 必须是无重复字符串数组")

    version_entry = {
        "version": report["version"],
        "minSchemaVersion": report["minSchemaVersion"],
        "releaseTag": report["releaseTag"],
        "asset": report["asset"],
        "size": report["size"],
        "sha256": report["sha256"],
        "publishedAt": report["publishedAt"],
        "yanked": False,
        "yankReason": None,
    }
    theme_fields = {
        "name": report["name"],
        "displayName": report["displayName"],
        "description": report["description"],
        "tags": report["tags"],
        "license": report["license"],
    }
    theme = next((item for item in source["themes"] if item["name"] == report["name"]), None)
    changed = False
    if theme is None:
        source["themes"].append({**theme_fields, "versions": [version_entry]})
        changed = True
    else:
        existing = next((item for item in theme["versions"] if item["version"] == report["version"]), None)
        if existing is not None:
            require(existing == version_entry, "已发布版本不可改写；版本坐标相同但制品 pin 不一致")
            require(all(theme[key] == value for key, value in theme_fields.items()), "幂等重试不能改写既有主题元数据")
        else:
            latest = max(semver(item["version"]) for item in theme["versions"])
            require(semver(report["version"]) > latest, "新版本必须严格高于当前最高版本")
            theme.update(theme_fields)
            theme["versions"].append(version_entry)
            theme["versions"].sort(key=lambda item: semver(item["version"]))
            changed = True

    source["themes"].sort(key=lambda item: item["name"])
    distribution_id = report["distributionId"]
    if featured and distribution_id not in featured_ids:
        featured_ids.append(distribution_id)
        featured_ids.sort()
        changed = True
    validate_source(source)
    known_ids = {f'{NAMESPACE}/{item["name"]}' for item in source["themes"]}
    require(set(featured_ids).issubset(known_ids), "featured 含未收录或非法的分发 ID")

    if changed:
        atomic_write_json(source_path, source)
        atomic_write_json(featured_path, featured_ids)
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--assets-dir", required=True, type=Path)
    parser.add_argument("--expected-release-tag")
    parser.add_argument("--featured", action="store_true")
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        if args.expected_release_tag:
            require(report.get("releaseTag") == args.expected_release_tag, "workflow 输入的 releaseTag 与分享包不一致")
        changed = apply_report(REPO_ROOT, report, args.assets_dir, args.featured)
    except (OSError, json.JSONDecodeError, RegistryError) as error:
        parser.exit(1, f"官方主题目录更新失败：{error}\n")
    print("✓ 官方主题目录已更新" if changed else "✓ 目录已经包含完全相同的版本，无需改写")


if __name__ == "__main__":
    main()
