# link 本地运行

link 当前只包含数据接入与独立网页采集。当前版本是单用户开发预览版，只允许在受信任电脑上通过 `127.0.0.1` 使用。

首次运行可从示例生成本地配置：

```bash
cp .env.example .env
```

```bash
npm run stable:up
```

服务地址：`http://127.0.0.1:41737/`。

Docker Compose 启动：

- `link-app`：数据接入页面和 API。
- `postgres`：`sensory_records` 与连接器同步记录。
- `crawler-api`：独立 Scrapling 网页采集器。

平台容器不挂载 `~/.codex`。Codex 数据由安装在本机的 LinkAgent 读取，用户在平台创建配对码完成设备配对后，通过 Codex 连接器下发同步指令。

```bash
npm run stable:down
```

停止本地服务。当前不包含公网认证、多租户、AI Worker、治理任务或记忆服务，不得直接暴露到公网。
