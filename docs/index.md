# QQ Sticker Sync

**KiraAI QQ 表情同步插件** — 通过 NapCat API 自动同步 QQ 收藏的表情包到本地贴纸库。

## 解决的问题

KiraAI 内置 `default-sticker` 插件只扫描本地文件系统中的图片文件。QQ 收藏的表情包（Custom Face）存储在腾讯服务器上，需要主动拉取。

本插件桥接了 NapCat WebSocket API 和 KiraAI 贴纸系统，让 QQ 收藏的表情自动出现在 KiraAI 贴纸库中，可直接用于聊天回复。

## 工作原理

```
QQ 收藏表情 → NapCat API → 下载图片 → StickerManager → default-sticker VLM 描述
                                                                       ↓
                                                             聊天中可用
```

1. 后台定时通过 NapCat WebSocket 调用 `fetch_custom_face` 获取表情列表
2. 对比本地已有贴纸，筛选需要下载的新表情
3. 通过 `httpx` 下载图片文件
4. 注册到 KiraAI `StickerManager`，存入 `data/sticker/` 目录
5. `default-sticker` 插件的扫描循环自动拾取新文件并调用 VLM 生成文字描述
6. 可选自动清理 QQ 收藏中已取消的过期本地贴纸

## 快速开始

将插件目录放入 KiraAI `data/plugins/`，在 WebUI 中启用即可。依赖仅 `httpx`。
