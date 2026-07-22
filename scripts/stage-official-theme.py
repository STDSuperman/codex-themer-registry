#!/usr/bin/env python3
"""本机预检官方主题，创建 draft Release 并触发 registry 发布事务。"""

import argparse
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_REPOSITORY = "STDSuperman/codex-themer-registry"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def command(arguments, cwd=None, check=True):
    result = subprocess.run(
        [str(item) for item in arguments],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"退出码 {result.returncode}"
        raise RuntimeError(f"命令失败：{' '.join(map(str, arguments))}\n{detail}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("--themer-root", type=Path, default=REPO_ROOT.parent / "codex-themer")
    parser.add_argument("--name", help="可选：覆盖导出包中的主题 slug")
    parser.add_argument("--version", help="可选：为本次官方发布指定严格 semver")
    parser.add_argument("--featured", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    pack = args.pack.expanduser().resolve()
    themer_root = args.themer_root.expanduser().resolve()
    if not pack.is_file() or pack.is_symlink():
        parser.exit(1, "分享包必须是普通文件\n")
    manifest = themer_root / "src-tauri/Cargo.toml"
    if not manifest.is_file():
        parser.exit(1, f"找不到 Codex Themer Cargo.toml：{manifest}\n")

    temporary = tempfile.TemporaryDirectory(prefix="codex-themer-release-")
    prepared_dir = Path(temporary.name)
    try:
        check_arguments = [
            "cargo", "run", "--locked", "--quiet", "--manifest-path", manifest,
            "--example", "ctheme-check", "--", "--json",
            "--prepare-namespace", "stdsuperman", "--output-dir", prepared_dir,
            "--expected-namespace", "stdsuperman",
        ]
        if args.name:
            check_arguments.extend(["--name", args.name])
        if args.version:
            check_arguments.extend(["--version", args.version])
        check_arguments.append(pack)
        checked = command(check_arguments)
        report = json.loads(checked.stdout)
        prepared_pack = prepared_dir / report["asset"]
        if not prepared_pack.is_file():
            raise RuntimeError("ctheme-check 未生成报告声明的规范化分享包")
        card_asset = report["cardAsset"]
        with zipfile.ZipFile(prepared_pack) as archive:
            names = archive.namelist()
            if names.count("preview/card.webp") != 1:
                raise RuntimeError("分享包必须只包含一个 preview/card.webp")
            card = archive.read("preview/card.webp")
        if len(card) != report["cardSize"]:
            raise RuntimeError("卡片图体积与 ctheme-check 报告不一致")
        card_path = prepared_dir / card_asset
        card_path.write_bytes(card)
    except (RuntimeError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        parser.exit(1, f"官方主题本机预检失败：{error}\n")

    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    try:
        dirty = command(["git", "status", "--porcelain"], cwd=REPO_ROOT).stdout.strip()
        if dirty:
            raise RuntimeError("registry 工作区必须干净；请先提交或撤销本地改动")
        revision = command(["git", "rev-parse", "HEAD"], cwd=themer_root).stdout.strip().lower()
        if not COMMIT_RE.fullmatch(revision):
            raise RuntimeError("无法解析 Codex Themer 精确 commit SHA")
        command(["gh", "auth", "status"])
        existing = command(
            ["gh", "release", "view", report["releaseTag"], "--repo", REGISTRY_REPOSITORY],
            check=False,
        )
        if existing.returncode == 0:
            raise RuntimeError(
                f'Release {report["releaseTag"]} 已存在；若是失败重试，请直接重新运行对应 workflow'
            )

        notes = (
            f'{report["displayName"]} v{report["version"]}\n\n'
            "此 Release 由 Codex Themer 官方主题发布流水线生成。"
        )
        command([
            "gh", "release", "create", report["releaseTag"], str(prepared_pack), str(card_path),
            "--repo", REGISTRY_REPOSITORY, "--draft", "--target", "main",
            "--title", f'{report["displayName"]} v{report["version"]}', "--notes", notes,
        ])
        command([
            "gh", "workflow", "run", "publish-official-theme.yml",
            "--repo", REGISTRY_REPOSITORY,
            "-f", f'release_tag={report["releaseTag"]}',
            "-f", f"themer_ref={revision}",
            "-f", f"featured={'true' if args.featured else 'false'}",
        ])
    except RuntimeError as error:
        parser.exit(1, f"官方主题发布准备失败：{error}\n")

    print(f'✓ 已创建 draft Release：{report["releaseTag"]}')
    print("✓ 已触发 publish-official-theme workflow；以 workflow 成功作为上架完成判据")


if __name__ == "__main__":
    main()
