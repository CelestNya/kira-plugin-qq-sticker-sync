# 概述

## 功能定位

QQ 表情同步插件是 KiraAI 的辅助插件，不直接处理消息。它负责将 QQ 客户端的收藏表情（Custom Face）拉取到 KiraAI 本地，供 `default-sticker` 插件拾取和描述。

## 与 default-sticker 的关系

| 插件 | 职责 |
|------|------|
| `qq-sticker-sync` | 从 QQ 服务器下载收藏表情到本地磁盘 |
| `default-sticker` | 扫描本地磁盘文件，调用 VLM 生成描述，注入 sticker tag |

两者通过 `StickerManager` 联动：

1. `qq-sticker-sync` 调用 `sticker_mgr.add_sticker(file_bytes, filename)` 注册新贴纸
2. `add_sticker` 内部触发 `on_sticker_registered` 回调
3. `default-sticker` 订阅了该回调，自动调用 VLM 描述
4. 描述完成后写入数据库，贴纸即可在聊天中使用

## 前置条件

- KiraAI 主程序（版本 >= 2.0）
- QQ 适配器已启用（NaCat WebSocket 连接）
- NapCat（或其他 OneBot 实现）正在运行
- Python 包：`httpx`

## 能力边界

**能做：**
- 双向同步 QQ 收藏表情 → KiraAI 本地贴纸库
- 区分普通自定义表情（Custom Face）和商城表情（Market Face）
- 商城表情使用 CDN 300px 高画质源
- 自动清理已取消收藏的过期本地贴纸
- 提供 HTTP API 手动触发同步

**不能做：**
- 反向同步（KiraAI → QQ）
- 删除 QQ 服务端的收藏表情
- 贴纸的 VLM 描述生成（由 default-sticker 负责）
- 处理非 QQ 适配器（如 Telegram、 Discord）
