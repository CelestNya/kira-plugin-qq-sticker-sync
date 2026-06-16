# 工作流程

## 数据流

```
KiraAI 启动
  │
  ├─ StickerManager.init() → 从 DB 加载已有贴纸
  │
  ├─ QQStickerSyncPlugin.initialize()
  │    ├─ 创建 httpx.AsyncClient
  │    └─ 创建 _sync_loop 后台任务
  │
  └─ [等待 NapCat 连接...]
       │
       ▼ (login_success_event 触发)
       │
  ── 同步循环 ──────────────────────────────────
  │                                              │
  ▼ 每 sync_interval_sec 秒                      │
  │                                              │
  ├─ 0. _recover_pending_vlm()                  │
  │    扫描 __pending_vlm__ 贴纸 → VLM 补描述   │
  │                                              │
  ├─ 1. _cleanup_stale_db()                     │
  │    清理文件已删除的 DB 条目                   │
  │                                              │
  ├─ 2. fetch_custom_face (NapCat API)           │
  │    获取所有收藏表情的 URL 列表                │
  │                                              │
  ├─ 3. fetch_custom_face_detail (NapCat API)    │
  │    获取元数据：isMarkFace / epId / eId       │
  │                                              │
  ├─ 4. 对比本地文件，筛选新表情                  │
  │    ├─ 普通表情 → URL hash 去重               │
  │    └─ 商城表情 → e_id 去重                   │
  │                                              │
  ├─ 5. 逐一下载并注册                           │
  │    ├─ 商城表情 → CDN 300px 源                │
  │    └─ 普通表情 → 原始 URL                    │
  │    └─ sticker_mgr.add_sticker()              │
  │         └─→ default-sticker VLM 描述         │
  │                                              │
  └─ 6. 自动删除已取消收藏的本地贴纸              │
       (auto_delete=true 时)                     │
       │                                         │
       ▼── 休眠 interval_sec ──→ 回到开头         │
```

## NapCat API 调用

### fetch_custom_face (获取表情 URL 列表)

```json
// 请求
{"action": "fetch_custom_face", "params": {}}
// 响应
{"status": "ok", "data": [
    "https://gxh.vip.qq.com/.../2859445368_0_0_0_ABC123_0_0/0",
    "https://.../2859445368_0_0_1_DEF456_1_GHI789/0"
]}
```

### fetch_custom_face_detail (获取元数据)

```json
// 请求
{"action": "fetch_custom_face_detail", "params": {"faceId": "ABC123"}}
// 响应
{"status": "ok", "data": [
    {"url": "https://.../2859445368_0_0_0_ABC123_0_0/0",
     "isMarkFace": false,
     "epId": 0,
     "eId": ""},
    {"url": "https://.../2859445368_0_0_1_DEF456_1_GHI789/0",
     "isMarkFace": true,
     "epId": 12345,
     "eId": "GHI789"}
]}
```

## URL 解析

表情 URL 包含多个 32 位十六进制段，插件从中提取关键标识：

```
2859445368_0_0_1_<upper32>_<num>_<hash32>/0
                  ↑ epId      ↑ url_hash (MD5)
```

- **url_hash**: URL 末尾的 32 位 hex，用于普通表情去重
- **e_id**: 商城表情的唯一标识，用于去重和 CDN 构建
- **isMarkFace**: 区分普通表情和商城表情，商城表情使用 CDN 300px 高质量源
