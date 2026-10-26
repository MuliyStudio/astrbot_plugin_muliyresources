/* =========================================================
   暮黎资源聚合 · 可视化配置页
   通过 AstrBot 插件页面 bridge 读写配置，不依赖任何前端框架
   ========================================================= */

const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
const app = document.getElementById("app");
const toastEl = document.getElementById("toast");

const state = {
  ready: false,
  loading: true,
  saving: false,
  fatal: "",
  meta: null,
  groups: [],
  values: {},
  baseline: {},
  dirty: new Set(),
  active: "overview",
  query: "",
  ctx: {},
};

let refs = {};
let fieldIndex = new Map();
let groupMap = new Map();
let conditionWatchers = new Set();
let globalListenersBound = false;
let contextBound = false;

const PRIMARY_TOGGLE = {
  list_card: { key: "list_card_enabled", on: "图片已开", off: "图片已关" },
  minigame: { key: "minigame_enabled", on: "已启用", off: "已关闭" },
  game: { key: "game_report_enabled", on: "日报已开", off: "日报已关" },
  movie: { key: "movie_report_enabled", on: "日报已开", off: "日报已关" },
  shortdrama: { key: "drama_enabled", on: "搜索已开", off: "搜索已关" },
  music: { key: "wyy_auto_parse", on: "名片已开", off: "名片已关" },
  vip_video: { key: "video_vip_parse", on: "已启用", off: "已关闭" },
  verify: { key: "join_verify_enabled", on: "已启用", off: "已关闭" },
  points: { key: "points_enabled", on: "积分已开", off: "积分已关" },
};

const FEATURE_TOGGLES = {
  list_card: "list_card_enabled",
  points: "points_enabled",
  music: "wyy_auto_parse",
  vip_video: "video_vip_parse",
  verify: "join_verify_enabled",
  minigame: "minigame_enabled",
};

const ICON_PATHS = {
  apps: '<path d="M4 8h4V4H4v4zm6 12h4v-4h-4v4zm-6 0h4v-4H4v4zm0-6h4v-4H4v4zm6 0h4v-4h-4v4zm6-10v4h4V4h-4zm-6 4h4V4h-4v4zm6 6h4v-4h-4v4zm0 6h4v-4h-4v4z"/>',
  gamepad:
    '<path d="M21.58 16.09l-1.09-7.66C20.21 6.46 18.52 5 16.53 5H7.47C5.48 5 3.79 6.46 3.51 8.43l-1.09 7.66C2.2 17.63 3.39 19 4.94 19c.68 0 1.32-.27 1.8-.75L9 16h6l2.25 2.25c.48.48 1.13.75 1.8.75 1.56 0 2.75-1.37 2.53-2.91zM11 11H9v2H8v-2H6v-1h2V8h1v2h2v1zm4-1c-.55 0-1-.45-1-1s.45-1 1-1 1 .45 1 1-.45 1-1 1zm2 3c-.55 0-1-.45-1-1s.45-1 1-1 1 .45 1 1-.45 1-1 1z"/>',
  package:
    '<path d="M20.54 5.23l-1.39-1.68C18.88 3.21 18.47 3 18 3H6c-.47 0-.88.21-1.16.55L3.46 5.23C3.17 5.57 3 6.02 3 6.5V19c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V6.5c0-.48-.17-.93-.46-1.27zM12 17.5L6.5 12H10v-2h4v2h3.5L12 17.5zM5.12 5l.81-1h12l.94 1H5.12z"/>',
  movie:
    '<path d="M18 4l2 4h-3l-2-4h-2l2 4h-3l-2-4H8l2 4H7L5 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4h-4z"/>',
  tv: '<path d="M21 6h-7.59l3.29-3.29L16 2l-4 4-4-4-.71.71L10.59 6H3c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm0 14H3V8h18v12zM9 10v8l7-4z"/>',
  book: '<path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/>',
  music: '<path d="M12 3v10.55A4 4 0 1014 17V7h4V3h-6z"/>',
  play: '<path d="M8 5v14l11-7z"/>',
  star: '<path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"/>',
  verified:
    '<path d="M23 12l-2.44-2.79.34-3.69-3.61-.82-1.89-3.2L12 2.96 8.6 1.5 6.71 4.69 3.1 5.5l.34 3.7L1 12l2.44 2.79-.34 3.7 3.61.82 1.89 3.2L12 21.04l3.4 1.46 1.89-3.19 3.61-.82-.34-3.69L23 12z"/>',
  casino:
    '<path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM7.5 18a1.5 1.5 0 110-3 1.5 1.5 0 010 3zm0-9a1.5 1.5 0 110-3 1.5 1.5 0 010 3zm4.5 4.5a1.5 1.5 0 110-3 1.5 1.5 0 010 3zm4.5 4.5a1.5 1.5 0 110-3 1.5 1.5 0 010 3zm0-9a1.5 1.5 0 110-3 1.5 1.5 0 010 3z"/>',
  image:
    '<path d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z"/>',
  globe:
    '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>',
  search:
    '<path d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>',
  save: '<path d="M17 3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V7l-4-4zm-5 16c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3zm3-10H5V5h10v4z"/>',
  refresh:
    '<path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>',
  undo: '<path d="M12.5 8c-2.65 0-5.05.99-6.9 2.6L2 7v9h9l-3.62-3.62c1.39-1.16 3.16-1.88 5.12-1.88 3.54 0 6.55 2.31 7.6 5.5l2.37-.78C21.08 11.03 17.15 8 12.5 8z"/>',
  eye: '<path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17a5 5 0 110-10 5 5 0 010 10zm0-8a3 3 0 100 6 3 3 0 000-6z"/>',
  eyeOff:
    '<path d="M12 6.5c2.76 0 5 2.24 5 5 0 .51-.1 1-.24 1.46l3.06 3.06c1.39-1.23 2.49-2.77 3.18-4.53C21.27 7.11 17 4 12 4c-1.27 0-2.49.2-3.64.57l2.17 2.17c.47-.14.96-.24 1.47-.24zM2.71 3.16L1.39 4.47l2.17 2.17C2.19 7.8 1.01 9.78 1 12c1.73 4.39 6 7.5 11 7.5 1.55 0 3.03-.3 4.38-.84l.42.42L18.07 20l1.31-1.31L2.71 3.16zM12 17c-2.76 0-5-2.24-5-5 0-.77.18-1.5.49-2.14l1.57 1.57c-.03.18-.06.37-.06.57a3 3 0 003 3c.2 0 .38-.03.57-.07l1.57 1.57c-.65.32-1.37.5-2.14.5z"/>',
  chevron:
    '<path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/>',
  check: '<path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>',
  close:
    '<path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>',
  copy: '<path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>',
  clock:
    '<path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20a8 8 0 110-16 8 8 0 010 16zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z"/>',
  server:
    '<path d="M4 1h16c1.1 0 2 .9 2 2v4c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V3c0-1.1.9-2 2-2zm0 12h16c1.1 0 2 .9 2 2v4c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2v-4c0-1.1.9-2 2-2zM6 4v2h2V4H6zm0 12v2h2v-2H6z"/>',
  folder:
    '<path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/>',
  info: '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/>',
  warning: '<path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>',
  spark:
    '<path d="M19 9l1.25-2.75L23 5l-2.75-1.25L19 1l-1.25 2.75L15 5l2.75 1.25L19 9zm-7.5.5L9 4 6.5 9.5 1 12l5.5 2.5L9 20l2.5-5.5L17 12l-5.5-2.5zM19 15l-1.25 2.75L15 19l2.75 1.25L19 23l1.25-2.75L23 19l-2.75-1.25L19 15z"/>',
  settings:
    '<path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 00.12-.61l-1.92-3.32a.488.488 0 00-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.484.484 0 00-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58a.49.49 0 00-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/>',
  puzzle:
    '<path d="M20.5 11H19V7c0-1.1-.9-2-2-2h-4V3.5C13 2.12 11.88 1 10.5 1S8 2.12 8 3.5V5H4c-1.1 0-2 .9-2 2v3.8h1.5c1.49 0 2.7 1.21 2.7 2.7s-1.21 2.7-2.7 2.7H2V20c0 1.1.9 2 2 2h3.8v-1.5c0-1.49 1.21-2.7 2.7-2.7s2.7 1.21 2.7 2.7V22H17c1.1 0 2-.9 2-2v-4h1.5c1.38 0 2.5-1.12 2.5-2.5S21.88 11 20.5 11z"/>',
  arrow: '<path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/>',
  bolt: '<path d="M11 21h-1l1-7H7.5c-.58 0-.57-.32-.38-.66.19-.34.05-.08.07-.12C8.48 10.94 10.42 7.54 13 3h1l-1 7h3.5c.49 0 .56.33.47.51l-.07.15C12.96 17.55 11 21 11 21z"/>',
};

/* ---------- 基础工具 ---------- */

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function")
      node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (
      key === "for" ||
      key === "role" ||
      key.startsWith("aria-") ||
      key.startsWith("data-")
    )
      node.setAttribute(key, value === true ? "" : String(value));
    else if (key in node) {
      try {
        node[key] = value;
      } catch {
        node.setAttribute(key, String(value));
      }
    } else node.setAttribute(key, value === true ? "" : String(value));
  }
  append(node, children);
  return node;
}

function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

function icon(name, size = 18, cls = "") {
  return `<svg class="icon ${cls}" viewBox="0 0 24 24" width="${size}" height="${size}" fill="currentColor" aria-hidden="true">${
    ICON_PATHS[name] || ICON_PATHS.apps
  }</svg>`;
}

function clone(value) {
  if (value === undefined) return undefined;
  return JSON.parse(JSON.stringify(value));
}

function same(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function tr(key, fallback) {
  try {
    return bridge && typeof bridge.t === "function" ? bridge.t(key, fallback) : fallback;
  } catch {
    return fallback;
  }
}

function viewTitle() {
  return tr("views.config.title", tr("pages.config.title", "暮黎资源聚合控制台"));
}

function applyTheme() {
  document.documentElement.dataset.theme = state.ctx && state.ctx.isDark ? "dark" : "light";
}

function unwrap(res) {
  if (res && typeof res === "object" && res.status === "error") {
    throw new Error(res.message || "请求失败");
  }
  if (res && typeof res === "object" && res.status === "ok" && "data" in res) {
    return res.data;
  }
  return res;
}

async function apiGet(endpoint, params) {
  const raw = await bridge.apiGet(endpoint, params || {});
  return unwrap(raw);
}

async function apiPost(endpoint, body) {
  const raw = await bridge.apiPost(endpoint, body || {});
  return unwrap(raw);
}

let toastTimer = 0;
function toast(message, kind = "info") {
  toastEl.textContent = message;
  toastEl.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    toastEl.className = "toast";
  }, 3200);
}

function isTypingTarget(target) {
  if (!target) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    target.isContentEditable
  );
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("已复制到剪贴板", "success");
  } catch {
    try {
      const ta = h("textarea", { style: "position:fixed;left:-9999px;top:0" });
      ta.value = text;
      document.body.append(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      toast("已复制到剪贴板", "success");
    } catch {
      toast("复制失败，请手动选择文本", "error");
    }
  }
}

/* ---------- 启动 / 错误 ---------- */

function renderFatal(title, message, detail = "") {
  app.replaceChildren(
    h(
      "div",
      { class: "fatal-wrap" },
      h(
        "div",
        { class: "fatal-card" },
        h("div", { class: "fatal-icon", html: icon("warning", 28) }),
        h("h1", { text: title }),
        h("p", { text: message }),
        detail ? h("div", { class: "detail", text: detail }) : null,
        h(
          "button",
          {
            class: "btn primary",
            type: "button",
            onClick: () => init(),
          },
          h("span", { html: icon("refresh", 16) }),
          "重新加载"
        )
      )
    )
  );
}

function renderBoot() {
  app.replaceChildren(
    h(
      "div",
      { class: "boot" },
      h("div", { class: "boot-logo" }, h("img", { src: "./assets/logo.png", alt: "" })),
      h("div", { class: "boot-spinner", "aria-hidden": "true" }),
      h("p", { text: "正在读取配置…" })
    )
  );
}

/* ---------- 数据 ---------- */

async function loadConfig() {
  const data = await apiGet("config-view");
  if (!data || !Array.isArray(data.groups)) {
    throw new Error("后端返回的数据格式不正确，请重载插件后重试");
  }
  state.groups = data.groups;
  state.meta = data.meta || {};
  state.values = {};
  state.baseline = {};
  state.dirty.clear();
  fieldIndex = new Map();
  groupMap = new Map();
  conditionWatchers = new Set();
  for (const group of state.groups) {
    groupMap.set(group.key, group);
    for (const field of group.fields || []) {
      state.values[field.key] = clone(field.value);
      fieldIndex.set(field.key, field);
      for (const dep of Object.keys(field.condition || {})) {
        conditionWatchers.add(dep);
      }
    }
  }
  state.baseline = clone(state.values);
  if (state.active !== "overview" && !groupMap.has(state.active)) {
    state.active = "overview";
  }
  state.ready = true;
  state.loading = false;
}

/* ---------- 顶栏 / 侧栏 ---------- */

function mountShell() {
  const searchInput = h("input", {
    class: "search-input",
    type: "search",
    placeholder: "搜索配置项，如 Cookie、群号、日报…",
    "aria-label": "搜索配置项",
    autocomplete: "off",
    spellcheck: false,
  });
  searchInput.addEventListener("input", () => {
    state.query = searchInput.value.trim();
    renderSidebar();
    renderMain();
    updateChrome();
  });
  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      searchInput.value = "";
      state.query = "";
      renderSidebar();
      renderMain();
      updateChrome();
      searchInput.blur();
    }
  });

  const reloadBtn = h(
    "button",
    {
      class: "btn ghost",
      type: "button",
      title: "放弃未保存的修改并重新读取",
      onClick: () => reloadConfig(),
    },
    h("span", { html: icon("refresh", 16) }),
    h("span", { class: "btn-label", text: "重新读取" })
  );

  const saveBtn = h(
    "button",
    {
      class: "btn primary",
      type: "button",
      title: "保存修改（Ctrl/⌘ + S）",
      onClick: () => saveConfig(),
    },
    h("span", { html: icon("save", 16) }),
    h("span", { class: "btn-label", text: "保存" })
  );

  const topbar = h(
    "header",
    { class: "topbar" },
    h(
      "div",
      { class: "topbar-inner" },
      h(
        "div",
        { class: "brand" },
        h("img", { class: "brand-logo", src: "./assets/logo.png", alt: "" }),
        h(
          "div",
          { class: "brand-text" },
          h("h1", { id: "pageTitle", text: viewTitle() }),
          h(
            "p",
            {},
            h("span", {
              class: "version-chip",
              text: state.meta && state.meta.version ? `v${state.meta.version}` : "v—",
            }),
            h("span", {
              text: (state.meta && state.meta.display_name) || "暮黎资源聚合",
            })
          )
        )
      ),
      h(
        "div",
        { class: "top-actions" },
        h(
          "div",
          { class: "search-box" },
          h("span", { html: icon("search", 16) }),
          searchInput,
          h("kbd", { text: "/" })
        ),
        reloadBtn,
        saveBtn
      )
    )
  );

  const sideScroll = h("div", { class: "side-scroll" });
  const sideFoot = h("div", { class: "side-foot" });
  const sidebar = h("aside", { class: "sidebar" }, sideScroll, sideFoot);
  const main = h("main", { class: "main" });

  const savebar = h(
    "div",
    { class: "savebar", role: "region", "aria-label": "未保存的修改" },
    h(
      "div",
      { class: "savebar-text" },
      h("span", { id: "savebarCount", text: "有 0 项修改未保存" }),
      h("small", { text: "保存后立即写入插件配置，部分设置会立即生效" })
    ),
    h(
      "button",
      {
        class: "btn ghost",
        type: "button",
        onClick: () => discardChanges(),
      },
      h("span", { html: icon("undo", 16) }),
      h("span", { class: "btn-label", text: "撤销" })
    ),
    h(
      "button",
      {
        class: "btn primary",
        type: "button",
        onClick: () => saveConfig(),
      },
      h("span", { html: icon("save", 16) }),
      h("span", { class: "btn-label", text: "全部保存" })
    )
  );

  app.replaceChildren(topbar, h("div", { class: "layout" }, sidebar, main), savebar);

  refs = { searchInput, reloadBtn, saveBtn, sideScroll, sideFoot, main, savebar };

  if (globalListenersBound) return;
  globalListenersBound = true;
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      saveConfig();
      return;
    }
    if (event.key === "/" && !isTypingTarget(event.target)) {
      event.preventDefault();
      if (refs.searchInput) refs.searchInput.focus();
      return;
    }
  });

  window.addEventListener("beforeunload", (event) => {
    if (!state.dirty.size) return;
    event.preventDefault();
    event.returnValue = "";
  });
}

function renderSidebar() {
  const total = state.meta && state.meta.field_count ? state.meta.field_count : countFields();
  refs.sideScroll.replaceChildren(
    h(
      "button",
      {
        class: `nav-item${state.active === "overview" && !state.query ? " active" : ""}`,
        type: "button",
        "data-nav": "overview",
        onClick: () => navigate("overview"),
      },
      h("span", { html: icon("apps", 17) }),
      h("span", { class: "nav-text", text: "总览" }),
      h("span", { class: "nav-count", text: String(total) })
    ),
    h("div", { class: "nav-divider", text: "功能配置" }),
    ...state.groups.map((group) =>
      h(
        "button",
        {
          class: `nav-item${state.active === group.key && !state.query ? " active" : ""}`,
          type: "button",
          "data-nav": group.key,
          onClick: () => navigate(group.key),
        },
        h("span", { html: icon(group.icon || "apps", 17) }),
        h("span", { class: "nav-text", text: group.title }),
        h("span", { class: "nav-count", text: String((group.fields || []).length) }),
        h("span", {
          class: "nav-dirty",
          hidden: !isGroupDirty(group),
          title: "有未保存的修改",
        })
      )
    )
  );

  const meta = state.meta || {};
  const running = !!meta.scheduler_running;
  refs.sideFoot.replaceChildren(
    h(
      "div",
      { class: "mini-status" },
      h("span", { class: `status-dot${running ? " on" : ""}` }),
      h("span", {
        text: `定时任务 ${running ? "运行中" : "未启动"} · ${modeLabel(meta.scheduler_mode)}`,
      })
    )
  );
}

function navigate(target) {
  state.active = target;
  state.query = "";
  if (refs.searchInput) refs.searchInput.value = "";
  render();
  window.scrollTo(0, 0);
}

/* ---------- 主区域 ---------- */

function render() {
  if (!state.ready) return;
  const active = document.activeElement;
  if (active && active !== document.body && refs.main && refs.main.contains(active)) {
    active.blur();
  }
  renderSidebar();
  renderMain();
  updateChrome();
}

function renderMain() {
  if (!refs.main) return;
  const scrollY = window.scrollY;
  refs.main.replaceChildren();
  if (state.query) {
    refs.main.append(renderSearchResults());
  } else if (state.active === "overview" || !groupMap.has(state.active)) {
    refs.main.append(renderOverview());
  } else {
    refs.main.append(renderGroup(groupMap.get(state.active)));
  }
  refreshConditions();
  window.scrollTo(0, scrollY);
}

function renderOverview() {
  const meta = state.meta || {};
  const fields = countFields();
  const features = (meta.features || []).map((feature) => {
    const toggleKey = FEATURE_TOGGLES[feature.key];
    if (toggleKey && fieldIndex.has(toggleKey)) {
      return { ...feature, enabled: Boolean(state.values[toggleKey]) };
    }
    return feature;
  });
  const enabled = features.filter((f) => f.enabled).length;
  const fragment = document.createDocumentFragment();

  fragment.append(
    h(
      "div",
      { class: "page-head" },
      h(
        "div",
        {},
        h("h2", { text: "总览" }),
        h("p", { text: "所有配置集中在这里，修改后点右上角「保存」即可。" })
      ),
      h(
        "div",
        { class: "page-head-badges" },
        h("span", { class: "pill accent", text: `${meta.group_count || state.groups.length} 个分组` }),
        h("span", { class: "pill", text: `${fields} 项配置` })
      )
    )
  );

  fragment.append(
    h(
      "section",
      { class: "hero" },
      h(
        "div",
        { class: "hero-brand" },
        h("img", { src: "./assets/logo.png", alt: "" }),
        h(
          "div",
          {},
          h("h2", { text: meta.display_name || "暮黎资源聚合" }),
          h("p", {
            text: meta.description || "影视 / 游戏 / 软件 / 短剧 / 小说 多源搜索与定时日报",
          }),
          h(
            "div",
            { class: "hero-tags" },
            h("span", { class: "tag", text: `v${meta.version || "—"}` }),
            h("span", { class: "tag", text: `时区 ${meta.timezone || "系统本地"}` }),
            h(
              "span",
              { class: "tag" },
              h("span", { class: `status-dot${meta.scheduler_running ? " on" : ""}` }),
              `调度${meta.scheduler_running ? "运行中" : "未启动"}`
            )
          )
        )
      ),
      h(
        "div",
        { class: "hero-stats" },
        h("div", {}, h("strong", { text: String(meta.group_count || state.groups.length) }), h("span", { text: "配置分组" })),
        h("div", {}, h("strong", { text: String(fields) }), h("span", { text: "配置项" })),
        h("div", {}, h("strong", { text: String((meta.schedules || []).length || 4) }), h("span", { text: "定时日报" }))
      )
    )
  );

  if (features.length) {
    fragment.append(
      h(
        "div",
        { class: "feature-strip" },
        ...features.map((feature) =>
          h(
            "span",
            { class: `feature-pill${feature.enabled ? "" : " off"}` },
            h("span", { class: `status-dot${feature.enabled ? " on" : ""}` }),
            feature.label
          )
        ),
        h(
          "span",
          { class: "feature-pill" },
          h("span", { html: icon("bolt", 13) }),
          `${enabled} / ${features.length} 项功能已启用`
        )
      )
    );
  }

  fragment.append(h("h3", { class: "section-title", text: "功能配置" }));

  fragment.append(
    h(
      "div",
      { class: "group-grid" },
      ...state.groups.map((group) => renderGroupCard(group))
    )
  );

  fragment.append(
    h(
      "div",
      { class: "two-col" },
      renderSchedulePanel(),
      renderSystemPanel()
    )
  );

  return fragment;
}

function renderGroupCard(group) {
  const status = groupStatus(group);
  const fields = (group.fields || []).length;
  return h(
    "button",
    {
      class: `group-card${isGroupDirty(group) ? " dirty" : ""}`,
      type: "button",
      "data-group": group.key,
      onClick: () => navigate(group.key),
    },
    h("span", { class: "group-icon", html: icon(group.icon || "apps", 20) }),
    h(
      "span",
      { class: "group-card-main" },
      h(
        "span",
        { class: "group-card-top" },
        h("span", { class: "group-card-title", text: group.title }),
        h("span", { class: `pill ${status.kind}`, text: status.label })
      ),
      h("span", { class: "group-card-hint", text: group.hint || "点击进入配置" }),
      h(
        "span",
        { class: "group-card-foot" },
        h("span", { text: `${fields} 项配置` }),
        h(
          "span",
          { class: "enter" },
          "进入",
          h("span", { html: icon("arrow", 13) })
        )
      )
    )
  );
}

function renderGroup(group) {
  const fields = group.fields || [];
  const status = groupStatus(group);
  const fragment = document.createDocumentFragment();

  fragment.append(
    h(
      "div",
      { class: "page-head" },
      h(
        "div",
        {},
        h(
          "button",
          {
            class: "btn ghost back-btn",
            type: "button",
            onClick: () => navigate("overview"),
          },
          h("span", { html: icon("undo", 15) }),
          h("span", { class: "btn-label", text: "返回总览" })
        ),
        h(
          "div",
          { class: "group-title" },
          h("span", { class: "group-icon lg", html: icon(group.icon || "apps", 24) }),
          h(
            "div",
            {},
            h("h2", { text: group.title }),
            h("p", { text: group.hint || "调整本组配置后记得保存" })
          )
        )
      ),
      h(
        "div",
        { class: "page-head-badges" },
        h("span", { class: "pill", text: `${fields.length} 项配置` }),
        h("span", { class: `pill ${status.kind}`, text: status.label })
      )
    )
  );

  fragment.append(
    h(
      "section",
      { class: "panel" },
      h("div", { class: "fields-grid" }, ...fields.map((f) => renderField(f, group)))
    )
  );

  return fragment;
}

function renderField(field, group, options = {}) {
  const value = state.values[field.key];
  const isDirty = state.dirty.has(field.key);
  const wide = field.type === "text" || field.type === "list" || field.type === "dict";
  const classes = ["field"];
  if (wide) classes.push("wide");
  if (field.type === "bool") classes.push("field-bool");
  if (isDirty) classes.push("dirty");

  const titleBits = [
    h("label", { for: `f_${field.key}`, text: field.label }),
    h("span", { class: "field-dirty", hidden: !isDirty, title: "有未保存的修改" }),
  ];
  if (options.showGroup && group) {
    titleBits.push(h("span", { class: "group-badge", text: group.title }));
  }

  const tools = h(
    "div",
    { class: "field-tools" },
    h("button", {
      class: "icon-btn",
      type: "button",
      title: `恢复默认值（${formatDefault(field)}）`,
      "aria-label": `恢复 ${field.label} 的默认值`,
      html: icon("undo", 14),
      onClick: () => resetField(field),
    })
  );

  const attrs = {
    class: classes.join(" "),
    "data-key": field.key,
  };
  if (field.condition && Object.keys(field.condition).length) {
    attrs["data-condition"] = JSON.stringify(field.condition);
  }

  const container = h("div", attrs);

  if (field.type === "bool") {
    const on = !!value;
    const switchBtn = h(
      "button",
      {
        class: `switch${on ? " on" : ""}`,
        type: "button",
        id: `f_${field.key}`,
        role: "switch",
        "aria-checked": on ? "true" : "false",
        "aria-label": field.label,
        onClick: () => {
          const next = !state.values[field.key];
          setValue(field.key, next);
          switchBtn.classList.toggle("on", next);
          switchBtn.setAttribute("aria-checked", next ? "true" : "false");
          const label = container.querySelector(".bool-label");
          if (label) {
            label.textContent = next ? "已开启" : "已关闭";
            label.classList.toggle("on", next);
          }
        },
      },
      h("span", { class: "switch-thumb" })
    );

    container.append(
      h(
        "div",
        { class: "field-head" },
        h("div", { class: "field-title" }, ...titleBits),
        tools
      ),
      h("p", { class: "field-hint", text: field.hint || " " }),
      h(
        "div",
        { class: "bool-row" },
        h("span", { class: `bool-label${on ? " on" : ""}`, text: on ? "已开启" : "已关闭" }),
        switchBtn
      )
    );
  } else {
    container.append(
      h(
        "div",
        { class: "field-head" },
        h("div", { class: "field-title" }, ...titleBits),
        tools
      ),
      h("p", { class: "field-hint", text: field.hint || " " }),
      buildControl(field, value)
    );
  }

  container.append(
    h(
      "div",
      { class: "field-foot" },
      h("span", { class: "field-default", text: `默认：${formatDefault(field)}` }),
      rangeText(field) ? h("span", { class: "field-range", text: rangeText(field) }) : null
    )
  );

  if (field.condition && Object.keys(field.condition).length) {
    const met = conditionMet(field.condition);
    container.append(
      h("div", {
        class: "cond-note",
        text: `未生效：需要 ${conditionText(field.condition)}`,
        hidden: met,
      })
    );
  }

  return container;
}

function buildControl(field, value) {
  if (field.type === "int" || field.type === "integer" || field.type === "float" || field.type === "number") {
    return buildNumber(field, value);
  }
  if (field.type === "list") return buildList(field, value);
  if (field.type === "dict") {
    return h("div", { class: "field-note", text: "嵌套配置请使用原配置页编辑。" });
  }
  if (field.type === "text" && !field.secret) return buildTextArea(field, value);
  if (field.options && field.options.length) return buildSelect(field, value);
  return buildTextInput(field, value);
}

function buildSelect(field, value) {
  const current = value === null || value === undefined ? "" : String(value);
  const options = [...(field.options || [])];
  if (!options.some((opt) => String(opt.value) === current)) {
    options.unshift({ value: current, label: `当前值：${current || "（空）"}` });
  }
  const select = h(
    "select",
    { class: "select", id: `f_${field.key}`, "aria-label": field.label },
    ...options.map((opt) =>
      h(
        "option",
        { value: String(opt.value), selected: String(opt.value) === current },
        opt.label
      )
    )
  );
  select.addEventListener("change", () => setValue(field.key, select.value));
  return select;
}

function buildTextInput(field, value) {
  const input = h("input", {
    class: "input",
    id: `f_${field.key}`,
    type: field.secret ? "password" : "text",
    value: value === null || value === undefined ? "" : String(value),
    placeholder: field.default ? `留空使用默认：${formatDefault(field)}` : "留空表示不使用",
    autocomplete: "off",
    spellcheck: false,
  });
  input.addEventListener("input", () => setValue(field.key, input.value));
  if (!field.secret) return input;

  let visible = false;
  const eye = h("button", {
    class: "icon-btn",
    type: "button",
    title: "显示 / 隐藏",
    "aria-label": "显示或隐藏敏感内容",
    html: icon("eye", 15),
    onClick: () => {
      visible = !visible;
      input.type = visible ? "text" : "password";
      eye.innerHTML = icon(visible ? "eyeOff" : "eye", 15);
    },
  });
  return h("div", { class: "input-wrap" }, input, eye);
}

function buildTextArea(field, value) {
  const ta = h("textarea", {
    class: "textarea",
    id: `f_${field.key}`,
    rows: 3,
    placeholder: "支持多行文本",
    spellcheck: false,
  });
  ta.value = value === null || value === undefined ? "" : String(value);
  ta.addEventListener("input", () => setValue(field.key, ta.value));
  return ta;
}

function buildNumber(field, value) {
  const isFloat = field.type === "float" || field.type === "number";
  const input = h("input", {
    class: "input",
    id: `f_${field.key}`,
    type: "number",
    inputmode: isFloat ? "decimal" : "numeric",
    step: isFloat ? "0.1" : "1",
    min: field.min === undefined || field.min === null ? undefined : field.min,
    max: field.max === undefined || field.max === null ? undefined : field.max,
  });
  input.value = value === null || value === undefined ? "" : String(value);
  input.addEventListener("input", () => {
    if (input.value === "") return;
    const num = Number(input.value);
    if (!Number.isFinite(num)) return;
    input.classList.toggle(
      "invalid",
      (field.min !== null && field.min !== undefined && num < field.min) ||
        (field.max !== null && field.max !== undefined && num > field.max)
    );
    setValue(field.key, isFloat ? num : Math.trunc(num));
  });
  input.addEventListener("change", () => {
    let num = Number(input.value);
    if (!Number.isFinite(num)) num = Number(state.values[field.key] ?? field.default ?? 0);
    if (field.min !== null && field.min !== undefined) num = Math.max(field.min, num);
    if (field.max !== null && field.max !== undefined) num = Math.min(field.max, num);
    num = isFloat ? Math.round(num * 100) / 100 : Math.trunc(num);
    input.value = String(num);
    input.classList.remove("invalid");
    setValue(field.key, num);
  });
  input.addEventListener("blur", () => {
    if (input.value.trim() === "") {
      input.value = String(state.values[field.key] ?? field.default ?? 0);
      input.classList.remove("invalid");
    }
  });
  return h("div", { class: "number-wrap" }, input);
}

function buildList(field, value) {
  const list = Array.isArray(value) ? value : [];
  if (field.options && field.options.length) {
    const grid = h("div", { class: "check-grid" });
    for (const opt of field.options) {
      const id = `f_${field.key}_${opt.value}`;
      const checkbox = h("input", {
        type: "checkbox",
        id,
        value: opt.value,
        checked: list.includes(String(opt.value)),
      });
      checkbox.addEventListener("change", () => {
        const current = Array.isArray(state.values[field.key])
          ? [...state.values[field.key]]
          : [];
        const set = new Set(current);
        if (checkbox.checked) set.add(String(opt.value));
        else set.delete(String(opt.value));
        const ordered = field.options
          .map((o) => String(o.value))
          .filter((v) => set.has(v));
        setValue(field.key, ordered);
      });
      grid.append(
        h("label", { class: "check-chip", for: id }, checkbox, h("span", { text: opt.label }))
      );
    }
    return grid;
  }

  if (field.long_items) {
    const ta = h("textarea", {
      class: "textarea",
      id: `f_${field.key}`,
      rows: Math.min(8, Math.max(3, list.length + 1)),
      placeholder: "每行一项",
      spellcheck: false,
    });
    ta.value = list.join("\n");
    const note = h("div", { class: "field-note", text: `共 ${list.length} 项 · 每行一项` });
    ta.addEventListener("input", () => {
      const next = ta.value
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean);
      note.textContent = `共 ${next.length} 项 · 每行一项`;
      setValue(field.key, next);
    });
    return h("div", {}, ta, note);
  }

  const chips = h("div", { class: "chips" });
  const input = h("input", {
    class: "input chip-input",
    id: `f_${field.key}`,
    type: "text",
    placeholder: list.length ? "继续添加…" : "输入后回车添加",
    "aria-label": `添加 ${field.label}`,
    autocomplete: "off",
  });

  const syncChips = () => {
    const current = Array.isArray(state.values[field.key]) ? state.values[field.key] : [];
    const nodes = current.map((item) =>
      h(
        "span",
        { class: "chip" },
        h("span", { class: "chip-text", text: item, title: item }),
        h("button", {
          class: "chip-x",
          type: "button",
          title: `移除 ${item}`,
          "aria-label": `移除 ${item}`,
          html: icon("close", 12),
          onClick: () => {
            setValue(
              field.key,
              (state.values[field.key] || []).filter((x) => x !== item)
            );
            syncChips();
          },
        })
      )
    );
    if (!current.length) {
      nodes.push(h("span", { class: "chips-empty", text: "尚未添加 · 留空表示不限制" }));
    }
    nodes.push(input);
    chips.replaceChildren(...nodes);
  };

  const addItems = (raw) => {
    const parts = String(raw)
      .split(/[\n,，;；]/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!parts.length) return;
    const current = Array.isArray(state.values[field.key])
      ? [...state.values[field.key]]
      : [];
    for (const item of parts) {
      if (!current.includes(item)) current.push(item);
    }
    setValue(field.key, current);
    input.value = "";
    syncChips();
    input.focus();
  };

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === "," || event.key === "，") {
      event.preventDefault();
      addItems(input.value);
    } else if (event.key === "Backspace" && !input.value) {
      const current = state.values[field.key] || [];
      if (current.length) {
        setValue(field.key, current.slice(0, -1));
        syncChips();
        input.focus();
      }
    }
  });
  input.addEventListener("blur", () => {
    if (input.value.trim()) addItems(input.value);
  });
  input.addEventListener("paste", (event) => {
    const text = event.clipboardData && event.clipboardData.getData("text");
    if (text && /[\n,，;；]/.test(text)) {
      event.preventDefault();
      addItems(text);
    }
  });

  syncChips();
  return chips;
}

/* ---------- 搜索 ---------- */

function renderSearchResults() {
  const query = state.query.toLowerCase();
  const matches = [];
  for (const group of state.groups) {
    for (const field of group.fields || []) {
      const haystack = [field.key, field.label, field.hint, group.title]
        .join("\n")
        .toLowerCase();
      if (haystack.includes(query)) matches.push({ group, field });
    }
  }

  const fragment = document.createDocumentFragment();
  fragment.append(
    h(
      "div",
      { class: "page-head" },
      h(
        "div",
        {},
        h("h2", { text: "搜索结果" }),
        h("p", { text: `关键词「${state.query}」 · 共 ${matches.length} 项` })
      ),
      h(
        "div",
        { class: "page-head-badges" },
        h(
          "button",
          {
            class: "btn ghost",
            type: "button",
            onClick: () => navigate(state.active === "overview" ? "overview" : state.active),
          },
          h("span", { html: icon("close", 14) }),
          h("span", { class: "btn-label", text: "清除搜索" })
        )
      )
    )
  );

  if (!matches.length) {
    fragment.append(
      h(
        "div",
        { class: "empty" },
        h("div", { class: "empty-icon", html: icon("search", 24) }),
        h("strong", { text: "没有找到匹配的配置项" }),
        h("p", { text: "试试搜索「Cookie」「群号」「日报」「积分」等关键词。" })
      )
    );
    return fragment;
  }

  const byGroup = new Map();
  for (const match of matches) {
    if (!byGroup.has(match.group.key)) byGroup.set(match.group.key, []);
    byGroup.get(match.group.key).push(match.field);
  }
  for (const group of state.groups) {
    const fields = byGroup.get(group.key);
    if (!fields || !fields.length) continue;
    fragment.append(
      h(
        "section",
        { class: "result-group" },
        h(
          "div",
          { class: "result-group-head" },
          h("span", { html: icon(group.icon || "apps", 16) }),
          h("span", { text: group.title }),
          h("span", { class: "count", text: String(fields.length) }),
          h(
            "button",
            {
              class: "icon-btn",
              type: "button",
              title: `打开 ${group.title}`,
              "aria-label": `打开 ${group.title}`,
              html: icon("arrow", 15),
              onClick: () => navigate(group.key),
            }
          )
        ),
        h(
          "div",
          { class: "fields-grid" },
          ...fields.map((field) => renderField(field, group, { showGroup: false }))
        )
      )
    );
  }
  return fragment;
}

/* ---------- 定时 / 系统信息 ---------- */

function renderSchedulePanel() {
  const schedules = (state.meta && state.meta.schedules) || [];
  return h(
    "section",
    { class: "panel" },
    h(
      "div",
      { class: "panel-head" },
      h("span", { class: "head-icon", html: icon("clock", 18) }),
      h(
        "div",
        {},
        h("h3", { text: "定时日报" }),
        h("p", { text: "四个日报各自独立定时，时间与群号在上面的分组里修改。" })
      )
    ),
    h(
      "div",
      { class: "schedule-list" },
      ...schedules.map((schedule) =>
        h(
          "div",
          { class: "schedule-row" },
          h(
            "span",
            { class: "schedule-name" },
            h("span", { class: `status-dot ${schedule.enabled ? "on" : "off"}` }),
            schedule.name
          ),
          h("span", {
            class: "schedule-time",
            text: `每日 ${pad2(schedule.hour)}:${pad2(schedule.minute)}`,
          }),
          h("span", {
            class: "schedule-groups",
            text: schedule.all_groups || !schedule.groups ? "全部群" : `${schedule.groups} 个群`,
          }),
          h("span", {
            class: "schedule-next",
            text: schedule.next ? `下次 ${schedule.next}` : "下次待调度",
          })
        )
      )
    )
  );
}

function renderSystemPanel() {
  const meta = state.meta || {};
  return h(
    "section",
    { class: "panel" },
    h(
      "div",
      { class: "panel-head" },
      h("span", { class: "head-icon", html: icon("server", 18) }),
      h(
        "div",
        {},
        h("h3", { text: "运行信息" }),
        h("p", { text: "只读信息，用于排查配置是否生效。" })
      )
    ),
    h(
      "div",
      { class: "info-list" },
      infoRow("调度模式", modeLabel(meta.scheduler_mode)),
      infoRow("时区", meta.timezone || "系统本地"),
      infoRow("插件版本", `v${meta.version || "—"}`),
      pathRow("数据目录", meta.data_dir || "—"),
      pathRow("配置兜底文件", meta.config_backup || "—")
    )
  );
}

function infoRow(label, value) {
  return h(
    "div",
    { class: "info-row" },
    h("span", { text: label }),
    h("strong", { text: value || "—" })
  );
}

function pathRow(label, value) {
  return h(
    "div",
    { class: "info-row path-row" },
    h("span", { text: label }),
    h(
      "span",
      { class: "path-value" },
      h("code", { text: value || "—", title: value || "" }),
      h("button", {
        class: "icon-btn",
        type: "button",
        title: "复制路径",
        "aria-label": `复制${label}`,
        html: icon("copy", 13),
        onClick: () => copyText(value || ""),
      })
    )
  );
}

/* ---------- 状态 / 交互 ---------- */

function setValue(key, value) {
  state.values[key] = value;
  if (same(value, state.baseline[key])) state.dirty.delete(key);
  else state.dirty.add(key);
  updateFieldState(key);
  updateChrome();
  if (conditionWatchers.has(key)) refreshConditions();
}

function updateFieldState(key) {
  if (!refs.main) return;
  const selector = `.field[data-key="${cssEscape(key)}"]`;
  const node = refs.main.querySelector(selector);
  if (!node) return;
  const dirty = state.dirty.has(key);
  node.classList.toggle("dirty", dirty);
  const dot = node.querySelector(".field-dirty");
  if (dot) dot.hidden = !dirty;
}

function resetField(field) {
  let fallback;
  if (field.type === "list") fallback = clone(field.default || []);
  else if (field.type === "bool") fallback = !!field.default;
  else if (field.type === "int" || field.type === "integer") fallback = Number(field.default || 0);
  else if (field.type === "float" || field.type === "number") fallback = Number(field.default || 0);
  else fallback = field.default === null || field.default === undefined ? "" : String(field.default);
  setValue(field.key, fallback);
  renderMain();
  const node = refs.main.querySelector(`.field[data-key="${cssEscape(field.key)}"]`);
  if (node) node.scrollIntoView({ block: "center", behavior: "smooth" });
}

function updateChrome() {
  if (!refs.saveBtn) return;
  const count = state.dirty.size;
  const label = state.saving ? "保存中…" : count ? `保存 (${count})` : "保存";
  refs.saveBtn.replaceChildren(
    h("span", { html: icon(state.saving ? "refresh" : "save", 16, state.saving ? "spin" : "") }),
    h("span", { class: "btn-label", text: label })
  );
  refs.saveBtn.disabled = state.saving || !count;

  const savebarCount = refs.savebar.querySelector("#savebarCount");
  if (savebarCount) {
    savebarCount.textContent = count
      ? `有 ${count} 项修改未保存`
      : "没有未保存的修改";
  }
  refs.savebar.classList.toggle("show", count > 0);
  refs.savebar.inert = count === 0;
  refs.savebar.setAttribute("aria-hidden", count > 0 ? "false" : "true");
  refs.savebar.querySelectorAll("button").forEach((btn) => {
    btn.disabled = state.saving;
  });

  refs.sideScroll.querySelectorAll(".nav-item[data-nav]").forEach((btn) => {
    const key = btn.dataset.nav;
    const dot = btn.querySelector(".nav-dirty");
    if (dot) dot.hidden = key === "overview" ? count === 0 : !isGroupDirtyKey(key);
  });

  if (refs.main) {
    refs.main.querySelectorAll(".group-card[data-group]").forEach((card) => {
      card.classList.toggle("dirty", isGroupDirtyKey(card.dataset.group));
    });
    refs.main.querySelectorAll(".field[data-key]").forEach((node) => {
      const dirty = state.dirty.has(node.dataset.key);
      node.classList.toggle("dirty", dirty);
      const dot = node.querySelector(".field-dirty");
      if (dot) dot.hidden = !dirty;
    });
  }
}

function refreshConditions() {
  if (!refs.main) return;
  refs.main.querySelectorAll("[data-condition]").forEach((node) => {
    let condition;
    try {
      condition = JSON.parse(node.dataset.condition);
    } catch {
      return;
    }
    const met = conditionMet(condition);
    node.classList.toggle("condition-off", !met);
    const note = node.querySelector(".cond-note");
    if (note) {
      note.textContent = `未生效：需要 ${conditionText(condition)}`;
      note.hidden = met;
    }
  });
}

function conditionMet(condition) {
  return Object.entries(condition || {}).every(([key, expected]) => {
    const current = state.values[key];
    if (typeof expected === "boolean") return Boolean(current) === expected;
    return String(current ?? "") === String(expected);
  });
}

function conditionText(condition) {
  return Object.entries(condition || {})
    .map(([key, expected]) => {
      const field = fieldIndex.get(key);
      const label = field ? field.label : key;
      if (typeof expected === "boolean") {
        return `「${label}」${expected ? "开启" : "关闭"}`;
      }
      return `「${label}」= ${expected === "" ? "（空）" : expected}`;
    })
    .join(" 且 ");
}

function isGroupDirty(group) {
  return isGroupDirtyKey(group.key);
}

function isGroupDirtyKey(key) {
  for (const field of groupMap.get(key)?.fields || []) {
    if (state.dirty.has(field.key)) return true;
  }
  return false;
}

function groupStatus(group) {
  const info = PRIMARY_TOGGLE[group.key];
  if (!info || !fieldIndex.has(info.key)) return { kind: "accent", label: "已就绪" };
  return state.values[info.key]
    ? { kind: "on", label: info.on }
    : { kind: "off", label: info.off };
}

function countFields() {
  return state.groups.reduce((sum, group) => sum + (group.fields || []).length, 0);
}

function modeLabel(mode) {
  if (mode === "framework") return "官方 cron_manager";
  if (mode === "local") return "自建 apscheduler";
  return "未启动";
}

function pad2(value) {
  const num = Number(value);
  return Number.isFinite(num) ? String(Math.trunc(num)).padStart(2, "0") : "--";
}

function formatDefault(field) {
  const value = field.default;
  if (field.type === "bool") return value ? "开" : "关";
  if (value === null || value === undefined || value === "") return "（空）";
  if (Array.isArray(value)) {
    if (!value.length) return "（空）";
    const text = value.join("、");
    return text.length > 80 ? `${text.slice(0, 80)}…` : text;
  }
  const text = String(value);
  return text.length > 80 ? `${text.slice(0, 80)}…` : text;
}

function rangeText(field) {
  const hasMin = field.min !== null && field.min !== undefined;
  const hasMax = field.max !== null && field.max !== undefined;
  if (!hasMin && !hasMax) return "";
  return `${hasMin ? field.min : "…"} – ${hasMax ? field.max : "…"}`;
}

function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(value);
  return String(value).replace(/["\\]/g, "\\$&");
}

/* ---------- 保存 / 重新读取 ---------- */

async function saveConfig() {
  const active = document.activeElement;
  if (active && refs.main && refs.main.contains(active) && typeof active.blur === "function") {
    active.blur();
  }
  if (state.saving || !state.dirty.size) return;
  const changed = {};
  for (const key of state.dirty) changed[key] = state.values[key];
  state.saving = true;
  updateChrome();
  try {
    const result = await apiPost("config-view/save", { values: changed });
    if (!result || typeof result !== "object") {
      throw new Error("保存接口没有返回结果，请稍后重试");
    }
    const savedValues = (result && result.values) || {};
    for (const [key, value] of Object.entries(savedValues)) {
      state.values[key] = clone(value);
      state.baseline[key] = clone(value);
      const field = fieldIndex.get(key);
      if (field) field.value = clone(value);
      state.dirty.delete(key);
    }
    try {
      // 重新拉取一次，让「定时日报」和分组状态使用最新值与下次运行时间
      await loadConfig();
      render();
    } catch {
      renderMain();
      updateChrome();
    }
    const count = result && result.saved ? result.saved : Object.keys(savedValues).length;
    toast(`已保存 ${count} 项配置`, "success");
    if (result && result.schedule_reloaded) {
      window.setTimeout(() => toast("定时任务已按新时间重新注册", "info"), 900);
    }
  } catch (error) {
    toast(error && error.message ? error.message : "保存失败，请稍后重试", "error");
  } finally {
    state.saving = false;
    updateChrome();
  }
}

async function reloadConfig() {
  if (state.dirty.size) {
    toast("还有未保存的修改：请先保存，或点「撤销」放弃修改后再重新读取", "error");
    return;
  }
  state.query = "";
  state.dirty.clear();
  renderBoot();
  try {
    await loadConfig();
    mountShell();
    render();
    toast("已重新读取配置", "success");
  } catch (error) {
    renderFatal(
      "重新读取失败",
      error && error.message ? error.message : "无法连接到插件后端。",
      "请确认插件已启用，并在插件详情页重新打开此页面。"
    );
  }
}

function discardChanges() {
  if (!state.dirty.size) return;
  state.values = clone(state.baseline);
  state.dirty.clear();
  renderMain();
  updateChrome();
  toast("已撤销未保存的修改", "info");
}

/* ---------- 初始化 ---------- */

function waitForBridge() {
  if (!bridge || typeof bridge.apiGet !== "function") {
    return Promise.reject(
      new Error("没有找到 AstrBot 插件页面 bridge。请从插件详情页打开此页面。")
    );
  }
  if (typeof bridge.ready === "function") {
    return Promise.race([
      bridge.ready(),
      new Promise((_, reject) =>
        window.setTimeout(
          () => reject(new Error("等待 AstrBot 页面上下文超时")),
          8000
        )
      ),
    ]);
  }
  return Promise.resolve(
    typeof bridge.getContext === "function" ? bridge.getContext() : {}
  );
}

async function init() {
  renderBoot();
  try {
    state.ctx = (await waitForBridge()) || {};
    applyTheme();
    if (!contextBound && typeof bridge.onContext === "function") {
      contextBound = true;
      bridge.onContext((ctx) => {
        state.ctx = { ...state.ctx, ...(ctx || {}) };
        applyTheme();
        const title = viewTitle();
        document.title = title;
        const heading = document.getElementById("pageTitle");
        if (heading) heading.textContent = title;
      });
    }
    document.title = viewTitle();
    await loadConfig();
    mountShell();
    render();
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    let hint = "这个页面需要在 AstrBot WebUI 中打开。\n请进入「插件 → 已安装 → 暮黎资源聚合 → 暮黎资源聚合控制台」。";
    if (/未找到该路由|not found/i.test(message)) {
      hint += "\n\n提示：插件后端路由未注册，请在插件页重载一次插件（不是只刷新页面）后再打开。";
    }
    renderFatal("无法打开控制台", hint, message);
  }
}

init();
