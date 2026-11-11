# 服务器部署与更新

本文说明如何把 daily-card 部署到云服务器。**默认形态是「同域名多服务，nginx 用 `location /daily-card/` 区分」**：nginx 直接托管前端静态资源，Python 服务只提供 JSON API。独占域名的简单写法保留在第 4 节。

> **安全边界**：`server.py` 是零鉴权的 `ThreadingHTTPServer`，默认只监听 `127.0.0.1:8777`。公网流量必须先进 nginx，由反代承担鉴权；**不要**用 `--host 0.0.0.0` 直接暴露。

## 0. 架构约定

这一节记录设计约束，改动代码或 nginx 配置前请先确认没有破坏它们。

1. **部署前缀是运行时变量，不属于源码。** 前端所有 URL 由 `web/app.js` 顶部唯一的 `BASE` 派生（`new URL(".", document.baseURI)`），源码里不允许出现 `src="/..."`、`href="/..."`、`"/api/..."` 这类域名根绝对路径。`scripts/selfcheck.sh` 第 7 步会阻断这类回归。
2. **前缀由 nginx 剥离，后端路由恒为 `/api/*`。** 用 `rewrite ^/daily-card/(.*)$ /$1 break;` 配合**不带 URI** 的 `proxy_pass`。因此 CLI、既有 8 组接口、SKILL.md 中的调用示例都不需要为部署形态改动。
3. **静态与 API 同源。** 两者都挂在 `/daily-card/` 下，一次 `auth_basic` 即可覆盖；若拆到不同 location 前缀，两个 location 都必须加鉴权，否则接口会裸奔。
4. **本地开发保持零配置。** `python3 server.py`（独立模式）仍同时托管 `web/` 与 API，`./start-server.command` 与 agent 的本机调用不受云部署影响。云上才用 `--api-only`。
5. **前端可独立发版。** 静态资源发布到带版本号的目录，用 `current` 符号链接切换，回滚不需要重启 Python 服务。
6. **尾斜杠是硬要求。** `/daily-card` 必须 301 到 `/daily-card/`，否则浏览器会把相对路径 `api/bootstrap` 解析成 `/api/bootstrap`，请求会落到同域名其它服务上。

## 1. 前置条件

| 项 | 要求 | 检查 |
| --- | --- | --- |
| Python | 3.9+ | `python3 --version` |
| Pillow | 见 `requirements.txt` | `python3 -c "import PIL; print(PIL.__version__)"` |
| 中文字体 | Noto Sans CJK（Linux 必需） | `fc-list \| grep -i "noto.*cjk"` |
| git | 用于后续更新 | `git --version` |
| nginx | 统一入口，已有其它服务 | `nginx -v` |

安装中文字体（**最容易漏的一步**，缺了会直接报「找不到中文字体」）：

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y fonts-noto-cjk

# RHEL / CentOS / Fedora
sudo dnf install -y google-noto-sans-cjk-fonts

sudo fc-cache -fv
```

渲染器按 `Hiragino Sans GB → PingFang → STHeiti → NotoSansCJK → 微软雅黑` 顺序探测；Linux 上靠 NotoSansCJK 命中。字体放在自定义位置时，用 `--font` / `--font-bold` 指定。

## 2. 安装

```bash
sudo mkdir -p /opt
sudo git clone https://github.com/ChenKuan1110/daily-card.git /opt/daily-card
cd /opt/daily-card
./install.sh                 # 装依赖、初始化私有配置、跑自检
./scripts/selfcheck.sh       # 单独复验，共 8 步（含子路径链路模拟）
```

`install.sh` 幂等，重复执行不会覆盖已有的 `config/themes.json`。CI 里直接跑 `./scripts/selfcheck.sh`：只读检查 + 一次临时渲染 + 进程内的子路径代理回归，不写 `output/`、不改配置、不需要 nginx。

### 私有配置放哪里

建议把使用者数据放到仓库目录之外，避免 `git pull` 时混在一起：

```bash
sudo mkdir -p /etc/daily-card
sudo cp /opt/daily-card/config/themes.default.json /etc/daily-card/
sudo cp /opt/daily-card/config/stickers.json      /etc/daily-card/
sudo cp /opt/daily-card/config/themes.json        /etc/daily-card/   # 如需带自己的主题
sudo cp /opt/daily-card/config/settings.json      /etc/daily-card/   # 如需带自己的设置
export DAILY_CARD_CONFIG=/etc/daily-card
```

`DAILY_CARD_CONFIG` 可用 `Environment=` 写进 systemd unit。`themes.default.json` 与 `stickers.json` 必须在该目录里，否则会退到内置最小主题。

> 服务器上的 `themes.json` / `settings.json` 是私有数据，**不在版本管理里**：升级不会覆盖，但 `git clone` 也不会帮你备份，请自行定期复制。网页后台有「导出 JSON」可用。

## 3. 形态 A（推荐）：同域名子路径 `/daily-card/`

### 3.1 请求链路

```
浏览器
  ├── /daily-card/、*.css、*.js  ──> nginx alias ──> /opt/daily-card-web/current/
  └── /daily-card/api/*          ──> nginx rewrite（剥前缀）──> 127.0.0.1:8777 /api/*
```

Python 服务以 `--api-only` 运行，只回答 `/api/*`；静态资源不经过 Python。前端的 `BASE` 从页面 URL 推导，因此 `fetch("api/bootstrap")` 实际请求 `/daily-card/api/bootstrap`，再由 nginx 还原成 `/api/bootstrap`。

### 3.2 发布前端静态版本

```bash
cd /opt/daily-card
sudo mkdir -p /opt/daily-card-web
sudo ./scripts/publish-web.sh                # 版本目录取 VERSION，如 v0.5.0
sudo ./scripts/publish-web.sh --list          # 查看已发布版本与当前指向
sudo ./scripts/publish-web.sh --rollback      # 回滚到上一个版本
sudo ./scripts/publish-web.sh --rollback v0.4.9   # 回滚到指定版本
```

脚本会把 `web/` 复制到 `/opt/daily-card-web/vX.Y.Z/`，写入 `manifest.json`（版本、UTC 时间、来源 commit），然后原子切换 `current` 符号链接；`nginx alias` 始终指向 `current/`，所以**切版本不需要 reload nginx，也不需要重启 Python**。默认保留 5 个历史版本，可用环境变量调整：

```bash
sudo env DAILY_CARD_WEB_ROOT=/srv/daily-card-web DAILY_CARD_WEB_KEEP=3 ./scripts/publish-web.sh
```

清理旧版本只作用于本脚本初始化过的根目录（有 `.daily-card-web-root` 标记）且只删 `v*` 目录，不触碰其它文件。

### 3.3 nginx 配置

生成密码文件：

```bash
sudo apt install -y apache2-utils        # 提供 htpasswd
sudo htpasswd -c /etc/nginx/.htpasswd carduser
```

把下面这段放进**已有的 `server {}` 块**（与其它服务共存，不要在 server 级写 `auth_basic`，否则会误伤别的服务）：

```nginx
# /daily-card → /daily-card/，保证相对路径的解析基准正确
location = /daily-card {
    return 301 /daily-card/;
}

# API：剥掉 /daily-card 前缀后转发，后端仍收到 /api/*
location ^~ /daily-card/api/ {
    rewrite ^/daily-card/(.*)$ /$1 break;
    proxy_pass http://127.0.0.1:8777;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
    client_max_body_size 24m;          # 对齐后端 MAX_BODY

    auth_basic "daily-card";
    auth_basic_user_file /etc/nginx/.htpasswd;
}

# 静态：nginx 直接出文件，不经过 Python
location ^~ /daily-card/ {
    alias /opt/daily-card-web/current/;
    index index.html;
    add_header Cache-Control "no-cache" always;   # 走 ETag 协商，切版本后刷新即生效

    auth_basic "daily-card";
    auth_basic_user_file /etc/nginx/.htpasswd;
}
```

三个容易踩坑的点：

- `proxy_pass` **不带 URI**，前缀靠 `rewrite ... break` 剥掉。若写成 `proxy_pass http://127.0.0.1:8777/;`，nginx 会把 location 匹配段替换掉，后端收到的是 `/bootstrap` 而不是 `/api/bootstrap`。
- `^~` 保证这两个前缀优先于同域名下可能存在的正则 location（例如其它服务的 `\.(js|css)$` 规则）。
- 静态资源用 `no-cache` + ETag 协商，不要设长 `expires`：版本切换后 URL 不变，长缓存会让用户一直拿旧 CSS。要做强缓存，需改成带版本号的 URL 前缀。

两处 `auth_basic` 可用 `include /etc/nginx/snippets/daily-card-auth.conf;` 去重。只在内网/VPN 使用时，可换成 `allow 10.0.0.0/8; deny all;` 之类的 IP 白名单。

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### 3.4 进程守护

`/etc/systemd/system/daily-card.service`：

```ini
[Unit]
Description=daily-card API service
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/daily-card
Environment=DAILY_CARD_CONFIG=/etc/daily-card
ExecStart=/usr/bin/python3 server.py --host 127.0.0.1 --port 8777 --api-only
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo chown -R www-data:www-data /opt/daily-card/output /opt/daily-card/uploads
sudo chown -R www-data:www-data /etc/daily-card
sudo systemctl daemon-reload
sudo systemctl enable --now daily-card
sudo systemctl status daily-card
```

`--api-only` 下后端不再托管静态页面，`/api/reveal` 也返回 403（远程没有「打开本机文件夹」语义，前端会自动禁用该按钮）。

### 3.5 验证

```bash
# 后端（本机）
curl -s http://127.0.0.1:8777/api/health
# {"ok":true,"version":"0.5.0","mode":"api-only","serves_static":false,...}

# 公网（带鉴权）
curl -u carduser:PASSWORD -I https://your-domain/daily-card/
curl -u carduser:PASSWORD -s  https://your-domain/daily-card/api/health
curl -u carduser:PASSWORD -s  https://your-domain/daily-card/style.css | head -3
```

再打开 `https://your-domain/daily-card/` 检查三个面板：设计、主题配置、全局设置，以及贴纸图标是否加载。页面里所有资源请求都应以 `/daily-card/` 开头。

## 4. 形态 B（附录）：独占域名 / 根路径

若没有「同域名多服务」的约束，可以保持原来的单体写法：Python 同时托管页面与 API（**不要加 `--api-only`**），nginx 全量转发。

```nginx
server {
    listen 443 ssl http2;
    server_name card.example.com;
    ssl_certificate     /etc/letsencrypt/live/card.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/card.example.com/privkey.pem;

    client_max_body_size 24m;
    auth_basic "daily-card";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:8777;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }
}

server {
    listen 80;
    server_name card.example.com;
    return 301 https://$host$request_uri;
}
```

systemd 的 `ExecStart` 去掉 `--api-only` 即可。这种形态不需要 `publish-web.sh`，前端随代码一起更新。

### 容器方式（可选）

```bash
docker run -d --name daily-card --restart always \
  -p 127.0.0.1:8777:8777 \
  -v /opt/daily-card:/app -v /etc/daily-card:/config \
  -e DAILY_CARD_CONFIG=/config \
  -w /app python:3.11-slim \
  sh -c "pip install -r requirements.txt && python3 server.py --host 0.0.0.0 --port 8777"
```

容器内监听 `0.0.0.0` 只为端口映射生效，宿主机仍只绑定 `127.0.0.1:8777`。镜像里要装 `fonts-noto-cjk`。若走形态 A，命令加 `--api-only` 并把静态目录单独挂载给 nginx。

## 5. 更新与 CI/CD

唯一版本真相源是 git 仓库，所有端都从它派生。

### 手动更新

```bash
cd /opt/daily-card
git pull
./install.sh --no-deps
sudo ./scripts/publish-web.sh          # 前端独立发版；形态 B 可跳过
sudo systemctl restart daily-card      # 仅后端代码变化时
```

只改前端时，单独执行 `publish-web.sh` 即可，不必重启 Python；只改 nginx 配置时才需要 `systemctl reload nginx`。私有配置在 `/etc/daily-card`，完全不受 `git pull` 影响。

### CI：每次 push 做自检

`scripts/selfcheck.sh` 是统一入口，8 个步骤：Python 语法、依赖与私有配置、主题/平台清单、PNG 冒烟渲染、私有数据忽略检查、前端 JS 语法、前端路径可移植性（含 BASE 推导 4 组单测）、子路径部署模拟（10 项链路断言）。

```yaml
name: selfcheck
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: sudo apt-get update && sudo apt-get install -y fonts-noto-cjk
      - run: pip install -r requirements.txt
      - run: ./scripts/selfcheck.sh
```

### CD：服务器侧拉取

```bash
ssh deploy@server 'cd /opt/daily-card && git pull && ./install.sh --no-deps && sudo ./scripts/publish-web.sh && sudo systemctl restart daily-card'
```

推荐节奏：CI 跑 `selfcheck.sh` → 通过后打 tag → tag 触发 CD 拉取 → 平台侧按 tag 重新导入 skill 快照。skillhub 类平台存的是**快照**，需要维护者重新导入才会生成新版本，版本天然滞后于服务器，属正常现象。

## 6. 排障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 页面能打开但样式/脚本全 404 | 前端仍是旧版绝对路径，或 nginx `alias` 少了尾斜杠 | 确认发布的是 v0.5.0+；检查页面源码应为 `href="style.css"`；`alias` 必须以 `/` 结尾 |
| 接口 404 或打到同域名别的服务 | 前端 URL 未带前缀，或 nginx 没剥前缀 | 确认 `/daily-card` 有 301；用 `curl` 看实际请求路径；核对 `rewrite` + 不带 URI 的 `proxy_pass` |
| 后端收到 `/bootstrap` 而非 `/api/bootstrap` | `proxy_pass` 带了 URI，被 nginx 二次替换 | 改成 `proxy_pass http://127.0.0.1:8777;` 配 `rewrite ... break` |
| 切版本后样式仍是旧的 | 静态资源被强缓存 | 用 `Cache-Control: no-cache` 走 ETag；浏览器硬刷新 |
| `manifest.json` 的 `source_commit` 为 unknown | root 执行时 git 判定仓库属主不可信 | `sudo git config --global --add safe.directory /opt/daily-card` |
| `找不到中文字体` | Linux 没装 Noto CJK | `apt install fonts-noto-cjk` 后 `fc-cache -fv` |
| 中文显示成方块 | 命中的字体不含中文字形 | 用 `--font` / `--font-bold` 指定 `.ttf/.ttc` |
| 上传大图失败 | 超过 24MB | 压缩图片；或同步调大 nginx `client_max_body_size` 与后端 `MAX_BODY` |
| 改了主题没生效 | 改的是出厂模板而非 `themes.json` | 确认 `DAILY_CARD_CONFIG` 指向的目录 |
| `/api/reveal` 返回 403 | `--api-only` 下刻意禁用 | 正常行为，前端已禁用该按钮；需要本地文件夹请走独立模式 |

## 7. 已知边界

- 后端**零鉴权**、CORS 为 `*`；安全完全依赖 nginx 的 `auth_basic` 或 IP 白名单。
- `/api/health` 会回显 `config_dir` 路径，属于内网诊断信息；如不希望暴露，可在 nginx 层限制该路径。
- 前端 `window.DAILY_CARD_BASE` 可把 API 指向独立域名，但此时静态资源仍在页面所在域；若真走跨域，需要确认 CORS 与鉴权头能带上，本项目当前只按同源场景验证。
