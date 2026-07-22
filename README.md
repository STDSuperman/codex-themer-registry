# Codex Themer Registry

Codex Themer 官方主题注册表，承担官方主题源与社区授信元数据两个角色。

## 结构

```text
├── .github/workflows/
│   └── publish-official-theme.yml  # 官方主题上架事务
├── codex-themer-source.json   # 官方主题源清单
├── trusted-sources.json       # 授信第三方主题源列表
├── featured.json              # 官方精选
├── index-public-key.txt        # 客户端内置的索引验签公钥
├── metadata/
│   ├── metadata-v1.json       # 签名聚合元数据（客户端消费入口）
│   ├── metadata-v1.json.sig   # Ed25519 签名（base64）
│   └── metadata-v1.bundle.json # codeload 入口使用的单文件签名信封
└── scripts/
    ├── stage-official-theme.py   # 本机预检、创建 draft Release、触发 CI
    ├── update-official-theme.py  # 确定性更新源清单
    ├── sign-metadata.py          # 聚合并签名官方元数据
    └── test_registry.py          # registry 契约测试
```

## 发布官方主题

前提：

- Codex Themer 与本仓库是同级目录；
- 当前 Codex Themer revision 已推送到 GitHub；
- `gh auth status` 成功，且维护者对本仓库有 Release 与 Actions 权限；
- 仓库 Actions secret `INDEX_SIGNING_KEY_HEX`（推荐）或兼容旧名 `SIGNING_KEY_HEX` 是 32 字节 Ed25519 私钥 hex，导出公钥必须等于 `index-public-key.txt`；两者同时存在时只使用新名。
- Codex Themer 私有仓库登记一把只读 Deploy Key；对应私钥仅保存为本仓库 Actions secret `THEMER_DEPLOY_KEY`。发布 workflow 用它检出输入 SHA，且检出后不持久化凭据。

先从 Codex Themer 导出规范命名的 `.ctpack`，再运行：

```bash
python3 scripts/stage-official-theme.py /absolute/path/theme-name-1.0.0.ctpack --version 1.0.0 --featured
```

脚本会用 Codex Themer 同一源码里的 `ctheme-check` 把普通导出的 `local/<name>` 分享包规范化为 `stdsuperman/<name>`，按需用 `--name` / `--version` 覆盖发布坐标，并从主题预览派生独立卡片图。随后它创建只含规范化分享包与卡片图的 draft Release，并把精确的 Codex Themer commit SHA 交给 `publish-official-theme` workflow。CI 会再次预检，且严格按以下顺序提交：

CI 在 Ubuntu 构建与客户端同一 Rust crate，因此 workflow 显式安装与主项目 Linux 发布任务相同的 Tauri 原生依赖；发布复验不依赖 runner 的偶然预装状态，也不使用一套降级验证器。

1. 校验 draft Release 的 `.ctpack` 与卡片图；
2. 确定性更新源清单并生成签名元数据；
3. 运行 registry 契约测试；
4. 把 Release 从 draft 改为公开；
5. 提交并推送源清单、精选、签名元数据与单文件签名信封。

因此提交失败最多留下一个尚未被目录引用的 Release；重新触发同一版本是幂等的，已发布版本的哈希、体积和 Release 坐标不能改写。

仅做本机预检、不创建任何远端内容：

```bash
python3 scripts/stage-official-theme.py /absolute/path/theme-name-1.0.0.ctpack --dry-run
```

## 本地验证与签名

registry 契约测试只依赖 Python 标准库；签名验证与签名脚本依赖固定版本 `cryptography`：

```bash
python3 -m pip install cryptography==46.0.7
python3 -m unittest discover -s scripts -p 'test_*.py'
```

只有索引密钥维护者才运行签名：

```bash
SIGNING_KEY_HEX=<私钥> python3 scripts/sign-metadata.py
```

脚本会在写入前核对派生公钥；公钥不等于 `index-public-key.txt` 时直接失败。

## 消费方式

Codex Themer 客户端只从本仓库 `main` 分支的 GitHub codeload 归档读取固定路径 `metadata/metadata-v1.bundle.json`，再用内置公钥验证信封中的元数据原文。归档只是传输容器，不是信任根；真实性只来自 Ed25519 签名。网络失败时客户端只回退最近一次验签通过的本机目录，不切换到第二套远程协议。客户端启动后只默认同步签名目录；主题包和预览图只在用户浏览或明确安装时下载，安装后不会自动应用。
