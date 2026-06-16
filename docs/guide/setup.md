# 安装与配置

## 安装

### 方式一：插件商店安装

在 KiraAI WebUI 插件管理页输入仓库地址：

```
https://github.com/CelestNya/kira-plugin-qq-sticker-sync
```

### 方式二：手动复制

```bash
git clone https://github.com/CelestNya/kira-plugin-qq-sticker-sync.git
cp -r kira-plugin-qq-sticker-sync /path/to/kiraai/data/plugins/qq-sticker-sync
```

安装依赖：

```bash
pip install httpx
```

### 启用

在 `data/config/plugins.json` 中添加：

```json
{
  "qq-sticker-sync": true
}
```

或通过 WebUI 插件页面点击启用。

## 验证启动

启动 KiraAI，控制台应有以下输出：

```
[qq-sticker-sync] [QQStickerSyncPlugin] initialized (interval=1800s)
[qq-sticker-sync] Waiting for NapCat client connection...
[qq-sticker-sync] NapCat client connected (adapter: qq)
[qq-sticker-sync] Found 42 QQ custom faces
[qq-sticker-sync] Need to download 3/42 new stickers
[qq-sticker-sync] [1/3] Downloading a1b2c3d4e5f6...
[qq-sticker-sync] Synced QQ sticker: id=127, file=qqsync_a1b2c3d4e5f6.png (15342B)
[qq-sticker-sync] QQ sticker sync complete: 3 new, 42 total (next sync in 1800s)
```

## 配置

在 KiraAI WebUI 插件页面中设置。

参见 [配置选项](/config/options) 页面。
