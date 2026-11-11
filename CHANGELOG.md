# 更新记录

公开仓库为**单个干净初始提交**（历史重开），因此版本演进以本文件为准。

## 0.5.0 · 2026-11-11 · 同域名子路径部署与前后端解耦

面向「nginx 统一入口 + 同域名多服务 + `location /daily-card/`」的部署形态，改动集中在前端 URL 派生与部署层，**渲染逻辑与既有 API 路径不变**。

- 前端新增运行时 `BASE`：由 `document.baseURI` 推导，可用 `window.DAILY_CARD_BASE` 覆盖；`app.js` 的 10 处 API 路径与贴纸图标、以及 `index.html` 的静态资源全部改为相对派生，源码不再出现域名根绝对路径
- `server.py` 新增 `--api-only`（云部署只提供 API、不托管静态、禁用 `/api/reveal`）与 `GET /api/health`（回显版本/模式/配置目录）；`bootstrap` 增加 `mode` 字段；独立模式仍托管 `web/`，本地直连不受影响
- 新增 `scripts/publish-web.sh`：前端静态资源按版本目录发布、`current` 符号链接原子切换、`--rollback` 秒回滚、旧版本清理，附带 `manifest.json`
- 新增 `scripts/test_subpath.py`：进程内模拟 nginx 剥前缀 + 静态分离，回归 10 项链路断言
- `scripts/selfcheck.sh` 从 6 步扩到 8 步：新增硬编码路径检查、BASE 推导 4 组单测、子路径部署模拟
- `docs/DEPLOY.md` 重写：子路径部署为默认方案、新增「架构约定」章节、原独占域名配置降为附录；`SKILL.md` 同步补充运行模式与发布命令
- 前端可独立发版与回滚，不依赖 Python 服务重启

## 0.4.0 · 2026-11-11 · 公开发布准备

面向「仓库公开 + 多路并行 + 云服务器 + skill 收录」的打包层改造，**未改动任何渲染逻辑与后台代码**。

- 私有数据剥离：`config/themes.json`、`config/settings.json` 移出版本管理，本机保留；clone 后由 `ensure_config()` 从出厂模板自动初始化
- 去本机绝对路径：`SKILL.md` 改为可移植写法，支持任意安装位置
- 补齐 MIT `LICENSE`、`requirements.txt`、`VERSION`、`.env.example`、`README.md`、`config/README.md`
- 新增幂等 `install.sh`（依赖 / 私有配置 / 可选 skill 软链 / 自检）与 `scripts/selfcheck.sh`（CI 统一入口）
- 新增 `docs/DEPLOY.md`：部署、反代鉴权、systemd、更新与 CI/CD 接入说明
- `SKILL.md` 补充「两种可选后端」「更新与多端同步」章节，frontmatter 增加 license / version / compatibility
- `.gitignore` 增加私有配置、`.env`、虚拟环境与部署本地产物
- 仓库根即 skill 目录，符合 Agent Skills 规范，可被 GitHub 导入型平台识别

## 0.3.0 · 主题编辑实时预览

- 主题配置面板改为三栏，编辑中的**未保存草案**直接在服务端内存渲染，不写配置文件
- 新增 `cardpreview.py`：真实卡片预览、配色语义图、贴纸取色条、全量贴纸 sprite、WCAG 对比度诊断
- `config/stickers.json` 的 6 种纹样补充中文语义说明
- 修掉预览临时 PNG 堆积问题（用完即删）

## 0.2.0 · 配置外置 + 网页后台 + 多方案取色

- 主题表从代码搬到 `config/*.json`，运行时加载；「恢复默认」出厂模板分离
- 新增 `server.py` + `web/` 单页后台：卡片设计、主题配置、全局设置三个面板
- 新增 `cardconfig.py`：背景图分桶取色 + 色相去重，输出最多 4 套候选配色方案，可选序号或自定义主色
- 新增 `SKILL.md` 并注册到用户级 skills

## 0.1.0 · demo 基线

- `cardgen.py`：11 套主题、28 个手绘矢量贴纸、5 种平台尺寸、自动日期与落款
- 标题自动换行与字号选择、长文案自适应、超采样抗锯齿
- `--bg-image` 自定义背景取色、`--seed` 可复现构图、交互式问答
- 6 张示例成品图
