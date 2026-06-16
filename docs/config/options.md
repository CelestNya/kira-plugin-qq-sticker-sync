# 配置选项

在 KiraAI WebUI 插件页面中配置。

## sync_interval_sec

- **类型**: `integer`
- **默认**: `1800`（30 分钟）
- **范围**: 60 及以上

同步间隔。插件每隔此秒数检查一次 QQ 收藏表情是否有更新。

QQ 收藏表情不常变动，建议保持默认值 1800（30 分钟）以减少 NapCat API 调用次数。

## download_concurrency

- **类型**: `integer`
- **默认**: `5`
- **范围**: 1 及以上

下载并发数。控制同时从 QQ CDN 下载贴纸图片的 HTTP 请求数。

下载阶段是纯网络 I/O，CDN 抗并发能力强。默认 5 在大多数网络环境下能充分利用带宽。

## vlm_concurrency

- **类型**: `integer`
- **默认**: `3`
- **范围**: 1 及以上

VLM 描述并发数。控制同时调用 VLM 生成贴纸描述的最大并发量。

下载注册完成后，插件自带 VLM 描述阶段。`StickerManager.register_sticker` 用 `asyncio.create_task` 触发回调，因此 `default-sticker` 的 VLM 回调不受外部控制。本插件绕过该机制，用 placeholder desc 跳过默认回调，自行管理 VLM 调用并受 Semaphore 约束。

- **3（默认）**：同时描述 3 张，平滑友好
- **1**：完全串行，最慢但无限流风险
- **5**：对高额度 VLM API 可适当调高

## vlm_compress_enabled

- **类型**: `switch`
- **默认**: `false`

VLM 描述前将贴纸图片转为 JPEG 有损压缩后再上传。

下载时保存原始文件（原格式、原画质），确保本地贴纸库始终持有无损源文件。只有发送给 VLM 的 payload 经过压缩，减小上传带宽和延迟。

- **关闭（默认）**：原始文件直接送 VLM，画质无损
- **开启**：PIL 读取 → RGBA 转 RGB → JPEG(quality) → base64 → VLM

## vlm_compress_quality

- **类型**: `integer`
- **默认**: `85`
- **范围**: 10–100

JPEG 压缩质量，仅在 `vlm_compress_enabled` 开启时生效。

- **100**: 最高画质，文件仍可能因 RGBA→RGB 转换而缩小
- **85**: 画质与文件大小的良好平衡
- **50**: 文件小，有明显压缩痕迹

## auto_delete

- **类型**: `switch`
- **默认**: `false`

自动删除本地存储中已被取消收藏的 QQ 表情。

- **关闭（默认）**：仅新增，不删除。取消收藏的表情保留在本地。
- **开启**：每次同步时，检查本地 `qqsync_` 前缀的贴纸是否仍在 QQ 收藏中，
  不在的则从本地删除文件和数据库记录。

::: warning 注意
开启后，所有不在 QQ 收藏表情列表中的 `qqsync_` 前缀本地贴纸都会被删除，包括曾经通过本插件同步但随后在 QQ 中取消收藏的、以及手动重命名或复制进来的 `qqsync_` 文件。如需保留某些贴纸，请在开启前备份或修改文件名去掉 `qqsync_` 前缀。
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
