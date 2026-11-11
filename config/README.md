# 配置目录说明

这个目录里的文件分两类，**只有模板类进版本管理**。

| 文件 | 归属 | 说明 |
| --- | --- | --- |
| `themes.default.json` | 产品资产，进仓库 | 11 套出厂主题。只读，供「恢复默认」与首次运行初始化 |
| `stickers.json` | 产品资产，进仓库 | 28 个贴纸的中文名/分组 + 6 种背景纹样（含语义说明 `desc`） |
| `themes.json` | **使用者私有数据，不进仓库** | 实际生效的主题配置，后台可直接编辑 |
| `settings.json` | **使用者私有数据，不进仓库** | 默认平台、落款、超采样、颗粒度、输出目录等 |

## 首次运行会发生什么

`cardconfig.ensure_config()` 在 `themes.json` 缺失时自动从 `themes.default.json` 复制一份，在 `settings.json` 缺失时写入内置默认值。所以 clone 仓库后不需要手动创建任何配置文件，直接跑 CLI 即可。

## 私有数据为什么不能进仓库

仓库是公开的。一旦 `themes.json` 被提交，自定义主题、配色、落款偏好都会随历史永久公开，而且 `git pull` 会与本地改动冲突。`.gitignore` 已排除这两个文件；**即使文件存在，也不会被 `git add` 跟踪**。

需要备份自己的主题时，直接复制 `themes.json` 到仓库外的位置，或在网页后台点「导出 JSON」。

## 更新时如何拿到新的出厂主题

`git pull` 只会更新 `themes.default.json`，不会碰你的 `themes.json`。想用新模板里的某套主题：

1. 从 `themes.default.json` 里找到对应主题条目，手动拷贝进 `themes.json`；
2. 或在后台「导出 JSON → 合并 → 导入」。

**不要**用 `--init-config` 或后台「恢复出厂主题」来升级，它们会整体覆盖私有配置。

## 换一套配置目录

- 环境变量：`export DAILY_CARD_CONFIG=/path/to/private-config`
- 或 CLI：`python3 cardgen.py --config-dir /path/to/private-config ...`
- 该目录里同样需要 `themes.default.json` 与 `stickers.json`，否则会退到内置最小主题。
