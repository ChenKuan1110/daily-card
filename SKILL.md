---
name: daily-card
description: 生成「每日一句 / 打卡」风格社交卡片图，适用于朋友圈、公众号、小红书。当用户要求做卡片图、日签、打卡图、语录海报、带标题+副标题+日期的分享图，或要调整主题配色/贴纸元素、从背景图自动取配色时使用。触发词：每日一句、打卡图、日签、分享图、朋友圈配图、小红书封面、公众号首图、卡片生成、daily card、社交卡片。
license: MIT
version: "0.4.0"
compatibility: "Python 3.9+、Pillow、系统需有中文字体（macOS 自带；Linux 需 Noto Sans CJK）"
---

# daily-card · 社交卡片生成器

## 能力一句话

输入 **标题 + 副标题** → 输出一张 PNG：自动包含当天日期、与文案主题相关的矢量贴纸、成套统一的配色。纯本地渲染，中文文字 100% 可控，同参数结果可复现。

**这个仓库本身就是一个 skill 目录**：本 SKILL.md 所在目录即项目根，代码、配置模板、文档都在同级。可放进 WorkBuddy / Claude Code / Codex CLI 等各自的 skills 路径，也可由 skillhub 类平台从 GitHub 导入。

## 安装与位置

项目根 = 本 SKILL.md 所在目录。放到任何路径都能跑——代码用 `__file__` 定位，不依赖绝对路径。

```bash
cd /path/to/daily-card          # 换成实际安装位置
python3 -m pip install -r requirements.txt
./install.sh                    # 幂等安装：依赖、私有配置初始化、自检
./scripts/selfcheck.sh          # 之后随时可单独自检（也是 CI 入口）
```

不需要联网、不需要 AI 接口、不需要 API Key。中文字体自动探测：macOS 用 Hiragino Sans GB / PingFang，Linux 用 Noto Sans CJK，Windows 用微软雅黑；都找不到时会退出并提示用 `--font` / `--font-bold` 指定字体文件。

**agent 优先用本地 CLI，不需要启动任何服务。** 网页后台与远程 API 都是可选后端，见「两种可选后端」。

## 最常用：命令行生成（agent 优先用这条）

```bash
python3 cardgen.py "今天也要好好生活" "把普通的日子，过得响亮一点"
```

命令会打印 `文件：...` 的完整路径；**把这个 PNG 路径用 present_files 交给用户**，并在回复里说明主题和尺寸。默认输出目录 `output/`，文件名 `<标题>-<日期>-<平台>.png`。

### 常用参数

| 参数 | 作用 | 示例 |
| --- | --- | --- |
| `-t` / `-s` | 标题 / 副标题 | `-t "早安" -s "先起床"` |
| `--platform` | 尺寸预设 | `xhs`(1080×1440) / `moments`(1080×1080) / `wechat`(900×500) / `story`(1080×1920) / `wechat2`(1080×460) |
| `--theme` | 强制主题，默认按关键词自动识别 | `--theme study` |
| `--date` | 指定日期 | `--date 2026-01-01` |
| `--brand` | 底部落款 | `--brand "Claw · 每日一句"` |
| `--out` | 指定输出路径 | `--out /tmp/card.png` |
| `--seed` | 构图随机种子，同种子同构图 | `--seed 42` |
| `--bg-image` | 自定义背景图（自动取色） | `--bg-image ./bg.jpg` |
| `--bg-scheme` | 选用第 N 套图片配色，或自定义主色 | `--bg-scheme 2` / `--bg-scheme "#C2185B"` |
| `--list-schemes` | 输出背景图的候选配色方案 JSON | `python3 cardgen.py --bg-image bg.jpg --list-schemes` |
| `--list-themes` | 列出全部主题与贴纸 | |
| `--config-dir` | 使用另一套配置目录 | |
| `--init-config` | 从出厂模板重建 `config/themes.json`（**会覆盖私有主题，先备份**） | |

### 背景图取色的完整流程

```bash
# 1. 先看图片能提取出哪几套配色（返回 JSON：name / base / colors / ratio）
python3 cardgen.py --bg-image ./bg.jpg --list-schemes

# 2. 选一套生成（0 是主色，1/2/3 是辅色；也可以直接给 #RRGGBB）
python3 cardgen.py "黄昏是白天给夜晚的回信" "今天也辛苦了" \
  --bg-image ./bg.jpg --bg-scheme 2 --platform xhs
```

配色（背景、文字、强调色、卡片、贴纸）全部由选中的方案派生，所以**贴纸颜色必然与画面同色系**；贴纸种类仍按标题主题自动匹配。

## 配置文件（改配置，不要改代码）

| 文件 | 内容 | 是否进仓库 |
| --- | --- | --- |
| `config/themes.default.json` | 出厂模板，11 套主题，只读，用于「恢复默认」 | 是 |
| `config/stickers.json` | 28 个贴纸的中文名/分组 + 6 种背景纹样注册表（含语义说明 `desc`） | 是 |
| `config/themes.json` | **实际生效**的主题配置：label、keywords、10 个颜色、motif、stickers、dark | **否，私有数据** |
| `config/settings.json` | 默认平台、落款、超采样倍数、颗粒强度、输出目录、默认配色方案序号 | **否，私有数据** |

`themes.json` 与 `settings.json` 属于使用者私有数据，不进版本管理、不随公开仓库发布。**首次运行时 `cardconfig.ensure_config()` 会自动从出厂模板复制生成**，无需手动创建。想换一套配置目录用 `DAILY_CARD_CONFIG` 环境变量或 `--config-dir`。详见 `config/README.md`。

内置 11 套主题：`study` `morning` `night` `coffee` `sport` `nature` `mood` `work` `tech` `festival` `quote`。

**要改配色/贴纸时**：直接编辑 `config/themes.json` 对应主题的 `colors` / `stickers` / `keywords`，或走后台 API；脚本每次运行都重新读取，改完立即生效。新增主题需包含全部 10 个颜色键（`#RRGGBB`）、至少一个合法贴纸 ID。因为它是私有数据，改完不会出现在 `git status` 里，需要备份请自行复制该文件。

## 两种可选后端

| 后端 | 何时需要 | 启用方式 |
| --- | --- | --- |
| 无（默认） | 只要用 CLI 生成卡片 | 什么都不做，直接 `python3 cardgen.py ...` |
| 本地网页后台 | 要 GUI、实时预览、可视化改主题 | `python3 server.py`，接口在 `http://127.0.0.1:8777` |
| 远程服务器 | 团队共享、agent 需要稳定端点 | 自行部署后设 `DAILY_CARD_URL`，把 API 基址换掉 |

CLI 始终在调用方本机执行，与后端无关。**没有启动服务时不要调 `/api/*`**，会连接失败。

### 本地网页后台（可视化配置 + 实时预览）

```bash
python3 server.py                 # http://127.0.0.1:8777
python3 server.py --port 9000 --open
# macOS 也可双击 start-server.command
```

三个面板：卡片设计（表单 + 实时预览 + 下载/保存）、主题配置（可视化改颜色/贴纸/关键词并写回 JSON）、全局设置（默认值与渲染参数）。Tab 可用 `#design` / `#config` / `#settings` 深链。

主题配置面板是三栏：主题列表 / 编辑器 / **实时效果预览**。编辑颜色、背景纹样、深色开关、贴纸时，右侧会立刻显示尚未保存的草稿效果，包括真实卡片、配色语义图（标注 10 个颜色各用在哪、当前纹样实际长什么样）、贴纸在该配色下的样子，以及 WCAG 对比度/明暗一致性诊断。预览只读内存，**不会写 `config/themes.json`**，满意后点「保存配置」才落盘。

### JSON 接口（agent 可直接调用，无需浏览器）

| 接口 | 说明 |
| --- | --- |
| `GET /api/bootstrap` | 一次拿到 themes_doc / settings / registry / platforms / 路径 |
| `POST /api/render` | 生成预览，返回 `{png: dataURL, path, theme, size, bytes}` |
| `POST /api/save` | 生成并写入 `output/`，返回落盘路径 |
| `POST /api/theme-preview` | **未保存主题草案** → 卡片 + 语义图 + 贴纸条 + 可读性诊断，不写配置文件 |
| `POST /api/schemes` | 背景图 → 多套配色方案。传 `{"path":"/abs/bg.jpg"}` 或 `{"image":"data:image/png;base64,..."}` |
| `GET /api/schemes?image_id=xxx` | 重新取已上传图片的方案 |
| `POST /api/config/themes` | `{"themes_doc": {...}}` 保存主题配置（有校验） |
| `POST /api/config/settings` | `{"settings": {...}}` 保存全局设置 |
| `POST /api/config/reset` | 恢复出厂主题（**会覆盖私有主题，先备份**） |
| `POST /api/reveal` | 打开输出文件夹 |
| `GET /api/sticker?id=book&theme=study` | 贴纸图标 PNG |

`/api/render` 与 `/api/save` 的请求体：

```json
{
  "title": "今天也要好好生活",
  "subtitle": "把普通的日子过得响亮一点",
  "platform": "xhs",
  "theme": "auto",
  "date": null,
  "brand": "Claw · 每日一句",
  "seed": null,
  "bg_image_id": null,
  "bg_path": "./bg.jpg",
  "bg_scheme": 0,
  "dark_override": null
}
```

- `bg_scheme` 可为整数序号或 `#RRGGBB`；`dark_override` 为 `true/false` 时强制浅/深卡片，`null` 跟随图片判断。
- `bg_image_id` 由 `/api/schemes` 返回；也可以直接给 `bg_path` 服务端可访问的路径。
- 返回的 `png` 是 `data:image/png;base64,...`，解码后写文件即可。

示例（`DAILY_CARD_URL` 未设置时走本地）：

```bash
DC_URL="${DAILY_CARD_URL:-http://127.0.0.1:8777}"
curl -s "$DC_URL/api/save" \
  -H 'Content-Type: application/json' \
  -d '{"title":"今天也要好好生活","subtitle":"把日子过得响亮一点","platform":"xhs"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["path"])'
```

### 主题草案预览 / 配色诊断（保存前先验货）

想在写入配置前判断一套配色好不好看、文字读不读得清，调 `/api/theme-preview`。`theme` 是完整主题草稿，服务端只放内存：

```json
{
  "theme": {
    "label": "MY THEME · 新主题",
    "keywords": ["打卡"],
    "motif": "dots",
    "dark": false,
    "colors": {
      "bg1": "#F7E9C8", "bg2": "#EED6A4", "card": "#FFFCF6",
      "ink": "#2E3A2C", "sub": "#6D7570", "accent": "#E0703C",
      "accent2": "#5D8B6A", "soft": "#F1D9A8", "pill": "#2E3A2C",
      "pill_text": "#FFFDF5"
    },
    "stickers": ["book", "pencil", "sun"]
  },
  "title": "示例标题",
  "subtitle": "示例副标题",
  "platform": "moments",
  "date": "2026-11-11",
  "seed": 7
}
```

返回字段（`card` / `legend` / `stickers` / `sticker_sheet` 均为 `data:image/png;base64,...`）：

| 字段 | 含义 |
| --- | --- |
| `card` | 用这份草稿真实渲染出的卡片 |
| `legend` | 语义化配色示意图：真实纹样 + 卡片层级 + 10 个颜色各管什么 |
| `stickers` | 已选贴纸在当前配色下的样子 |
| `sticker_sheet` | 全量贴纸 sprite，配合 `sheet`（cols/rows/cell/order）切片显示 |
| `diagnostics` | `[{level: ok/warn/tip, text: 中文说明}]` |
| `contrast` | 各项对比度数值（ink_card / sub_card / pill_pair / card_bg / accent_bg / bg_light） |
| `motif` / `dark` / `draft_only` | 纹样中文名与说明、明暗标记、恒为 `true` 表示未落盘 |

`diagnostics` 按 WCAG 对比度检查：主文字/副文字/标签字可读性、卡片与背景区分度、强调色是否够跳、以及「背景很暗却设成浅色主题」这类矛盾。**推荐做法**：先 POST 草稿看诊断 → 有 `warn` 就照提示改颜色再跑一次 → 没有 warn 才调 `/api/config/themes` 保存。

不启动后台时可直接调用模块：

```python
import base64, cardconfig as cfg, cardpreview as cp
draft = cfg.load_doc()["themes"]["study"]        # 嵌套结构，含 colors
draft["colors"]["accent"] = "#C2185B"            # 改一下看看
r = cp.build_preview({"theme": draft, "title": "示例", "subtitle": "副标题"})
for it in r["diagnostics"]:
    print(it["level"], it["text"])
open("/tmp/draft-card.png", "wb").write(base64.b64decode(r["card"].split(",", 1)[1]))
```

## 更新与多端同步

**唯一版本真相源是 git 仓库**，其余各端都是派生，只单向流出：

| 端 | 更新方式 | 私有配置 |
| --- | --- | --- |
| 本机 / 云服务器 | `git pull && ./install.sh` | 不受影响，不会覆盖 |
| 本机 skill 注册 | `./install.sh --link-skill` 建符号链接，避免文件副本漂移 | 不受影响 |
| skillhub 等平台快照 | 维护者打 tag 后重新导入，天然有版本滞后 | 平台只拿到出厂模板 |

出厂模板 `themes.default.json` 随版本更新，使用者私有的 `themes.json` 永不覆盖。需要把新出厂主题合进自己的配置时，手动从 `themes.default.json` 拷贝对应条目，或在后台用「导出 JSON → 合并 → 导入」，不要直接执行 `--init-config` / `/api/config/reset`。

服务器部署与 CI/CD 接入说明见 `docs/DEPLOY.md`。

## Agent 推荐工作流

1. 从用户话里提取标题、副标题（没给副标题就补一句贴合语气的短句，或留空）。
2. 判断平台：没说就用 `xhs`；提到公众号用 `wechat`，朋友圈用 `moments`。
3. 若用户给了背景图：先 `--list-schemes` 或 `/api/schemes` 看候选，选定后再生成；用户没指定就用方案 0。
4. 执行 CLI（无需服务）；只有用户明确要用后台/远程时才调 `/api/save`。
5. **用 present_files 展示成品图**，回复里说明主题、尺寸、日期、取色方案。
6. 用户要改风格 → 改 `config/themes.json` 或后台配置面板，不要改 `cardgen.py`。

## 注意事项

- 代码分工：`cardgen.py` 只负责渲染，`cardconfig.py` 负责配置加载/保存/取色，`cardpreview.py` 负责主题草案预览与配色诊断，`server.py` 是后台，都读同一份 `config/*.json`。
- `output/`、`uploads/`、`config/themes.json`、`config/settings.json`、`.env` 均被 `.gitignore` 忽略；`examples/` 是 demo 成品图（约 6.7 MB，不参与运行，可随时删除）。
- 主题 ID 只允许字母数字 `-` `_`；颜色必须是 `#RRGGBB`；贴纸 ID 必须存在于 `config/stickers.json`。
- 图片尺寸越大、超采样越高越慢；默认 2x 超采样已够清晰。
- `server.py` **零鉴权**且默认只监听 `127.0.0.1`。公开部署前务必自行加反向代理鉴权或 IP 白名单，详见 `docs/DEPLOY.md`。

## 已知限制 / 下一版本计划

- **贴纸不能自定义上传（当前版本）**：贴纸只能从 `config/stickers.json` 已注册的 28 个矢量贴纸中选择，没有独立的贴纸库管理模块，也不支持上传 PNG/SVG 当贴纸。要增加形状，目前需开发者在 `cardgen.py` 新增 `s_xxx` 绘制函数并在 `stickers.json` 注册。
- **下一版本计划**：自定义贴纸上传（PNG/SVG，自动取色适配主题）、贴纸库管理面板（增删改 / 分组 / 预览 / 复用）、贴纸与主题解耦。用户已明确该项放到下一版本实现，本次不涉及。
- 主题草案预览用的是 1x 超采样以加快响应，与最终 2x 输出在极细颗粒上略有差异，版式与配色一致。
