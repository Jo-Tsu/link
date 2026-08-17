# Smallink 品牌资产

## 文件

- `smallink-wordmark-source.png`：用户确认的完整 Smallink 字标原稿，仅作为品牌源文件。
- `smallink-mark.png`：从字标左侧提取的透明背景独立图形，尺寸为 1024 x 1024。

## 使用规则

- macOS App、Dock、安装包、菜单栏和产品内小尺寸 Logo 只使用 `smallink-mark.png`。
- 产品名称统一显示为 `Smallink`，不要把完整字标缩进小图标容器。
- macOS DMG 安装背景标题固定为 `Install Smallink`，副标题固定为 `Drag the app onto the Applications folder`；1x、2x 与 TIFF 版本必须同步更新。
- 图形周围保留透明留白，不增加底板、阴影、描边或额外文字。
- 产品视觉统一使用深邃夜蓝 `#00224D`、科技蓝 `#00529B` 和节点青蓝 `#00A8E8`。
- 完整 UI 规则见 `docs/smallink-ui-design-system.md`。

## 兼容边界

本次更新只改变对外品牌和视觉资产。现有 `link` Python 包、`X-Link-Token`、
`~/.config/link/`、`link.db` 与 `.link/` 属于运行兼容标识，未经数据迁移方案不得直接改名。新建会话产物默认使用 `~/Smallink/`，已有用户设置的 `~/Link/` 路径继续有效。
