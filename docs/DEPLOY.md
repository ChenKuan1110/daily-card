# 服务器部署与更新

本文说清楚怎么把 daily-card 装到自己的云服务器、怎么安全地对外提供网页后台、以及后续怎么用 CI/CD 更新。

> **本次改造未改动 `server.py`。** 它仍是零鉴权的 `ThreadingHTTPServer`，默认只监听 `127.0.0.1:8777`。安全边界由反向代理承担，请务必按下面的方式部署，不要把 `--host 0.0.0.0` 直接暴露到公网。

## 1. 前置条件

| 项 | 要求 | 检查 |
| --- | --- | --- |
| Python | 3.9+ | `python3 --version` |
| Pillow | 见 `requirements.txt` | `python3 -c "import PIL; print(PIL.__version__)"` |
| 中文字体 | Noto Sans CJK（Linux 必需） | `fc-list \| grep -i "noto.*cjk"` |
| git | 用于后续更新 | `git --version` |

安装中文字体（**最容易漏的一步**，缺了会直接报「找不到中文字体」）：

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y fonts-noto-cjk

# RHEL / CentOS / Fedora
sudo dnf install -y google-noto-sans-cjk-fonts

# 装完刷新缓存
sudo fc-cache -fv
```

渲染器按 `Hiragino Sans GB → PingFang → STHeiti → NotoSansCJK → 微软雅黑` 顺序探测；Linux 上靠 NotoSansCJK 命中。若字体放在自定义位置，用 `--font` / `--font-bold` 指定，或在 `config/` 同目录放软链。

## 2. 安装

```bash
sudo mkdir -p /opt
sudo git clone <仓库地址> /opt/daily-card
cd /opt/daily-card
./install.sh                 # 装依赖、初始化私有配置、跑自检
./scripts/selfcheck.sh       # 单独复验：语法 / 配置 / 冒烟渲染 / 私有数据检查
```

`install.sh` 幂等，重复执行不会覆盖已有的 `config/themes.json`。CI 里直接跑 `./scripts/selfcheck.sh` 即可，它只读检查 + 一次临时渲染，不写 `output/`、不改配置。

### 私有配置放哪里

建议把使用者数据放到仓库目录之外，避免 `git pull` 时与仓库内容混在一起：

```bash
sudo mkdir -p /etc/daily-card
sudo cp /opt/daily-card/config/themes.default.json /etc/daily-card/
sudo cp /opt/daily-card/config/stickers.json      /etc/daily-card/
sudo cp /opt/daily-card/config/themes.json        /etc/daily-card/   # 如需带自己的主题
sudo cp /opt/daily-card/config/settings.json      /etc/daily-card/   # 如需带自己的设置
export DAILY_CARD_CONFIG=/etc/daily-card
```

`DAILY_CARD_CONFIG` 也可用 `Environment=` 写进下面的 systemd unit。`themes.default.json` 和 `stickers.json` 必须在该目录里，否则会退到内置最小主题。

> 服务器上的 `themes.json` / `settings.json` 是私有数据，**不在版本管理里**。升级不会覆盖它们，但也意味着 `git clone` 不会帮你备份——请自行定期复制。网页后台有「导出 JSON」可用。

## 3. 推荐架构：反向代理承担鉴权

```
浏览器 ──HTTPS──> nginx (auth_basic / IP 白名单) ──> 127.0.0.1:8777 (server.py)
```

`server.py` 保持只听回环地址，公网流量先进 nginx。上传上限对齐后端 `MAX_BODY = 24MB`。

生成密码文件：

```bash
sudo apt install -y apache2-utils        # 提供 htpasswd
sudo htpasswd -c /etc/nginx/.htpasswd carduser
```

`/etc/nginx/sites-available/daily-card`：

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

```bash
sudo ln -s /etc/nginx/sites-available/daily-card /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

如果只在内网/VPN 里用，可以省掉 `auth_basic`，改为 `allow 10.0.0.0/8; deny all;` 之类的 IP 白名单。**无论如何都不要省掉反代层直接暴露 `0.0.0.0`。**

## 4. 进程守护

`/etc/systemd/system/daily-card.service`：

```ini
[Unit]
Description=daily-card web console
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/daily-card
Environment=DAILY_CARD_CONFIG=/etc/daily-card
ExecStart=/usr/bin/python3 server.py --host 127.0.0.1 --port 8777
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo chown -R www-data:www-data /opt/daily-card/output /opt/daily-card/uploads
sudo systemctl daemon-reload
sudo systemctl enable --now daily-card
sudo systemctl status daily-card
```

健康检查：

```bash
curl -s http://127.0.0.1:8777/api/bootstrap | python3 -c \
  'import json,sys; d=json.load(sys.stdin); print("主题", len(d["themes_doc"]["themes"]), "套")'
```

> 后台会往 `uploads/` 写上传图与预览临时图（临时图用完即删）。请确保运行用户对 `uploads/`、`output/`、以及 `DAILY_CARD_CONFIG` 指向的目录有写权限。

### 容器方式（可选）

不写 Dockerfile 也能跑，用挂载把私有配置与产物留在外面：

```bash
docker run -d --name daily-card --restart always \
  -p 127.0.0.1:8777:8777 \
  -v /opt/daily-card:/app -v /etc/daily-card:/config \
  -e DAILY_CARD_CONFIG=/config \
  -w /app python:3.11-slim \
  sh -c "pip install -r requirements.txt && python3 server.py --host 0.0.0.0 --port 8777"
```

容器里监听 `0.0.0.0` 是为了让端口映射生效，但**宿主机只绑定 `127.0.0.1:8777`**，公网仍由 nginx 接入。别忘了镜像里要装 `fonts-noto-cjk`。

## 5. 更新与 CI/CD

唯一版本真相源是 git 仓库，所有端都从它派生。

### 手动更新（先跑通这条，再自动化）

```bash
cd /opt/daily-card
git pull
./install.sh --no-deps
sudo systemctl restart daily-card
```

私有配置在 `/etc/daily-card`，完全不受 `git pull` 影响。

### CI：每次 push 做自检

`scripts/selfcheck.sh` 是统一入口，GitHub Actions 里直接用：

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
      - run: sudo apt-get update && sudo apt-get install -y fonts-noto-cjk
      - run: pip install -r requirements.txt
      - run: ./scripts/selfcheck.sh
```

自检覆盖：Python 语法、配置加载、主题/贴纸注册表、主题与平台清单、一次真实 PNG 渲染、私有数据是否被 `.gitignore` 忽略、前端 JS 语法。

### CD：服务器侧拉取

可以给服务器配一个 webhook / 定时任务，或在 CI 的 `deploy` job 里 SSH 执行：

```bash
ssh deploy@server 'cd /opt/daily-card && git pull && ./install.sh --no-deps && sudo systemctl restart daily-card'
```

推荐节奏：CI 跑 `selfcheck.sh` → 通过后打 tag → tag 触发 CD 拉取 → 平台侧按 tag 重新导入 skill 快照。这样代码、服务器、skill 平台三条线都从同一个 tag 派生，不会各自漂移。

### skillhub 等平台的更新

平台存的是**快照**，不是实时同步：维护者打 tag / 推送提交后，需要在平台重新导入（re-import）才会生成新版本。所以它的版本天然滞后于服务器，这是正常的，不必强求对齐。

## 6. 排障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `找不到中文字体` | Linux 没装 Noto CJK | `apt install fonts-noto-cjk` 后 `fc-cache -fv` |
| 中文显示成方块 | 命中的字体不含中文字形 | 用 `--font` / `--font-bold` 指定 `.ttf/.ttc` |
| `/api/*` 连接被拒 | 没启动 `server.py`，或 CLI 误调 API | 先起服务；纯出图用 CLI 即可 |
| 上传大图失败 | 超过 24MB | 压缩图片；或同步调大 nginx `client_max_body_size` 与后端 `MAX_BODY` |
| 改了主题没生效 | 改的是出厂模板而非 `themes.json` | 确认 `DAILY_CARD_CONFIG` 指向的目录 |
| 升级后主题被重置 | 误用了 `--init-config` / 「恢复出厂主题」 | 从备份恢复 `themes.json`；升级本身不会覆盖 |
