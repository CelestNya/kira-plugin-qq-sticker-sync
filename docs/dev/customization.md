# 自定义与扩展

## 代码结构

```
qq-sticker-sync/
├── main.py              ← 全部插件逻辑（单文件 ~476 行）
├── __init__.py          ← 从 .main import QQStickerSyncPlugin
├── manifest.json        ← 插件元信息
├── schema.json          ← 配置 schema
├── requirements.txt     ← httpx>=0.27.0
└── docs/                ← 本文档
```

## 开发思路

### 1. 完善同步触发机制

当前 `_sync_loop` 仅在初始化时等待 NapCat 连接一次。如果运行中 NapCat 断开后又重连，同步循环仍在运行但会失败。可以考虑：

```python
def _watch_client_connection(self):
    """监听 NapCat 连接状态，断开时暂停同步，重连后恢复"""
    # 通过 adapter_mgr 监听适配器事件
```

### 2. 并行下载

当前 `_sync_once` 在 Step 5 中逐个下载图片。对于首次同步（可能有数百张），可以考虑：

```python
async def _download_all(self, pending: list) -> int:
    """使用 asyncio.gather 或 Semaphore 并发下载"""
    sem = asyncio.Semaphore(5)
    async def _one(item):
        async with sem:
            return await self._download_and_register(*item)
    tasks = [_one(p) for p in pending]
    results = await asyncio.gather(*tasks)
    return sum(1 for r in results if r)
```

### 3. 更多 QQ 表情类型

当前只处理 `fetch_custom_face` 返回的表情。QQ 还有：

- `fetch_emoji_like` — 表情回应
- `fetch_like` — 点赞
- 群聊热表情

可以扩展 `_sync_once` 调用更多 API。

### 4. 反同步

当前是单向（QQ → KiraAI）。可以考虑支持双向：

- 在 KiraAI 贴纸库中新增的图片，自动上传到 QQ 收藏
- 需要调用 NapCat API: `send_action("upload_custom_face", ...)`

### 5. 更智能的 auto_delete

当前 auto_delete 在同步循环末尾一次性清理。可以改为：

- 记录上次删除时间，避免每次同步都全量扫描
- 删除前进行确认：先统计数量，记录日志，不下手

### 6. 日志增强

当前日志比较详细但缺少 `get_logger("qq-sticker-sync", "cyan")` 的彩色输出。可以：

```python
from core.logging_manager import get_logger

# 已存在，直接使用
logger = get_logger("qq-sticker-sync", "cyan")
```

日志颜色为青色，与控制台其他日志（紫色 VLM、绿色系统）区分开来。

## 已确认的待改进

- 暂无明确 bug 报告
- 建议增加连接断开后的自动恢复逻辑
- 建议增加 `httpx` 超时和重试配置化
