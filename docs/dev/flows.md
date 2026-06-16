# 核心流程

## 同步循环 (_sync_once)

这是插件最核心的方法，按顺序执行以下步骤：

### Step 1: 清理 DB 孤岛

```python
await self._cleanup_stale_db()
```

遍历 `sticker_mgr.sticker_dict` 中所有 `qqsync_` 前缀的贴纸：
- 文件已从磁盘删除 → 删除 DB 记录（不删文件）
- 路径重复 → 保留第一个，删除后续

### Step 2: 获取表情列表

```python
resp = await client.send_action("fetch_custom_face", {})
```

返回 URL 列表，每个 URL 包含 32 位 hex 片段。

### Step 3: 获取表情元数据

```python
detail = await client.send_action("fetch_custom_face_detail", {"faceId": faceId})
```

只需要传入任一 faceId 即可获取所有表情的详细信息，包括 `isMarkFace`、`epId`、`eId`。

此步骤失败不影响主流程（降级：所有表情按普通表情处理）。

### Step 4: 筛选新表情

遍历 URL 列表，对每个 URL：
1. 提取 url_hash
2. 查找对应的元数据
3. 分支判断：
   - 商城表情且有关联 e_id → 按 e_id 去重
   - 普通表情 → 按 url_hash 去重
4. 未去重的加入 `pending` 队列

### Step 5: 下载 & 注册

逐一下载 `pending` 队列中的表情：

```python
for url, url_hash, meta in pending:
    await self._download_and_register(url, url_hash, meta)
```

下载后调用 `sticker_mgr.add_sticker()` 注册。已注册的 hash/e_id 加入 `existing` 集合，避免 `auto_delete` 误删。

### Step 6: 自动删除（可选）

```python
if self.auto_delete:
    await self._remove_stale_stickers(current_hashes, current_eids)
```

对比本次同步得到的完整集合和本地已有文件，删除不在集合中的 `qqsync_` 文件。

## NapCat 客户端发现

```python
def _find_napcat_client(self):
    """遍历所有适配器，找到 QQ 适配器 → 返回 NapCatWebSocketClient"""
    adapters = self.ctx.adapter_mgr.get_adapters()
    for name, adapter in adapters.items():
        if not isinstance(adapter, IMAdapter):
            continue
        info = getattr(adapter, "info", None)
        if info and info.platform.lower() == "qq":
            client = adapter.get_client()
            if client is not None:
                return client
    return None
```

通过 KiraAI 的 `adapter_mgr` 遍历已注册适配器，找到 `platform == "qq"` 的 `IMAdapter` 实例，获取其底层 WebSocket 客户端。

## URL hash 提取

```python
@staticmethod
def _extract_hash(url: str) -> Optional[str]:
    """提取 URL 中最后一个 32 位 hex 段作为内容指纹"""
    matches = re.findall(r"([a-fA-F0-9]{32})", url)
    return matches[-1].lower() if matches else None
```

QQ 表情 URL 格式：
```
.../2859445368_0_0_1_<上段>_<序号>_<hash>/0   ← 商城表情
.../2859445368_0_0_0_<上段>_0_0/0              ← 普通表情
```

取最后一段作为 hash。此 hash 是内容的 MD5 指纹，相同的表情图片 hash 相同。

## 文件名规范

所有本插件下载的贴纸文件名均以 `qqsync_` 前缀标识：

```
普通表情: qqsync_{url_hash}.{ext}
商城表情: qqsync_{e_id}.{ext}
```

此前缀用于：
- `_cleanup_stale_db()` 识别哪些贴纸由本插件管理
- `_remove_stale_stickers()` 筛选需清理的贴纸
- `_get_synced_hashes()` / `_get_synced_eids()` 扫描已同步集合
