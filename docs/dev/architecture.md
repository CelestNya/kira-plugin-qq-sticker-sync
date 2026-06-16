# 架构设计

## 类结构

```
QQStickerSyncPlugin (BasePlugin)
│
├─ 状态字段
│   ├─ _sync_task      → 后台同步循环的 asyncio.Task
│   ├─ _http_client    → httpx.AsyncClient (用于下载贴纸图片)
│   ├─ _napcat_client  → 缓存的 NapCatWebSocketClient 引用
│   └─ _syncing        → 同步锁，防止重复触发
│
├─ 生命周期
│   ├─ initialize()    → 读取配置，创建 HTTP 客户端，启动同步循环
│   └─ terminate()     → 取消任务，关闭 HTTP 客户端
│
├─ 客户端发现
│   ├─ _find_napcat_client()  → 遍历适配器查找 QQAdapter
│   └─ _wait_for_client()     → 轮询等待 NapCat 登录就绪
│
├─ 同步逻辑
│   ├─ _sync_loop()             → 后台无限循环
│   ├─ _do_sync()               → 单次同步入口
│   └─ _sync_once(client)       → 核心同步实现
│
├─ VLM 恢复
│   ├─ _recover_pending_vlm()   → 扫描 __pending_vlm__ 贴纸，补 VLM 描述
│   └─ _vlm_describe_file()     → 共享 VLM 核心（带压缩）
│
├─ 下载与注册
│   ├─ _download_content()     → 并发下载，asyncio.gather 无限制
│   ├─ _register_content()     → 注册（placeholder desc 跳过 VLM 回调）
│   └─ _describe_sticker()     → 新 sticker VLM 描述，委托 _vlm_describe_file
│
├─ 清理
│   ├─ _cleanup_stale_db()      → 删除文件不存在的 DB 条目
│   └─ _remove_stale_stickers() → 删除已取消收藏的贴纸
│
├─ 工具方法
│   ├─ _build_cdn_url()        → 构建商城表情 CDN 300px 地址
│   ├─ _get_synced_eids()      → 从本地文件名收集已同步 e_id
│   ├─ _get_synced_hashes()    → 从本地文件名收集已同步 hash
│   ├─ _hash_from_path()       → 路径中提取 32 位 hex
│   ├─ _extract_hash()         → URL 中提取 32 位 hex
│   ├─ _extract_face_id()      → URL 中提取首个 32 位 hex
│   └─ _content_type_to_ext()  → Content-Type → 文件扩展名
│
└─ API 端点
    └─ trigger_manual_sync()   → POST /api/plugin/qq-sticker-sync/sync
```

## 关键设计决策

### 1. 双去重机制

QQ 表情有两种类型，使用不同的标识去重：

| 表情类型 | 去重标识 | 来源 | 下载源 |
|---------|---------|------|--------|
| 普通自定义表情(Custom Face) | URL 末尾 MD5 hash | 用户上传/收藏 | 原始 URL |
| 商城表情(Market Face) | e_id | QQ 商城 | CDN `raw300.gif` |

`_sync_once` 中两者分别维护 `existing_hashes` 和 `existing_eids` 两个集合。

### 2. 去重扫描基于文件系统

`_get_synced_hashes()` 和 `_get_synced_eids()` 直接扫描 `data/sticker/` 目录中的文件名，而非查询数据库。这确保了即使 DB 记录丢失，也不会重复下载。

### 3. 同步锁

`_syncing` 布尔值防止并发触发。同步循环本身是串行的，但 HTTP API (`trigger_manual_sync`) 可以异步触发另一个同步周期。锁确保在这种情况下不会重复运行。

### 4. 注册并发控制

`default-sticker` 的 `on_sticker_registered` 回调会触发 VLM 调用。如果多个 sticker 同时注册，回调会同步并发执行（无锁），导致 N 路 VLM 同时发出。

解决方案：下载和注册分离为两阶段。
1. **Phase 1** — `_download_content()`：纯下载，asyncio.gather 全并发，不触发 VLM
2. **Phase 2** — `_register_content()`：限流注册，通过 `self._register_sem` 控制同时触发 VLM 的数量（默认 3）

```python
# Phase 1: 并发下载
await asyncio.gather(*[_download_one(...) for ...])

# Phase 2: 限流注册
async def _register_one(item):
    async with self._register_sem:
        return await self._register_content(item)
await asyncio.gather(*[_register_one(item) for item in download_results])
```

### 5. 幂等性

每次同步都是"全量对比 → 增量下载"。不会因重复运行而导致数据不一致。本地已有的贴纸不会被重新下载。
