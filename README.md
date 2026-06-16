# QQ Sticker Sync (QQ 表情同步插件)

通过 NapCat API 自动同步 QQ 收藏的表情包到 KiraAI 本地贴纸库。

## 工作原理

与 KiraAI 内置 `default-sticker` 插件配合使用：

1. 本插件通过 NapCat WebSocket 调用 `fetch_custom_face` 获取 QQ 收藏表情列表
2. 下载新表情到 KiraAI `data/sticker/` 目录
3. `default-sticker` 的扫描循环自动拾取新文件，调用 VLM 生成描述
4. 支持自动清理已取消收藏的过期本地表情

## 配置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `sync_interval_sec` | integer | 1800 | 同步间隔（秒） |
| `auto_delete` | switch | false | 自动删除已取消收藏的表情 |

## 依赖

- KiraAI 主程序
- QQ 适配器（NapCat WebSocket 连接）
- `httpx`
