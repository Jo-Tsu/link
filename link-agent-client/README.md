# LinkAgent Client

LinkAgent 是 Link 平台的本地连接器客户端。第一期支持 macOS 菜单栏运行、设备配对、Codex 只读授权、增量同步、本地持久队列和同步结果查看。

## 开发

```bash
npm install
npm run tauri dev
```

## 验证

```bash
npm run build
cd src-tauri && cargo test
```

## 打包

```bash
npm run tauri build -- --bundles dmg
```

若 macOS Documents 目录的 provenance 属性阻止 release 归档，可把 Cargo 构建目录放在系统临时目录：

```bash
CARGO_TARGET_DIR="$TMPDIR/link-agent-target" npm run tauri build -- --bundles dmg
```

正式客户端说明见 [`../docs/link-agent-client-prd.md`](../docs/link-agent-client-prd.md)，协议与数据边界见 [`../docs/link-agent-technical-design.md`](../docs/link-agent-technical-design.md)。
