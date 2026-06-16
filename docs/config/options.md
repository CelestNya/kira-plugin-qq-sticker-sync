# 配置选项

在 KiraAI WebUI 插件页面中配置。

## sync_interval_sec

- **类型**: `integer`
- **默认**: `1800`（30 分钟）
- **范围**: 60 及以上

同步间隔。插件每隔此秒数检查一次 QQ 收藏表情是否有更新。

QQ 收藏表情不常变动，建议保持默认值 1800（30 分钟）以减少 NapCat API 调用次数。

## auto_delete

- **类型**: `switch`
- **默认**: `false`

自动删除本地存储中已被取消收藏的 QQ 表情。

- **关闭（默认）**：仅新增，不删除。取消收藏的表情保留在本地。
- **开启**：每次同步时，检查本地 `qqsync_` 前缀的贴纸是否仍在 QQ 收藏中，
  不在的则从本地删除文件和数据库记录。

::: tip
首次开启时可能会有大量删除操作，后续趋于稳定。
:::

## HTTP API

插件在初始化时自动注册一个 API 端点，用于手动触发同步：

```
POST /api/plugin/qq-sticker-sync/sync
```

```json
// 正常响应
{"status": "ok", "message": "Sync triggered"}
// 同步中
{"status": "busy", "message": "Sync already in progress"}
```
