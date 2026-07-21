# Codex Themer Registry

Codex Themer 官方主题注册表，承担官方主题源与社区授信元数据两个角色。

## 结构

```
├── codex-themer-source.json   # 官方主题源清单
├── trusted-sources.json       # 授信第三方主题源列表
├── featured.json              # 官方精选
├── metadata/
│   ├── metadata-v1.json       # 签名聚合元数据（客户端消费入口）
│   └── metadata-v1.json.sig   # Ed25519 签名（base64）
└── scripts/
    └── sign-metadata.py       # 本地签名脚本
```

## 本地签名

```bash
SIGNING_KEY_HEX=<私钥> python3 scripts/sign-metadata.py
```

## 消费方式

Codex Themer 客户端从本仓库默认分支拉取 `metadata/metadata-v1.json` 与 `.sig`，验签后消费。
