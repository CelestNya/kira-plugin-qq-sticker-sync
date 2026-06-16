"""
QQ Sticker Sync Plugin

Syncs QQ collected stickers (favorite expressions) to local data/sticker/
via NapCat's fetch_custom_face API.

Works alongside default-sticker plugin:
  1. This plugin downloads QQ stickers to data/sticker/
  2. default-sticker's scan loop picks them up and auto-describes via VLM

Usage:
  - Requires QQ adapter with NapCat WebSocket connection
  - Enable in WebUI plugin manager
  - Stickers appear after default-sticker scan cycle
"""

import asyncio
import base64
import io
import os
import re
import time
from typing import Optional

import httpx
from PIL import Image as PILImage

from core.chat.message_elements import Image
from core.logging_manager import get_logger
from core.plugin import BasePlugin, logger, register
from core.utils.common_utils import desc_img
from core.utils.path_utils import get_data_path
from core.adapter.adapter_utils import IMAdapter

logger = get_logger("qq-sticker-sync", "cyan")

STICKER_DIR = f"{get_data_path()}/sticker"
QQ_SYNC_PREFIX = "qqsync_"
STICKER_DESC_PROMPT = (
    "这是一张sticker（表情包），请描述这张表情包的内容和聊天中哪些情景使用此表情包，"
    "要求描述精确，不要太长，不要使用Markdown等标记符号，如果有文字请将其输出"
)


class QQStickerSyncPlugin(BasePlugin):
    """Sync QQ collected stickers to local"""

    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self._sync_task: Optional[asyncio.Task] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._napcat_client = None
        self._syncing = False

    async def initialize(self):
        self.interval_sec = max(self.plugin_cfg.get("sync_interval_sec", 1800), 60)
        self.auto_delete = self.plugin_cfg.get("auto_delete", False)
        self.download_concurrency = max(self.plugin_cfg.get("download_concurrency", 5), 1)
        self.vlm_concurrency = max(self.plugin_cfg.get("vlm_concurrency", 3), 1)
        self.vlm_compress_enabled = self.plugin_cfg.get("vlm_compress_enabled", False)
        self.vlm_compress_quality = max(min(self.plugin_cfg.get("vlm_compress_quality", 85), 100), 10)
        self.sticker_mgr = self.ctx.sticker_manager

        self._download_sem = asyncio.Semaphore(self.download_concurrency)
        self._vlm_sem = asyncio.Semaphore(self.vlm_concurrency)

        os.makedirs(STICKER_DIR, exist_ok=True)

        self._http_client = httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "KiraAI/2.0"},
        )

        self._sync_task = asyncio.create_task(self._sync_loop())
        compress = f"quality={self.vlm_compress_quality}" if self.vlm_compress_enabled else "off"
        logger.info(f"QQ Sticker Sync initialized (interval={self.interval_sec}s, download_concurrency={self.download_concurrency}, vlm_concurrency={self.vlm_concurrency}, vlm_compress={compress})")

    async def terminate(self):
        if self._sync_task:
            self._sync_task.cancel()
            self._sync_task = None
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    @register.api(method="POST", path="/sync", auth=True)
    async def trigger_manual_sync(self, request):
        """Manual sync trigger API — POST /api/plugin/qq-sticker-sync/sync"""
        if self._syncing:
            return {"status": "busy", "message": "Sync already in progress"}

        asyncio.create_task(self._do_sync())
        return {"status": "ok", "message": "Sync triggered"}

    # ── 查找 QQ 适配器的 NapCat 客户端 ──────────────────────────

    def _find_napcat_client(self):
        """Find QQ adapter and return its NapCatWebSocketClient"""
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

    # ── 主循环 ────────────────────────────────────────────────

    async def _sync_loop(self):
        # Wait for NapCat client to be connected before first sync
        logger.info("Waiting for NapCat client connection...")
        client = await self._wait_for_client(timeout=120)
        if client is None:
            logger.error("NapCat client not available after 120s, sync loop disabled")
            return

        while True:
            try:
                await self._do_sync()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Sync error: {e}")
            await asyncio.sleep(self.interval_sec)

    async def _wait_for_client(self, timeout: float = 120) -> Optional[object]:
        """Poll until NapCat client is available and connected, or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            adapters = self.ctx.adapter_mgr.get_adapters()
            for name, adapter in adapters.items():
                if not isinstance(adapter, IMAdapter):
                    continue
                info = getattr(adapter, "info", None)
                if info and info.platform.lower() == "qq":
                    client = adapter.get_client()
                    if client is not None:
                        # Check if WebSocket is connected and logged in
                        login_evt = getattr(client, "login_success_event", None)
                        if login_evt is not None and login_evt.is_set():
                            logger.info(f"NapCat client connected (adapter: {name})")
                            return client
                        elif login_evt is not None:
                            # Wait for login event with per-attempt timeout
                            try:
                                await asyncio.wait_for(login_evt.wait(), timeout=10)
                                logger.info(f"NapCat client connected (adapter: {name})")
                                return client
                            except asyncio.TimeoutError:
                                logger.debug("NapCat client exists but not yet logged in, retrying...")
            await asyncio.sleep(3)
        return None

    async def _do_sync(self):
        """Find NapCat client and run sync (used by loop and API trigger)"""
        if self._syncing:
            logger.info("Sync already in progress, skipping")
            return
        self._syncing = True
        try:
            client = self._find_napcat_client()
            if client is not None:
                self._napcat_client = client
                await self._sync_once(client)
            else:
                logger.warning("QQ adapter not found or NapCat client not ready, retrying next cycle")
        finally:
            self._syncing = False

    # ── 单次同步 ──────────────────────────────────────────────

    async def _sync_once(self, client):
        """Fetch custom face list from NapCat and sync new stickers"""

        # ── Recovery: 修复之前同步失败的 pending VLM 贴纸 ──
        await self._recover_pending_vlm()

        # Clean stale DB entries where file was deleted from disk
        await self._cleanup_stale_db()

        logger.info("Fetching QQ custom faces...")

        # Step 1: get face list (quick, URLs only)
        try:
            resp = await client.send_action("fetch_custom_face", {})
        except Exception as e:
            logger.error(f"NapCat API fetch_custom_face failed: {e}")
            return

        if resp.get("status") != "ok" or not resp.get("data"):
            logger.warning(f"fetch_custom_face returned: {resp.get('message', 'empty data')}")
            return

        urls = resp["data"]
        if not isinstance(urls, list):
            logger.warning(f"Unexpected response format, expected list got {type(urls).__name__}")
            return

        logger.info(f"Found {len(urls)} QQ custom faces")

        # Step 2: get detailed metadata (isMarkFace, epId, eId) for all faces
        # fetch_custom_face_detail returns ALL faces' metadata given any faceId
        meta_map = {}  # url_hash -> {isMarkFace, epId, eId}
        eid_map = {}   # e_id -> meta (for market face dedup)
        face_id = self._extract_face_id(urls[0]) if urls else None
        if face_id:
            try:
                detail = await client.send_action("fetch_custom_face_detail", {"faceId": face_id})
                if detail.get("status") == "ok" and isinstance(detail.get("data"), list):
                    for item in detail["data"]:
                        item_url = item.get("url", "")
                        h = self._extract_hash(item_url)
                        meta_entry = {
                            "is_mark_face": item.get("isMarkFace", False),
                            "ep_id": str(item.get("epId", "")),
                            "e_id": str(item.get("eId", "")),
                        }
                        if h:
                            meta_map[h] = meta_entry
                        # Also index by e_id if present (for market face dedup)
                        e_id = item.get("eId", "")
                        if e_id:
                            eid_map[e_id] = meta_entry
            except Exception as e:
                logger.warning(f"fetch_custom_face_detail failed (non-critical): {e}")

        # Build set of already-synced hashes from sticker file names
        existing_hashes = self._get_synced_hashes()
        existing_eids = self._get_synced_eids()

        # Count how many will be downloaded (for progress reporting)
        pending = []
        for url in urls:
            url_hash = self._extract_hash(url)
            if not url_hash:
                continue
            meta = meta_map.get(url_hash, {})
            e_id = meta.get("e_id", "")

            if meta.get("is_mark_face") and e_id:
                if e_id not in existing_eids:
                    pending.append((url, url_hash, meta))
            else:
                if url_hash not in existing_hashes:
                    pending.append((url, url_hash, meta))

        total = len(pending)
        logger.info(f"Need to download {total}/{len(urls)} new stickers")

        # ── Phase 1: 并发下载（无限制） ──
        download_results: list[Optional[dict]] = [None] * total

        async def _download_one(idx: int, url: str, url_hash: str, meta: dict):
            async with self._download_sem:
                result = await self._download_content(url, url_hash, meta)
                download_results[idx] = result

        tasks = [_download_one(i, u, h, m) for i, (u, h, m) in enumerate(pending)]
        await asyncio.gather(*tasks)

        # ── Phase 2: 注册（placeholder desc，不触发 default-sticker VLM） ──
        registered = []  # (item, sid)

        async def _register_one(item: dict):
            sid = await self._register_content(item)
            if sid is not None:
                registered.append((item, sid))

        reg_tasks = [_register_one(d) for d in download_results if d is not None]
        if reg_tasks:
            await asyncio.gather(*reg_tasks)

        # ── Phase 3: 限流 VLM 描述（Semaphore 控制并发） ──
        new_count = 0

        if registered:
            logger.info(f"Phase 1+2 complete, describing {len(registered)} stickers (vlm_concurrency={self.vlm_concurrency})...")

            async def _describe_one(item: dict, sid: str):
                async with self._vlm_sem:
                    desc = await self._describe_sticker(item)
                    if desc:
                        try:
                            await self.sticker_mgr.update_sticker_desc(sid, desc)
                            logger.info(f"Described sticker {sid}: {desc[:60]}...")
                        except Exception as e:
                            logger.error(f"Failed to update desc for sticker {sid}: {e}")

            vlm_tasks = [_describe_one(item, sid) for item, sid in registered]
            await asyncio.gather(*vlm_tasks)
            new_count = len(registered)

        # Collect hashes and e_ids from THIS sync for auto-delete
        current_hashes = set()
        current_eids = set()
        for u in urls:
            h = self._extract_hash(u)
            if h:
                current_hashes.add(h)
        for meta_entry in meta_map.values():
            eid = meta_entry.get("e_id", "")
            if eid:
                current_eids.add(eid)

        # Auto-delete: remove local stickers whose QQ source no longer exists
        if self.auto_delete:
            removed = await self._remove_stale_stickers(current_hashes, current_eids)
            if removed:
                logger.info(f"Removed {removed} stale stickers (no longer in QQ favorites)")

        logger.info(f"QQ sticker sync complete: {new_count} new, {len(urls)} total (next sync in {self.interval_sec}s)")

    async def _cleanup_stale_db(self):
        """Remove stale qqsync_ DB entries: missing files + duplicate paths."""
        prefix = QQ_SYNC_PREFIX
        seen = {}  # path → first sid
        removed = 0
        for sid, info in list(self.sticker_mgr.sticker_dict.items()):
            path = info.get("path", "")
            if not path.startswith(prefix):
                continue
            full_path = os.path.join(STICKER_DIR, path)
            if not os.path.exists(full_path):
                await self.sticker_mgr.delete_sticker(sid, delete_file=False)
                removed += 1
            elif path in seen:
                # Duplicate path: keep the first entry, delete the rest
                await self.sticker_mgr.delete_sticker(sid, delete_file=False)
                removed += 1
            else:
                seen[path] = sid
        if removed:
            logger.info(f"Cleaned {removed} stale DB entries (file missing or duplicate)")

    # ── 下载 ──────────────────────────────────────────────────

    async def _download_content(self, url: str, url_hash: str, meta: dict) -> Optional[dict]:
        """Download sticker image bytes. No side effects, no VLM trigger."""
        if not self._http_client:
            return None
        is_mark = meta.get("is_mark_face", False)
        e_id = meta.get("e_id", "")

        if is_mark and e_id:
            download_url = self._build_cdn_url(e_id)
        else:
            download_url = url

        try:
            t0 = time.monotonic()
            response = await self._http_client.get(download_url)
            elapsed = time.monotonic() - t0
            if elapsed > 5:
                logger.warning(f"Slow download ({elapsed:.1f}s): {download_url[:60]}...")
            if response.status_code != 200:
                logger.warning(f"Download failed {download_url[:60]}... (HTTP {response.status_code})")
                return None

            content = response.content
            if not content:
                return None

            ct = response.headers.get("content-type", "")
            ext = self._content_type_to_ext(ct) or ".png"

            if is_mark and e_id:
                filename = f"qqsync_{e_id}{ext}"
            else:
                filename = f"qqsync_{url_hash}{ext}"

            label = e_id or url_hash
            logger.info(f"Downloaded {label} ({len(content)}B, {elapsed:.1f}s)")
            return {
                "filename": filename,
                "content": content,
                "url_hash": url_hash,
                "url": url,
                "meta": meta,
            }

        except httpx.TimeoutException:
            logger.warning(f"Timeout downloading {download_url[:60]}...")
        except Exception as e:
            logger.error(f"Error downloading {download_url[:60]}...: {e}")
        return None

    # ── 注册（placeholder desc，跳过 default-sticker VLM） ──────

    async def _register_content(self, item: dict) -> Optional[str]:
        """Register downloaded content, return sticker_id. No VLM trigger."""
        filename = item["filename"]
        content = item["content"]
        url_hash = item["url_hash"]
        url = item["url"]
        meta = item["meta"]
        is_mark = meta.get("is_mark_face", False)
        e_id = meta.get("e_id", "")

        try:
            result = await self.sticker_mgr.add_sticker(
                file_bytes=content,
                original_filename=filename,
                sticker_id=None,
                desc="__pending_vlm__",  # non-empty → default-sticker skips VLM
            )

            extra_fields = {
                "source": "qq_sticker_sync",
                "source_url_hash": url_hash,
                "source_url": url,
                "is_mark_face": is_mark,
            }
            if meta.get("ep_id"):
                extra_fields["ep_id"] = meta["ep_id"]
            if e_id:
                extra_fields["e_id"] = e_id
            for key, val in extra_fields.items():
                self.sticker_mgr.set_sticker_extra(result["id"], key, val)

            if is_mark:
                logger.info(f"Registered QQ marketplace sticker: id={result['id']}, file={filename}")
            else:
                logger.info(f"Registered QQ sticker: id={result['id']}, file={filename}")
            return result["id"]

        except Exception as e:
            logger.error(f"Failed to register sticker {filename}: {e}")
            return None

    # ── VLM 描述恢复 ────────────────────────────────────────────

    async def _recover_pending_vlm(self):
        """Scan all qqsync_ stickers, find __pending_vlm__ ones and describe them."""
        pending = []
        for sid, info in self.sticker_mgr.sticker_dict.items():
            path = info.get("path", "")
            desc = info.get("desc", "")
            if path.startswith(QQ_SYNC_PREFIX) and desc == "__pending_vlm__":
                pending.append((sid, path))

        if not pending:
            return

        logger.info(f"Recovery: found {len(pending)} stickers with pending VLM description")

        async def _recover_one(sid: str, path: str):
            async with self._vlm_sem:
                full_path = os.path.join(STICKER_DIR, path)
                if not os.path.exists(full_path):
                    logger.warning(f"Recovery: sticker file missing, deleting {sid} ({path})")
                    try:
                        await self.sticker_mgr.delete_sticker(sid, delete_file=False)
                    except Exception:
                        pass
                    return
                desc = await self._vlm_describe_file(full_path, path)
                if desc:
                    try:
                        await self.sticker_mgr.update_sticker_desc(sid, desc)
                        logger.info(f"Recovery: described sticker {sid}: {desc[:60]}...")
                    except Exception as e:
                        logger.error(f"Recovery: failed to update desc for sticker {sid}: {e}")

        tasks = [_recover_one(sid, path) for sid, path in pending]
        await asyncio.gather(*tasks)
        logger.info("Recovery: pending VLM description complete")

    # ── VLM 描述（共享核心，带压缩） ────────────────────────────

    async def _vlm_describe_file(self, filepath: str, label: str) -> Optional[str]:
        """VLM-describe an image file. Shared by recovery and new sticker phases."""
        if not os.path.exists(filepath):
            logger.warning(f"Sticker file not found for VLM: {filepath}")
            return None

        try:
            vlm = self.ctx.provider_mgr.get_default_vlm()

            if self.vlm_compress_enabled:
                pil_img = PILImage.open(filepath)
                if pil_img.mode == "RGBA":
                    bg = PILImage.new("RGB", pil_img.size, (255, 255, 255))
                    bg.paste(pil_img, mask=pil_img.split()[3])
                    pil_img = bg
                elif pil_img.mode != "RGB":
                    pil_img = pil_img.convert("RGB")
                buf = io.BytesIO()
                pil_img.save(buf, format="JPEG", quality=self.vlm_compress_quality)
                bs64 = base64.b64encode(buf.getvalue()).decode()
                image = Image(image=f"data:image/jpeg;base64,{bs64}")
                logger.info(f"Compressed {label} → JPEG q={self.vlm_compress_quality} ({buf.tell()/1024:.0f}KB base64)")
            else:
                image = Image(image=filepath)

            sticker_desc = await desc_img(
                client=vlm,
                image=image,
                prompt=STICKER_DESC_PROMPT,
            )
            return sticker_desc
        except Exception as e:
            logger.error(f"VLM description failed for {label}: {e}")
            return None

    async def _describe_sticker(self, item: dict) -> Optional[str]:
        """VLM-describe a new sticker from download result. Delegates to _vlm_describe_file."""
        filename = item["filename"]
        sticker_path = os.path.join(STICKER_DIR, filename)
        return await self._vlm_describe_file(sticker_path, filename)

    # ── 删除失效表情 ──────────────────────────────────────────

    async def _remove_stale_stickers(self, current_hashes: set, current_eids: set) -> int:
        """Remove local qqsync_ stickers whose source no longer exists in QQ favorites.

        Custom faces identified by url_hash, market faces by e_id.
        """
        removed = 0
        prefix = QQ_SYNC_PREFIX
        for sid, info in list(self.sticker_mgr.sticker_dict.items()):
            path = info.get("path", "")
            if not path.startswith(prefix):
                continue
            # Extract 32-char hex (url_hash or e_id) from "qqsync_{hex}.ext"
            h = self._hash_from_path(path)
            if h and h not in current_hashes and h not in current_eids:
                try:
                    await self.sticker_mgr.delete_sticker(sid, delete_file=True)
                    removed += 1
                    logger.info(f"Removed stale sticker {sid} ({path})")
                except Exception as e:
                    logger.error(f"Failed to delete stale sticker {sid}: {e}")
        return removed

    # ── 工具方法 ──────────────────────────────────────────────

    @staticmethod
    def _build_cdn_url(e_id: str) -> str:
        """Build CDN URL for 300px market face from its e_id.

        CDN only serves raw300.gif (300x300). No higher resolution available.
        """
        dir_prefix = e_id[:2]
        return f"https://gxh.vip.qq.com/club/item/parcel/item/{dir_prefix}/{e_id}/raw300.gif"

    def _get_synced_eids(self) -> set:
        """Collect e_ids from qqsync_ files in sticker folder.

        Scans actual files on disk, not DB records.
        """
        eids = set()
        prefix = QQ_SYNC_PREFIX
        if not os.path.isdir(STICKER_DIR):
            return eids
        for fname in os.listdir(STICKER_DIR):
            if not fname.startswith(prefix):
                continue
            name = fname[len(prefix):]
            name = os.path.splitext(name)[0]
            if re.match(r'^[a-f0-9]{32}$', name):
                eids.add(name)
        return eids

    def _get_synced_hashes(self) -> set:
        """Collect URL hashes from qqsync_ files in sticker folder.

        Scans actual files on disk, not DB records.
        """
        hashes = set()
        prefix = QQ_SYNC_PREFIX
        if not os.path.isdir(STICKER_DIR):
            return hashes
        for fname in os.listdir(STICKER_DIR):
            if not fname.startswith(prefix):
                continue
            h = self._hash_from_path(fname)
            if h:
                hashes.add(h)
        return hashes

    @staticmethod
    def _hash_from_path(path: str) -> Optional[str]:
        """Extract hash from 'qqsync_{hash}.ext'"""
        # Strip prefix and extension
        name = path
        if name.startswith(QQ_SYNC_PREFIX):
            name = name[len(QQ_SYNC_PREFIX):]
        name = os.path.splitext(name)[0]
        if re.match(r'^[a-f0-9]{32}$', name):
            return name
        return None

    @staticmethod
    def _extract_hash(url: str) -> Optional[str]:
        """Extract content MD5 hash from QQ expression URL

        URL format varies:
          .../2859445368_0_0_1_<upper32>_<num>_<hash32>/0   ← marketplace
          .../2859445368_0_0_0_<upper32>_0_0/0               ← user image
        Take the last 32-hex segment found (case-insensitive).
        """
        matches = re.findall(r"([a-fA-F0-9]{32})", url)
        return matches[-1].lower() if matches else None

    @staticmethod
    def _extract_face_id(url: str) -> Optional[str]:
        """Extract the first (sticker ID) 32-hex from URL for detail API query"""
        matches = re.findall(r"([a-fA-F0-9]{32})", url)
        return matches[0] if matches else None

    @staticmethod
    def _content_type_to_ext(ct: str) -> Optional[str]:
        """Map HTTP Content-Type to file extension"""
        if not ct:
            return None
        ct = ct.split(";")[0].strip().lower()
        mapping = {
            "image/png": ".png",
            "image/gif": ".gif",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "image/bmp": ".bmp",
        }
        return mapping.get(ct)
