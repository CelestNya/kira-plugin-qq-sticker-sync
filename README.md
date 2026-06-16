# QQ Sticker Sync (QQ 表情同步插件)

通过 NapCat API 自动同步 QQ 收藏的表情包到 KiraAI 本地贴纸库。

## 工作原理

1. 定时通过 NapCat WebSocket 调用 `fetch_custom_face` 获取 QQ 收藏表情列表
2. **并发下载**新表情到 `data/sticker/` 目录（原格式保存）
3. 注册到 `StickerManager`，跳过 `default-sticker` 的回调触发
4. **限流 VLM 描述** — 自行管理 VLM 并发，可选 JPEG 压缩
5. 支持自动清理已取消收藏的过期本地贴纸
6. VLM 失败自动恢复 — 每次同步自动补描述失败的贴纸

## 配置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `sync_interval_sec` | integer | 1800 | 同步间隔（秒，最小 60） |
| `download_concurrency` | integer | 5 | 下载并发数 |
| `vlm_concurrency` | integer | 3 | VLM 描述并发数 |
| `vlm_compress_enabled` | switch | false | VLM 描述前 JPEG 压缩 |
| `vlm_compress_quality` | integer | 85 | JPEG 压缩质量 (10-100) |
| `auto_delete` | switch | false | 自动删除已取消收藏的表情 |

## 数据流

```
NapCat API → 并发下载 → 注册(placeholder desc) → 限流 VLM 描述 → update desc
                                                  ↑
                                    每次同步前自动恢复 __pending_vlm__
```

## 依赖

- KiraAI 主程序
- QQ 适配器（NapCat WebSocket 连接）
- `httpx`
- `Pillow`
