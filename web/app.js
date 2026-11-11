/* daily-card 网页工作台 —— 原生 JS，无构建、无外部依赖 */

/* 部署前缀属于运行时环境，不属于源码。
   同一份前端可挂在 / 或 /daily-card/ 等任意子路径；nginx 负责剥掉 API 前缀。
   需要把 API 指向独立域名时，可在加载本脚本前设置 window.DAILY_CARD_BASE。 */
const BASE = (window.DAILY_CARD_BASE || new URL(".", document.baseURI).href).replace(/\/+$/, "");
const url = (p) => BASE + "/" + String(p).replace(/^\/+/, "");

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const COLOR_LABELS = {
  bg1: "背景·上", bg2: "背景·下", card: "卡片底", ink: "主文字", sub: "副文字",
  accent: "强调色", accent2: "辅助色", soft: "柔和色", pill: "标签底", pill_text: "标签字",
};
const COLOR_KEYS = Object.keys(COLOR_LABELS);
const COLOR_HINTS = {
  bg1: "顶部渐变", bg2: "底部渐变", card: "承托文字", ink: "标题",
  sub: "副标题/日期", accent: "标签/贴纸", accent2: "第二层点缀",
  soft: "柔光色块", pill: "小标签底", pill_text: "小标签字",
};
const COLOR_ROLES = {
  bg1: "渐变起始色，画面最上方", bg2: "渐变结束色，画面最下方",
  card: "中央卡片底色，承托全部文字", ink: "标题颜色，最需要保证对比度",
  sub: "副标题、日期与辅助信息", accent: "标签、纹样与贴纸的主色",
  accent2: "纹样与贴纸的第二层点缀", soft: "大面积浅色块与柔光",
  pill: "卡片顶部小标签的底色", pill_text: "小标签上的文字颜色",
};
const MOTIF_FALLBACK = {
  circles: "大面积柔光圆叠加，温柔治愈", dots: "规则小圆点，秩序感强",
  grid: "细网格配角落光晕，理性克制", rays: "右上角放射线，有能量感",
  waves: "底部波浪层叠，舒缓流动", stars: "随机星点，夜晚氛围",
};

const S = {
  doc: null, settings: null, registry: null, platforms: {},
  current: null, colorValues: {}, pendingStickers: [],
  schemes: [], imageId: null, scheme: 0,
  lastPng: null, busy: false, reqId: 0, timer: null, toastTimer: null,
  pvReqId: 0, pvTimer: null, pvBusy: false, sheet: null,
};

/* ---------------------------------------------------------------- utils */

async function api(path, method = "GET", body) {
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opt.body = JSON.stringify(body);
  const r = await fetch(url(path), opt);
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok || (data && data.ok === false)) {
    throw new Error((data && data.error) || ("HTTP " + r.status));
  }
  return data;
}

function toast(msg, err = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("err", err);
  el.classList.add("show");
  clearTimeout(S.toastTimer);
  S.toastTimer = setTimeout(() => el.classList.remove("show"), 3000);
}

function localDate() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

/* ------------------------------------------------------------ bootstrap */

async function bootstrap() {
  const d = await api("api/bootstrap");
  S.doc = d.themes_doc;
  S.settings = d.settings;
  S.registry = d.registry;
  S.platforms = d.platforms;
  if (d.mode === "api-only") {
    const b = $("#btn-reveal");
    b.disabled = true;
    b.title = "远程模式不提供打开本机文件夹";
  }
  $("#config-path").textContent = "配置 " + d.config_dir + "  ·  输出 " + d.output_dir;

  fillPlatformSelects();
  fillThemeSelects();
  $("#cfg-motif").innerHTML = (S.registry.motifs || []).map(
    (m) => `<option value="${esc(m.id)}" title="${esc(m.desc || "")}">${esc(m.name)}</option>`).join("");
  S.current = Object.keys(S.doc.themes)[0];
  selectTheme(S.current, false);
  fillSettings();
  $("#f-date").value = localDate();
  $("#f-brand").value = S.settings.brand || "";
  $("#f-platform").value = S.settings.platform || "xhs";
  renderSchemes();
  bindEvents();
  const hash = location.hash.replace("#", "");
  activateTab(["design", "config", "settings"].includes(hash) ? hash : "design");
  renderPreview(false);
  renderThemePreview();
}

function activateTab(name) {
  $$(".tab").forEach((x) => x.classList.toggle("active", x.dataset.tab === name));
  $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === "panel-" + name));
  history.replaceState(null, "", "#" + name);
}

const SHORT_PLATFORM = {
  xhs: "小红书 3:4", moments: "朋友圈 1:1", wechat: "公众号横图",
  story: "竖屏 9:16", wechat2: "公众号首图",
};

function fillPlatformSelects() {
  const opts = Object.entries(S.platforms).map(([k, v]) =>
    `<option value="${k}" title="${esc(v.desc)}  ${v.w}×${v.h}">${esc(SHORT_PLATFORM[k] || k)}</option>`).join("");
  $("#f-platform").innerHTML = opts;
  $("#s-platform").innerHTML = opts;
  $("#cfg-pv-platform").innerHTML = opts;
  $("#cfg-pv-platform").value = "moments";
}

function fillThemeSelects() {
  const keep = $("#f-theme").value;
  const opts = `<option value="auto">自动识别（按关键词）</option>` +
    Object.entries(S.doc.themes).map(([k, t]) =>
      `<option value="${esc(k)}">${esc(t.label)}  [${esc(k)}]</option>`).join("");
  $("#f-theme").innerHTML = opts;
  if (keep && [...$("#f-theme").options].some((o) => o.value === keep)) {
    $("#f-theme").value = keep;
  }
}

function fillSettings() {
  $("#s-platform").value = S.settings.platform || "xhs";
  $("#s-brand").value = S.settings.brand || "";
  $("#s-supersample").value = S.settings.supersample ?? 2;
  $("#s-grain").value = S.settings.grain ?? 9;
  $("#s-output").value = S.settings.output_dir || "output";
  $("#s-scheme").value = S.settings.bg_scheme ?? 0;
  $("#s-auto-theme").checked = !!S.settings.auto_pick_theme;
}

/* ------------------------------------------------------- 主题编辑面板 */

function renderThemeList() {
  $("#theme-list").innerHTML = Object.entries(S.doc.themes).map(([k, t]) =>
    `<button class="theme-item ${k === S.current ? "on" : ""}" data-id="${esc(k)}">
       ${esc(t.label)}<small>${esc(k)} · ${(t.stickers || []).length} 个贴纸</small>
     </button>`).join("");
  $$(".theme-item").forEach((b) => b.addEventListener("click", () => selectTheme(b.dataset.id)));
}

function buildColorGrid(colors) {
  S.colorValues = Object.assign({}, colors);
  $("#color-grid").innerHTML = COLOR_KEYS.map((k) =>
    `<div class="color-item" title="${esc(COLOR_ROLES[k])}">
       <span>${COLOR_LABELS[k]}</span>
       <input type="color" data-k="${k}" value="${esc(colors[k])}">
       <input class="hex" data-k="${k}" value="${esc(colors[k])}" spellcheck="false">
       <small>${esc(COLOR_HINTS[k])}</small>
     </div>`).join("");
  $$("#color-grid input[type=color]").forEach((inp) => {
    inp.addEventListener("input", () => {
      S.colorValues[inp.dataset.k] = inp.value;
      const hex = $(`#color-grid input.hex[data-k="${inp.dataset.k}"]`);
      if (hex) hex.value = inp.value;
      scheduleThemePreview();
    });
  });
  $$("#color-grid input.hex").forEach((inp) => {
    // 逐字输入时，只要是合法色值就立即重绘，不必等到失焦
    inp.addEventListener("input", () => {
      const v = inp.value.trim();
      if (!/^#[0-9a-fA-F]{6}$/.test(v)) return;
      S.colorValues[inp.dataset.k] = v;
      const color = $(`#color-grid input[type=color][data-k="${inp.dataset.k}"]`);
      if (color) color.value = v;
      scheduleThemePreview();
    });
    inp.addEventListener("change", () => {
      const v = inp.value.trim();
      if (!/^#[0-9a-fA-F]{6}$/.test(v)) {
        toast("颜色需为 #RRGGBB 格式", true);
        inp.value = S.colorValues[inp.dataset.k];
        return;
      }
      S.colorValues[inp.dataset.k] = v;
      const color = $(`#color-grid input[type=color][data-k="${inp.dataset.k}"]`);
      if (color) color.value = v;
      scheduleThemePreview();
    });
  });
}

function buildStickerGrid(selected, themeId) {
  S.pendingStickers = [...(selected || [])];
  const groups = S.registry.groups || [];
  const list = S.registry.stickers || [];
  let html = "";
  const renderItem = (s) => {
    const on = S.pendingStickers.includes(s.id) ? "on" : "";
    const icon = url("api/sticker?id=" + encodeURIComponent(s.id) +
                     "&theme=" + encodeURIComponent(themeId) + "&size=72");
    return `<button type="button" class="sticker-item ${on}" data-id="${esc(s.id)}" title="${esc(s.id)}">
       <span class="sticker-icon"><img src="${icon}" alt=""></span>
       <span>${esc(s.name)}</span></button>`;
  };
  groups.forEach((g) => {
    const items = list.filter((s) => s.group === g);
    if (!items.length) return;
    html += `<div class="sticker-group-title">${esc(g)}</div>` + items.map(renderItem).join("");
  });
  const rest = list.filter((s) => !groups.includes(s.group));
  if (rest.length) html += `<div class="sticker-group-title">其他</div>` + rest.map(renderItem).join("");
  $("#sticker-grid").innerHTML = html;
  $("#sticker-count").textContent = `已选 ${S.pendingStickers.length} 个`;
  $$(".sticker-item").forEach((b) => b.addEventListener("click", () => {
    const id = b.dataset.id;
    const i = S.pendingStickers.indexOf(id);
    if (i >= 0) {
      if (S.pendingStickers.length === 1) return toast("至少保留一个贴纸", true);
      S.pendingStickers.splice(i, 1);
      b.classList.remove("on");
    } else {
      S.pendingStickers.push(id);
      b.classList.add("on");
    }
    $("#sticker-count").textContent = `已选 ${S.pendingStickers.length} 个`;
    scheduleThemePreview();
  }));
  applyStickerSheet();
}

function selectTheme(id, commit = true) {
  if (commit) commitEditor();
  if (!S.doc.themes[id]) return;
  S.current = id;
  const t = S.doc.themes[id];
  $("#cfg-id").value = id;
  $("#editing-id").textContent = "· " + id;
  $("#cfg-label").value = t.label || "";
  $("#cfg-keywords").value = (t.keywords || []).join(", ");
  $("#cfg-motif").value = t.motif || "circles";
  $("#cfg-dark").value = String(!!t.dark);
  buildColorGrid(t.colors || {});
  buildStickerGrid(t.stickers || [], id);
  renderThemeList();
  updateSemanticHints();
  scheduleThemePreview();
}

function commitEditor() {
  if (!S.current || !S.doc.themes[S.current]) return;
  const oldId = S.current;
  const newId = $("#cfg-id").value.trim().replace(/\s+/g, "_");
  const t = S.doc.themes[oldId];
  const updated = {
    label: $("#cfg-label").value.trim() || oldId,
    keywords: $("#cfg-keywords").value.split(/[,，\n]/).map((s) => s.trim()).filter(Boolean),
    motif: $("#cfg-motif").value,
    dark: $("#cfg-dark").value === "true",
    colors: Object.assign({}, t.colors, S.colorValues),
    stickers: [...S.pendingStickers],
  };
  let finalId = oldId;
  if (newId && newId !== oldId) {
    if (S.doc.themes[newId]) {
      toast("主题 ID 已存在，本次未改名", true);
    } else {
      delete S.doc.themes[oldId];
      finalId = newId;
    }
  }
  S.doc.themes[finalId] = updated;
  S.current = finalId;
  $("#cfg-id").value = finalId;
  $("#editing-id").textContent = "· " + finalId;
}

async function saveConfig() {
  commitEditor();
  try {
    const r = await api("api/config/themes", "POST", { themes_doc: S.doc });
    toast(r.message || "配置已保存");
    fillThemeSelects();
    renderThemeList();
    renderPreview(false);
  } catch (e) { toast(e.message, true); }
}

/* ------------------------------------------- 主题草案：未保存也能看效果 */

function draftTheme() {
  const t = S.doc.themes[S.current] || {};
  return {
    label: $("#cfg-label").value.trim() || S.current,
    keywords: $("#cfg-keywords").value.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean),
    motif: $("#cfg-motif").value,
    dark: $("#cfg-dark").value === "true",
    colors: Object.assign({}, t.colors || {}, S.colorValues),
    stickers: [...S.pendingStickers],
  };
}

function updateSemanticHints() {
  const m = (S.registry.motifs || []).find((x) => x.id === $("#cfg-motif").value);
  $("#motif-hint").textContent = m
    ? `纹样「${m.name}」：${m.desc || MOTIF_FALLBACK[m.id] || "背景铺底纹理"}`
    : "";
  const dark = $("#cfg-dark").value === "true";
  $("#dark-hint").textContent = dark
    ? "深色主题：蒙版与卡片按暗色处理，ink 建议用浅色、pill_text 用深色。"
    : "浅色主题：蒙版与卡片按亮色处理，ink 建议用深色，背景不宜过暗。";
}

function scheduleThemePreview() {
  if (!$("#cfg-pv-auto").checked) return;
  clearTimeout(S.pvTimer);
  S.pvTimer = setTimeout(renderThemePreview, 380);
}

async function renderThemePreview() {
  clearTimeout(S.pvTimer);
  if (!S.current || !S.doc) return;
  const payload = {
    theme: draftTheme(),
    title: $("#cfg-pv-title").value.trim() || "把普通的日子，过得响亮一点",
    subtitle: $("#cfg-pv-subtitle").value.trim() || "这句是副标题，用来预览文字层级",
    platform: $("#cfg-pv-platform").value || "moments",
    date: localDate(),
    brand: "",
    seed: 7,                     // 固定构图，调色时方便前后对比
  };
  const myId = ++S.pvReqId;
  const state = $("#cfg-pv-state");
  state.textContent = "绘制中";
  $("#cfg-loading").hidden = false;
  try {
    const r = await api("api/theme-preview", "POST", payload);
    if (myId !== S.pvReqId) return;         // 丢弃过期响应
    const card = $("#cfg-card");
    card.src = r.card;
    card.style.display = "block";
    $("#cfg-legend").src = r.legend;
    $("#cfg-stickers").src = r.stickers;
    S.sheet = r;
    applyStickerSheet();
    renderDiagnostics(r.diagnostics, r.contrast);
    $("#cfg-meta").textContent =
      `${r.size[0]} × ${r.size[1]} · ${r.motif.name} · ${r.dark ? "深色" : "浅色"}主题 · 草稿预览`;
    const warns = (r.diagnostics || []).filter((x) => x.level === "warn").length;
    state.textContent = warns ? `${warns} 项提醒` : "草稿 · 未落盘";
    state.classList.toggle("warn-badge", !!warns);
    $("#motif-hint").textContent =
      `纹样「${r.motif.name}」：${r.motif.desc || MOTIF_FALLBACK[r.motif.id] || "背景铺底纹理"}`;
  } catch (e) {
    if (myId === S.pvReqId) {
      state.textContent = "预览失败";
      $("#cfg-meta").textContent = e.message;
    }
  } finally {
    if (myId === S.pvReqId) $("#cfg-loading").hidden = true;
  }
}

function applyStickerSheet() {
  const r = S.sheet;
  if (!r || !r.sheet || !r.sticker_sheet) return;
  const D = 44;                              // 网格里图标的显示边长
  const index = {};
  (r.sheet.order || []).forEach((id, i) => { index[id] = i; });
  $$(".sticker-item").forEach((b) => {
    const i = index[b.dataset.id];
    if (i === undefined) return;
    const icon = b.querySelector(".sticker-icon");
    if (!icon) return;
    icon.style.backgroundImage = `url("${r.sticker_sheet}")`;
    icon.style.backgroundSize = `${r.sheet.cols * D}px ${r.sheet.rows * D}px`;
    icon.style.backgroundPosition =
      `-${(i % r.sheet.cols) * D}px -${Math.floor(i / r.sheet.cols) * D}px`;
    const img = icon.querySelector("img");
    if (img) img.hidden = true;
  });
}

function renderDiagnostics(items, contrast) {
  const list = items || [];
  $("#cfg-diag").innerHTML = list.length
    ? list.map((it) =>
        `<div class="diag ${esc(it.level)}"><i></i><span>${esc(it.text)}</span></div>`).join("")
    : `<div class="diag ok"><i></i><span>没有发现问题</span></div>`;
  $("#cfg-contrast").textContent = contrast
    ? `主文字 ${contrast.ink_card}:1 · 副文字 ${contrast.sub_card}:1 · 背景亮度 ${Math.round(contrast.bg_light * 100)}%`
    : "";
}

/* ------------------------------------------------------------- 设计页 */

function designPayload() {
  const darkVal = $("#f-dark").value;
  return {
    title: $("#f-title").value.trim(),
    subtitle: $("#f-subtitle").value.trim(),
    platform: $("#f-platform").value,
    theme: $("#f-theme").value || "auto",
    date: $("#f-date").value || null,
    brand: $("#f-brand").value.trim(),
    seed: $("#f-seed").value === "" ? null : $("#f-seed").value,
    bg_image_id: S.imageId,
    bg_scheme: S.imageId ? S.scheme : 0,
    dark_override: darkVal === "" ? null : darkVal === "true",
  };
}

function renderSchemes() {
  if (!S.schemes.length) { $("#scheme-list").innerHTML = ""; return; }
  $("#scheme-list").innerHTML = S.schemes.map((sc, i) => {
    const on = S.scheme === i ? "on" : "";
    const sw = ["accent", "accent2", "soft", "bg2", "card"]
      .map((k) => `<i style="background:${sc.colors[k]}"></i>`).join("");
    return `<button class="scheme-card ${on}" data-i="${i}">
       <span class="name">${esc(sc.name)}</span>
       <span class="swatches">${sw}</span>
       <span class="base">${esc(sc.base)} · 占比 ${Math.round((sc.ratio || 0) * 100)}%</span>
     </button>`;
  }).join("");
  $$(".scheme-card").forEach((b) => b.addEventListener("click", () => {
    S.scheme = Number(b.dataset.i);
    renderSchemes();
    renderPreview(false);
  }));
}

async function renderPreview(save = false) {
  const p = designPayload();
  if (!p.title) { toast("标题不能为空", true); return; }
  const myId = ++S.reqId;
  S.busy = true;
  $("#preview-loading").hidden = false;
  try {
    const r = await api(save ? "api/save" : "api/render", "POST", p);
    if (myId !== S.reqId) return;               // 丢弃过期响应
    S.lastPng = r.png;
    const img = $("#preview-img");
    img.src = r.png;
    img.style.display = "block";
    const schemeTxt = S.imageId
      ? ` · 配色 ${typeof S.scheme === "number" ? "方案 " + (S.scheme + 1) : "自定义主色"}` : "";
    $("#preview-meta").textContent =
      `${r.size[0]} × ${r.size[1]}  ·  主题 ${r.theme}${schemeTxt}  ·  ${Math.round(r.bytes / 1024)} KB`;
    if (save) toast("已保存：" + r.path);
  } catch (e) {
    if (myId === S.reqId) toast(e.message, true);
  } finally {
    if (myId === S.reqId) { S.busy = false; $("#preview-loading").hidden = true; }
  }
}

function schedulePreview() {
  if (!$("#f-auto").checked) return;
  clearTimeout(S.timer);
  S.timer = setTimeout(() => renderPreview(false), 650);
}

/* -------------------------------------------------------------- events */

function bindEvents() {
  $$(".tab").forEach((t) => t.addEventListener("click", () => {
    activateTab(t.dataset.tab);
    if (t.dataset.tab === "config" && !S.sheet) renderThemePreview();
  }));

  $$(".form-panel input, .form-panel select, .form-panel textarea").forEach((el) => {
    if (el.id === "f-bg") return;
    el.addEventListener("input", schedulePreview);
    el.addEventListener("change", schedulePreview);
  });

  $("#btn-render").addEventListener("click", () => renderPreview(false));
  $("#btn-save").addEventListener("click", () => renderPreview(true));
  $("#btn-download").addEventListener("click", () => {
    if (!S.lastPng) return toast("请先生成预览", true);
    const a = document.createElement("a");
    a.href = S.lastPng;
    a.download = "daily-card-" + localDate() + ".png";
    document.body.appendChild(a); a.click(); a.remove();
  });
  $("#btn-reveal").addEventListener("click", async () => {
    try { await api("api/reveal", "POST", {}); toast("已打开输出文件夹"); }
    catch (e) { toast(e.message, true); }
  });

  // 背景图上传 → 提取候选配色方案
  $("#f-bg").addEventListener("change", (e) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = async () => {
      $("#bg-name").textContent = "正在分析配色…";
      try {
        const r = await api("api/schemes", "POST", { image: reader.result });
        S.imageId = r.image_id;
        S.schemes = r.schemes;
        S.scheme = 0;
        $("#bg-name").textContent = f.name + " · " + r.schemes.length + " 套方案";
        const thumb = $("#bg-thumb");
        thumb.src = reader.result;
        thumb.hidden = false;
        renderSchemes();
        renderPreview(false);
      } catch (err) { toast(err.message, true); $("#bg-name").textContent = "上传失败"; }
    };
    reader.readAsDataURL(f);
  });
  $("#bg-clear").addEventListener("click", () => {
    S.imageId = null; S.schemes = []; S.scheme = 0;
    $("#f-bg").value = "";
    $("#bg-thumb").hidden = true;
    $("#bg-name").textContent = "未使用背景图";
    renderSchemes();
    renderPreview(false);
  });
  $("#btn-custom-color").addEventListener("click", () => {
    if (!S.imageId) return toast("请先选择背景图", true);
    S.scheme = $("#f-base-color").value;
    renderSchemes();
    toast("已套用自定义主色");
    renderPreview(false);
  });

  // 主题编辑：任何字段变化都刷新右侧草案预览（含未保存的修改）
  $$(".theme-editor input, .theme-editor select, .theme-editor textarea").forEach((el) => {
    el.addEventListener("input", () => { updateSemanticHints(); scheduleThemePreview(); });
    el.addEventListener("change", () => { updateSemanticHints(); scheduleThemePreview(); });
  });
  $$(".cfg-pv-tools input, .cfg-pv-tools select").forEach((el) => {
    el.addEventListener("input", scheduleThemePreview);
    el.addEventListener("change", scheduleThemePreview);
  });
  $("#btn-cfg-refresh").addEventListener("click", renderThemePreview);
  $("#btn-cfg-download").addEventListener("click", () => {
    if (!S.sheet || !S.sheet.card) return toast("请先等待预览生成", true);
    const a = document.createElement("a");
    a.href = S.sheet.card;
    a.download = "theme-draft-" + localDate() + ".png";
    document.body.appendChild(a); a.click(); a.remove();
  });

  // 配置管理
  $("#btn-save-config").addEventListener("click", saveConfig);
  $("#btn-theme-add").addEventListener("click", () => {
    commitEditor();
    let id = "mytheme", n = 1;
    while (S.doc.themes[id]) { n += 1; id = "mytheme" + n; }
    const base = JSON.parse(JSON.stringify(S.doc.themes[S.current]));
    base.label = "MY THEME · 新主题";
    base.keywords = [];
    S.doc.themes[id] = base;
    selectTheme(id, false);
    fillThemeSelects();
    toast("已新增主题，改完请点「保存配置」");
  });
  $("#btn-theme-del").addEventListener("click", () => {
    if (Object.keys(S.doc.themes).length <= 1) return toast("至少保留一个主题", true);
    if (!confirm("确定删除主题「" + S.current + "」？保存配置后生效。")) return;
    delete S.doc.themes[S.current];
    S.current = Object.keys(S.doc.themes)[0];
    selectTheme(S.current, false);
    fillThemeSelects();
    toast("已删除，记得保存配置");
  });
  $("#btn-reset").addEventListener("click", async () => {
    if (!confirm("恢复出厂主题会覆盖当前 themes.json，确定继续？")) return;
    try {
      const r = await api("api/config/reset", "POST", {});
      S.doc = r.themes_doc;
      S.current = Object.keys(S.doc.themes)[0];
      selectTheme(S.current, false);
      fillThemeSelects();
      renderPreview(false);
      toast(r.message);
    } catch (e) { toast(e.message, true); }
  });
  $("#btn-export").addEventListener("click", () => {
    commitEditor();
    const blob = new Blob([JSON.stringify(S.doc, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "themes.json";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });

  // 全局设置
  $("#btn-save-settings").addEventListener("click", async () => {
    const patch = {
      platform: $("#s-platform").value,
      brand: $("#s-brand").value,
      supersample: Number($("#s-supersample").value) || 2,
      grain: Number($("#s-grain").value),
      output_dir: $("#s-output").value.trim() || "output",
      bg_scheme: Number($("#s-scheme").value) || 0,
      auto_pick_theme: $("#s-auto-theme").checked,
    };
    try {
      const r = await api("api/config/settings", "POST", { settings: patch });
      S.settings = Object.assign(S.settings, patch);
      $("#settings-hint").textContent = "已保存 " + new Date().toLocaleTimeString();
      toast(r.message || "设置已保存");
    } catch (e) { toast(e.message, true); }
  });
}

bootstrap().catch((e) => toast("初始化失败：" + e.message, true));
