# Contributing

感谢关注 Smallink。请让改动保持边界清楚，并同步更新受影响的产品、技术与测试文档。

## 开发流程

1. 从 `main` 创建短生命周期分支。
2. 不提交真实对话、数据库导出、凭据、绝对个人路径、构建目录或安装包。
3. 更新与行为变化对应的 PRD 和技术文档。
4. 提交前运行服务端、桌面端和端到端验证。

```bash
python -m pip install -e ".[messaging,dev]"
pytest tests -q

cd surfaces/gui
npm ci
npm test
npm run build
npm run e2e

cargo check --manifest-path surfaces/gui/src-tauri/Cargo.toml
```

## Pull Request

PR 需要说明目标、行为变化、验证方式和隐私影响。新增连接器、智能体、记忆写入或工具能力必须遵循既有边界，并保留来源追溯与权限控制。

## Contributor Agreement

项目计划保留双重授权和未来商业许可能力，因此在合并第一份外部实质代码贡献前会启用个人与企业 CLA。CLA 尚未启用期间，欢迎提交 Issue、设计讨论和用于评审的草稿 PR，但维护者不会合并实质代码贡献。
