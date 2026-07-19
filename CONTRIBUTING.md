# Contributing

感谢关注 Link。当前项目处于数据接入闭环的开发预览阶段，请让改动保持小而清晰，不要在同一提交中加入数据治理、记忆、知识库或多租户实现。

## 开发流程

1. 从 `main` 创建短生命周期分支。
2. 不提交真实 Codex 数据、数据库导出、凭据、绝对个人路径或安装包。
3. 更新与行为变化对应的 PRD 和技术文档。
4. 提交前运行平台与 LinkAgent 验证。

```bash
npm ci
npm run lint
npm run build
npm --prefix link-agent-client ci
npm --prefix link-agent-client run build
cd link-agent-client/src-tauri && cargo test
```

## Pull Request

PR 需要说明目标、行为变化、验证方式和隐私影响。新增连接器必须写入统一原始池并保留来源追溯，不得绕过接入协议写入后续数据资产。

## Contributor Agreement

项目计划保留双重授权和未来商业许可能力，因此在合并第一份外部实质代码贡献前会启用个人与企业 CLA。CLA 尚未启用期间，欢迎提交 Issue、设计讨论和用于评审的草稿 PR，但维护者不会合并实质代码贡献。
