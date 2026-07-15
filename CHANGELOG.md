# 暮黎资源聚合插件 更新日志

## v1.10.5 — 2026-07-16

### 🗑️ 移除：书山聚合小说搜索功能

- **原因**：小说搜索依赖书山聚合源（v1.vossc.com）的逆向接口，稳定性与维护成本不可控，且非核心需求，按用户要求移除。
- **改动**：
  - 删除 `core/novel.py` 整个模块（书山聚合小说搜索：`NovelSearcher` 等）
  - 简化 `main.py`：移除 `NovelSearcher` 导入、`_novel_sessions` 小说会话管理器、小说意图拦截（"找小说/搜小说/看小说"等关键词）、`resource_kw` 中的小说关键词、`llm_search_novel` LLM 工具、`/找小说` 命令、翻页（`paginate_results`）与选择（`select_search_result`）处理中的小说分支、`on_any_message` 小说会话块、`_format_novel_page` / `_format_novel_detail` 格式化方法
  - 移除 `_conf_schema.json` 的 `novel_source` / `novel_key` 配置项
  - 更新 `metadata.yaml`：移除小说功能说明，版本号 → 1.10.5
  - 同步更新 README（移除小说相关文档）
- 插件现仅保留：影视（双源）/ 游戏 / 软件搜索、软件日报、网易云语音名片、VIP 视频解析、摸头/舔狗/按摩表情等原有功能

## v1.10.4 — 2026-07-15

### ♻️ 调整：教父.com 影视源改为纯 Cookie 登录

- **移除账号密码登录**：删除 `muliy_username` / `muliy_password` 配置项与对应 PoW+账号登录代码，影视源仅支持 `muliy_cookie`（浏览器登录态 Cookie）一种登录方式，绕过 PoW 与验证码。
- **`muliy_cookie` 提示完善**：说明必填字段（`app_auth` / `browser_verifie` / `PHPSESSID` 等）与获取方式「登陆后按F12，在应用程式页面复制各个带字段名cookie粘贴进来，用 ; 隔开」。
- **`MuliySiteClient` 重构为 cookie-only**：`ensure_session` / `_relogin_on_fail` 仅做 Cookie 注入与重灌；`parse_vip_url` 同步改为接收 `cookies`。

## v1.10.3 — 2026-07-15

### 🐛 修复：网易云语音名片若干稳定性问题 + 配置防丢 + 部署自检

- **/wyy_login 二维码发送崩溃修复**：原代码把 PNG 二进制字节直接传给 `Image.file`（期望路径），在 `0x89`（PNG 头）处抛 `UnicodeDecodeError`。改为先写临时文件再传路径（`main.py`）。
- **发送时长逻辑改为「整曲截断」**：原「歌曲中间三分之一」改为「从开头取 `min(歌曲时长, 上限)`」。配置项 `发送语音最大时长（秒）` → **`最大发送歌曲时长（秒）`**（`_conf_schema.json` / `core/audio_clip.py` / `main.py`），语义不变（key `wyy_clip_seconds` 不变，已填配置不丢）。
- **配置重装/卸载防丢失（xdgame 风格）**：`initialize()` 启动时从本地兜底文件恢复所有「当前为空」的配置项，含 `wyy_cookie` / `wyy_custom_url` / `cookie` / `switch618_cookie` / `muliy_cookie`。前提：卸载时不勾选「同时删除插件配置文件」。
- **/song/detail 解析容错**：NeteaseCloudMusicApi 部分版本会把多个 JSON 拼接返回，原 `r.json()` 抛 `Extra data`。新增 `_loads_robust()` 去 BOM/空白/JSONP 包裹并取首个完整 JSON（`core/netease.py`）。
- **长曲语音发送超时修复**：剪辑输出由 44100Hz 立体声 128k → **24000Hz 单声道 48k**（体积约 1/4，600s≈3.6MB），规避 OneBot 转码 silk 上传超时；仍失败时自动回退发音频文件而非报错（`core/audio_clip.py` / `main.py`）。
- **新增跨平台自检脚本 + 统一部署教程**：`tools/netease-api/test_netease_api.sh`（手机 Termux/Ubuntu、服务器、电脑 Mac/Linux 通用，自动探测 curl/wget/python3，验证 在线/直链/详情/搜索 四项）；`tools/netease-api/README.md` 改写为「手机/服务器/电脑通用」教程。

## v1.10.2 — 2026-07-15

### ✨ 新增：按摩表情 + 舔狗/按摩头像优先渲染 + 网易云扫码登录恢复

- **按摩表情（给我按摩）**：新增「柴犬按摩」GIF 表情（逆向自 diydoutu.com/diy/doutu/401）。触发词 `给我按摩` / `给我揉揉` + `@某人`；被 @ 为被按摩者、发送者为按摩者；无 @ 时按摩自己，多 @ 只处理第一个。
- **头像优先渲染**：舔狗 / 按摩表情统一改用成员圆形头像贴图（QQ 平台自动拉取，其它平台回退白字兜底）；实际渲染直径 = 配置 size + 15（边距）。
- **`/wyy_login` 扫码登录恢复**：接回此前移除的管理员命令——发送后返回网易云登录二维码，App 扫码确认后自动提取会员 Cookie 写入 `wyy_cookie`，无需手动 F12 抓取（依赖 `wyy_custom_url` 自建 NeteaseCloudMusicApi 后端在线）。
- **教父.com 新站影视源文档补全**：README 补充双源自动切换说明与 `muliy_username` / `muliy_password` / `muliy_cache_ttl` 配置项；未配置账号密码时自动回退 a123tv 旧站。
- **手机 / 多设备部署支持**：新增 `tools/netease-api/手机与多设备搭建指南.md` 与一键脚本 `setup_termux.sh`，支持 AStrBot 装在手机 Termux / Ubuntu 环境自建 NeteaseCloudMusicApi 并多设备共用。
- **落地页 `index.html`**：新增插件自包含响应式介绍页。
- **清理**：移除 `assets/lickdog/font.otf`，舔狗字体改用 Noto Sans SC；同步清理调试产物（`__pycache__` / 测试 GIF 等）。

## v1.10.1 — 2026-07-14

### ✨ 优化：选择列表序号改为 emoji 可视化（1⃣2⃣3⃣…）

- **背景**：机器人返回的游戏 / 软件 / 影视搜索列表、资源类型 / 网盘 / 播放线路、下载链接等，此前用 `[1] [2] [3]` 纯数字序号。在 QQ / 微信里用户很难一眼对应「回哪个数字」，尤其列表较长时容易点错。
- **方案**：新增共享函数 `emoji_index(n, total)`（`core/constants.py`）：
  - 列表总数 **≤ 9** 时，1~9 显示成 `1⃣ 2⃣ 3⃣ … 9⃣`，方便用户在聊天里可视化点选；
  - 超过 9 个（翻页后）回落纯数字 `[n]`，避免同一列表里 emoji 与数字混排。
- **覆盖的选择列表**：
  - 搜索结果：游戏 / 软件 / 影视的翻页列表，a123tv 与 movie.py 的搜索列表，统一搜索综合预览，影视解析接口菜单
  - 资源类型 / 节点 / 网盘：在线播放（1⃣）/ 网盘资源（2⃣）、播放线路、网盘类型与网盘资源列表
  - 下载链接：软件 / 游戏会话、`select_search_result`、`on_any_message`、legacy 会话等共 8 处
- **兼容性**：用户回复数字的选择逻辑完全不受影响（解析的是用户打字的数字，而非显示前缀）；`_parse_selection()` 的自然语言（"第一个""百度网盘"）选择同样正常。

## v1.10.0 — 2026-07-14

### 🗑️ 移除 gamer520.com 游戏搜索源（仅保留 xdgame.com）

- **原因**：服务器 IP 被 Cloudflare 彻底封锁（全引擎均无法突破：curl TCP 被掐(56)、patchright `ERR_EMPTY_RESPONSE`、nodriver 找不到浏览器）。gamer520 的方案已无继续投入的必要。
- **改动**：
  - 删除 `core/gamer520.py` 整个模块（861 行）
  - 简化 `core/game.py`：移除源切换逻辑（`_GAME_SOURCE`、`set_game_source`、`set_gamer520_proxy`），所有函数直接调用 xdgame 实现
  - 简化 `main.py`：移除 `_active_game_source`/`_apply_game_source` 源自动切换方法、移除 `/gamer520_diag` 诊断命令、所有游戏搜索入口直接检查 xdgame Cookie
  - 移除 `_conf_schema.json` 的 `gamer520_proxy` 配置项
  - 精简 `requirements.txt`：移除 nodriver、scrapling、patchright 依赖
  - 更新 `metadata.yaml` 说明：游戏搜索仅支持 xdgame.com 单源

## v1.9.19 — 2026-07-14

### 🔧 关键修复：nodriver 自动探测 Chromium + StealthyFetcher 替换为直调 patchright

- **问题 1 — nodriver `Failed to connect to browser`**：nodriver 默认只找系统 PATH 中的 chrome/chromium，但 `playwright install chromium` 安装的 Chromium 在 `~/.cache/ms-playwright/` 下，不在 PATH 中 → nodriver 找不到浏览器。
- **问题 2 — StealthyFetcher 不支持 `browser_args`**：scrapling 的 StealthyFetcher.fetch() 不接受 `browser_args` 参数（TypeError），之前尝试传参后被静默回退到无 `--disable-http2` 的原始调用 → 依然 `net::ERR_HTTP2_PROTOCOL_ERROR`。
- **修复**：
  - 新增 `_find_chromium_path()`：自动搜索 playwright/patchright 安装的 Chromium（`~/.cache/ms-playwright/chromium-*/chrome-linux/chrome`），再回退系统 PATH → nodriver 能正确启动浏览器。
  - 新增 `_fetch_html_patchright()`：直接调用 patchright/playwright 的 `sync_playwright()` + `chromium.launch(args=["--disable-http2"])`，确保 `--disable-http2` 绝对生效，替代 scrapling 的 StealthyFetcher。
  - `_fetch_html` 的引擎 ② 从 StealthyFetcher 替换为 `_fetch_html_patchright`。
  - `diagnose()` 同步替换，patchright 测试段也有独立输出。

## v1.9.18 — 2026-07-14

### 🔧 关键修复：nodriver + StealthyFetcher 统一禁用 HTTP/2（数据中心 IP 突破口）

- **根因发现**：日志显示 curl_cffi 在数据中心 IP 上直接 TCP 被掐 `(56)`，但 Chromium 报 `net::ERR_HTTP2_PROTOCOL_ERROR` — TCP 能建连，说明浏览器指纹可过 IP 检查，只是 **Cloudflare 的 HTTP/2 实现有 bug** 导致协商失败。
- **修复**：
  - nodriver：Chronicle 启动参数加入 `--disable-http2`（强制 HTTP/1.1）
  - StealthyFetcher：尝试传 `browser_args=["--disable-http2"]`（若 scrapling 版本支持则生效；不支持则静默回退原方式）
- **diagnose() 增强**：
  - 新增 `【nodriver】` 独立测试段，可直接看到 CDP 引擎 + HTTP/1.1 是否生效
  - StealthyFetcher 测试段同样尝试传 `--disable-http2`
  - 更新结论文案，覆盖 HTTP2_PROTOCOL_ERROR / TCP(56) / nodriver 成功的不同场景解读

## v1.9.17 — 2026-07-14

### 🔧 优化：gamer520 新增 nodriver 引擎（四级回退，数据中心 IP 可过 Cloudflare）

- **背景**：gamer520.com 前置 Cloudflare「Just a moment…」JS 挑战，StealthyFetcher（patchright）在住宅 IP 上可过，但数据中心 IP（云服务器）常被 TCP 层掐断或触发验证。
- **方案**：新增 nodriver 作为第一优先引擎（CDP 直控 Chrome，不暴露 webdriver 痕迹），形成四级自动回退链：
  1. nodriver → 2026 基准测试"零封锁"，数据中心 IP 也能过 CF 挑战
  2. StealthyFetcher（patchright）→ 原有主力回退
  3. Fetcher（curl_cffi 带指纹）→ 纯 HTTP 兜底
  4. 直接 Fetcher.get → 最终兜底
- 实现细节：
  - `_fetch_html_nodriver_async(url)`：异步内核，启动隐身 Chrome 后自动等待 CF 挑战完成（6s 初始等待 + wait_for body + 2s 额外等待，总超时约 45 秒）。
  - `_fetch_html_nodriver(url)`：同步封装，创建独立事件循环兼容 `asyncio.to_thread` 调用栈。
  - `_NODRIVER_AVAILABLE` 全局标记：首次失败后自动跳过，避免重复启动失败。
  - 支持 `gamer520_proxy` 配置项透传（通过 Chrome 启动参数 `--proxy-server=`）。
  - 延迟导入 nodriver：未安装时插件仍可正常加载，自动回退其他引擎。
- 部署注意事项：
  - 服务器需安装 Chromium：`playwright install chromium`
  - Linux headless VPS 已自动加 `sandbox=False` 参数
  - `requirements.txt` 已新增 `nodriver` 依赖

## v1.9.16 — 2026-07-13

### 🤚 新增：摸头杀 PetPet GIF 功能

- 在群聊中发送 `摸摸 @某人`，机器人自动生成并发送摸头 GIF 动图。
- 支持命令别名 `摸头`，无@时默认摸自己的头。
- 支持同时@多人（最多5个），逐个生成 GIF 发送。
- 实现细节：
  - 新增 `core/petpet.py`：基于 Pillow 实现 10 帧透明 GIF 合成，算法参考 [camprevail/pet-pet-gif](https://github.com/camprevail/pet-pet-gif)。
  - 新增手部模板资源：`assets/petpet/pet0.gif` ~ `pet9.gif`。
  - QQ 头像通过 `https://q1.qlogo.cn/g?b=qq&nk={qq}&s=640` 公开接口获取，无需登录态。
  - 在 `main.py` 中新增 `cmd_petpet` / `cmd_petpet_alias` 命令处理器，使用 `event.get_messages()` 提取 `At` 组件。
- 异常处理：
  - 未@任何人：默认摸发送者自己。
  - @全体成员 (`all`)：自动跳过。
  - @超过5人：只处理前5人并提示。
  - 头像下载失败 / GIF 生成失败：返回友好错误提示。
  - Pillow 未安装：提示安装命令 `pip install pillow`。
- 依赖更新：`requirements.txt` 新增 `pillow`。

## v1.9.15 — 2026-07-12

### 🐞 修复：分享卡片链接 URL 编码 + 视频ID重定向 + 选接口菜单不弹

- **现象**：
  1. 部署后转发爱奇艺等分享卡片，机器人不先弹「选接口」菜单，而是直接提示「选择超时」或毫无反应。
  2. 菜单能弹出后，选接口解析失败——因为提取出的链接是 URL 编码的（`http%3A%2F%2F...`）且视频ID不对（`v_x0moau6sik` 应为 `v_2393lofbbz0`）。
- **根因**：
  1. 上一版（v1.9.14）VIP 解析用的是 `session_waiter` 等待流程，菜单消息在 `on_any_message` 上下文里被 pipeline 吞掉、waiter 几乎立即超时 → 表现为「没菜单就超时」。本版改回 `on_vip_video`（`priority=3`）+
     `_vip_pending` 字典会话（与影视/游戏选择兜底逻辑一致），菜单用 `event.send` 直接下发，用户回序号后在 `on_vip_video` 内 `event.stop_event()` 接管——不再有「假超时」。
  2. `is_vip_video_url()` 此前只扫裸文本，识别不了 QQ 的 `[CQ:json]`/`[CQ:share]`/`[CQ:xml]` 分享卡片（卡片的 `jumpUrl` 在 CQ 码里是 URL 编码的 JSON，裸文本正则匹配不到），导致分享卡片被静默忽略。
  3. AStrBot 对 JSON 分享卡片的事件 `message_str` 为空（显示 `[ComponentType.Json]`），只读 `message_str` 会再次漏掉卡片。
- **变更**：
  - `core/vip_capture.py`：
    - 新增 `_extract_cq_urls()`：从 `[CQ:json data=...]`/`[CQ:share]`/`[CQ:xml]` 卡片里解码出 `jumpUrl`/`url`/`playUrl` 等跳转地址（兼容 URL 编码与 CQ 转义两种写法），精确截到链接本身、不再贪婪吞掉半个 JSON。
    - 新增 `_extract_json_urls()`：从裸 JSON 对象字符串里优先读取 `jumpUrl`/`url` 等字段，再做 URL 正则兜底，避免贪婪正则把后续 JSON 字段一起吞入。
    - `is_vip_video_url()`：检测到 `[CQ:` 只走卡片解码分支；检测到 JSON 对象字符串只走字段提取分支；避免对整条 CQ 码/JSON 跑贪婪正则。
    - 恢复 `resolve_iqiyi_share()` / `is_iqiyi_share_url()`（v1.9.13 的可靠方案）：爱奇艺分享卡片经浏览器转换（`_find_clean_v`）在无登录态下常失败，改为用 `mesh.if.iqiyi.com` 公开接口（纯 HTTP、可走 `video_vip_proxy` 代理）把 `shareId`→真实 `v_xxx.html` 播放页，并顺带取标题/封面。浏览器转换失败时自动兜底，菜单不再错误地提示「无法转换」。`_handle_vip_link` 接入该兜底。
  - `main.py`：
    - `on_vip_video` 改为先读 `message_str`，若未命中则遍历消息组件（`ComponentType.Json`）的 `data` 字段再次识别（与网易云语音助手 `on_netease_voice` 的已验证写法一致）。
    - VIP 解析维持「展示命名接口菜单 → 等用户回序号 → Nodes 合并转发（标题+简介+截图+直链）」交互式流程，无超时死锁。
  - 待选会话 5 分钟 TTL 自动清理（无幽灵会话）。
- **v1.9.15 补丁（URL 编码 + 重定向跟随）**：
  - `core/vip_capture.py`：
    - `_extract_json_urls()` / `_extract_cq_urls()` 新增对 URL 编码链接（`http%3A%2F%2F...`）的识别与解码。
    - 新增 `follow_iqiyi_redirect(url, proxy)`：对爱奇艺播放页做 HTTP 重定向跟随（HEAD→GET 兜底），解决 `v_x0moau6sik.html` 302 跳转到 `v_2393lofbbz0.html` 但代码拿旧链接的问题。
    - `resolve_iqiyi_share()` 对 API 返回的 `vu` 字段做 `urllib.parse.unquote()` 解码，防止 URL 编码的播放页直链直接喂给解析器。
    - `analyze_vip_link()` 的 `_find_clean_v` 浏览器提取结果同样做 URL 解码。
    - 补回 `capture_vip_m3u8`(stub)/`shutdown`/`capture_interface_screenshot` 兼容旧导入。
  - `main.py` 的 `_handle_vip_link()`：
    - 入口处先 `urllib.parse.unquote(link)` 解码卡片链接。
    - 爱奇艺分享卡片改为**优先**调 `resolve_iqiyi_share`（API，纯 HTTP），成功后直接跳过耗时的浏览器分析；失败再走浏览器 + 兜底。
    - 解析完成后调 `follow_iqiyi_redirect()` 跟随 302 重定向，拿到最终播放页。
  - `core/video_parse.py`（补入包）：
    - `detect_video_url()` 新增对 URL 编码链接（`https?%3A%2F%2F...`）的识别。
    - `extract_video_from_miniapp()` 对提取出的 URL 做 `unquote()` 解码 + `http://` → `https://` 升级。

## v1.9.11 — 2026-07-12

### 🎞️ VIP 视频解析改为「交互式选接口 + 分享卡片转换」

- **背景**：用户希望完整流程为——(1) 把爱奇艺分享卡片链接转为纯净播放页；(2) 解析时先获取影视标题/简介；(3) 展示解析接口菜单让用户选；(4) 选中后把标题/简介/截图/直链以「聊天记录格式」返回。
- **变更**：
  - `core/vip_capture.py`：
    - 新增 `VIP_INTERFACES` 命名接口表（虾米/M1907/七哥/咸鱼/极速/PlayerJY/789/fongmi/花旗/937，与影视解析页下拉框一致），菜单展示带名字。
    - 新增 `analyze_vip_link()`：用无头浏览器加载链接，**自动把爱奇艺分享卡片 `playShare.html?shareId=` 转换为纯净 `v_xxx.html` 播放页**（解出 tvid 后从页面里定位只出现一次的 v_ 链接），并抓取影视标题/简介/截图（浏览器截图，或 `og:image` 缩略图）。
    - 新增 `verify_interface_playable()`：选中接口后加载其播放直链，检测是否真渲染出可播放的 `<video>`/`<iframe>` 播放器，返回 `{ok, title}`；浏览器上下文加 `ignore_https_errors=True`（让 `937` 等证书异常站点也能加载）。
    - 移除旧的「并发自动优选」逻辑（`capture_vip_m3u8` 等），改为「展示菜单 → 用户挑选 → 单接口校验」。
  - `main.py`：
    - `on_vip_video` 改为交互式：`_vip_pending` 按 `unified_msg_origin` 维护待选会话（5 分钟 TTL）；先 `analyze_vip_link` 提取信息并发送「影视信息 + 命名接口菜单 + 截图」，等用户回序号；`_handle_vip_selection` 校验选中接口，成功则以 **Nodes/Node 合并转发（聊天记录格式）** 返回（标题+简介+截图+直链），失败则保留会话让用户换接口重试或发纯净链接。
    - 支持 `/cancel` 取消；序号无效时提示重选。
  - `_conf_schema.json`：接口文案改为「展示菜单让用户挑选」；新增 `video_vip_proxy`（浏览器出网代理，留空自动探测）。

## v1.9.10 — 2026-07-12

### 🎞️ 重写：VIP 视频解析改为「影视解析页接口集合」

- **背景**：此前方案（自己凑外链解析站 + HLS 代理/VLC 备选）不稳定——要么外链随时失效，要么免费站返回的 m3u8 分片带防盗链（取到一张 PNG 水印图而非视频），独立播放器放不了；用户明确要求「不要 VLC 备选，直接用影视解析页的接口」。
- **变更**：
  - `core/vip_capture.py` 重写为**解析接口集合**：默认模板与「影视解析页 https://www.xn--wcv59z.com/zjx」下拉框里的接口一致（虾米/jx.xmflv.com、M1907、七哥、咸鱼、极速、PlayerJY、789、fongmi、花旗、937 共 10 个），并发尝试、用无头浏览器检测哪个接口**真的渲染出可播放的 `<video>`/`<iframe>` 播放器**，自动跳过失效接口，返回第一个可用的「解析播放直链」给用户（浏览器/播放器打开即看）。
  - **彻底移除 HLS 代理 / VLC 备选**（按用户要求）。
  - 不再自己到处找外链解析站，接口列表与影视解析页保持一致，可在配置 `video_vip_parser_urls` 里增删。
  - 保留环境代理自动探测（Chromium 不读 `HTTP(S)_PROXY`，显式传入），仅用于浏览器出网，与 HLS 代理无关。
  - `main.py`：VIP 解析分支对接新逻辑；返回文案改为「解析播放直链（浏览器/播放器打开即看）」+ 命中接口名；去除 m3u8/VLC 相关措辞。
  - `_conf_schema.json`：`video_vip_parser_urls` 默认改为 10 个影视解析页接口；`video_vip_parse` 提示更新。
- **使用**：直接把爱奇艺/腾讯/优酷/芒果/bilibili 等 VIP 视频链接发到对话即可自动解析；爱奇艺分享短链 `qy.net/xxx` 会自动归一化为真实播放页。某接口集体失效时在 `video_vip_parser_urls` 增删。

## v1.9.5 — 2026-07-11

### 🎵 新增：网易云 VIP/付费歌曲解析（wyy_cookie）

- **背景**：用户反馈网易云语音名片无法解析 VIP/付费歌曲。排查确认根因：`NeteaseCloudMusicApi` v4.32.0 **无全局 Cookie 环境变量**，VIP 歌曲仅在请求携带有效会员 Cookie（`MUSIC_U`）时才返回播放直链；插件此前调用 `/song/url` 不带 Cookie，故 VIP 歌曲 `data[0].url` 为 null。参考项目 `Suxiaoqinx/Netease_url` 能解析 VIP，正是因为它把黑胶会员 Cookie 写入 `cookie.txt` 随请求转发。
- **变更**：
  - `core/netease.py`：`_get_json` 增加 `cookie` 参数，请求时作为 `Cookie` 头发送（服务端 `server.js` 解析 `req.headers.cookie` → `query.cookie` → `option.js` 转发，与浏览器登录态一致，避开 `;`/`=` 的 URL 编码坑）。
  - `core/netease.py`：`_parse_custom` 在 `/song/url` 与 `/song/detail` 两处请求均带上 `wyy_cookie`；旧 `{id}` 模板分支同样带上。
  - `_conf_schema.json`：新增 `wyy_cookie`（string，默认空；hint 说明需黑胶会员 Cookie、获取方式与风控提醒）。留空时行为不变（仅免费歌）。
  - `metadata.yaml`：版本号 → 1.9.5；网易云说明补充 VIP 解析。
- **使用**：填 `wyy_cookie` = 黑胶会员账号的 Cookie 整串（含 MUSIC_U 与 __csrf）即可解析 VIP 歌曲；`standard/exhigh/lossless` 需黑胶会员，`sky/jymaster` 需超级会员。后端容器无需改动（Cookie 由插件每次请求携带）。

## v1.9.4 — 2026-07-11

### 🎵 变更：网易云语音改为「歌曲中间三分之一」发送

- **背景**：QQ 语音长度在 10 分钟内均无限制（此前按 60 秒旧限制裁剪），用户希望发送更长、更完整的歌曲片段。
- **变更**：
  - `core/audio_clip.py`：`compute_clip_range` 替换为 `compute_middle_third_range(duration, max_seconds=600)`——把整首歌时长分成三份，取中间那一段（start=duration/3, length=duration/3）。
  - `main.py`：调用处改为 `compute_middle_third_range`，名片文案改为「中间片段」。
  - `_conf_schema.json`：`wyy_clip_seconds` 重定义为「语音最大时长上限」，默认 600（10 分钟）、最大 600；`wyy_clip_start_ratio` 标记废弃（不再生效）。
  - `metadata.yaml`：版本号 → 1.9.4，更新网易云语音说明。

## v1.9.3 — 2026-07-11

### 🧹 清理：移除不可用的公共解析后端 wyapi / qzxdp

- **背景**：公共解析站 `wyapi.toubiec.cn` 与 `tools.qzxdp.cn` 对服务器 / 数据中心 IP 普遍返回 404 拦截（已实测确认），插件是「服务器直连」调用，无法使用，且用户明确要删掉这些用不上的功能。
- **变更**：
  - `core/netease.py`：`parse()` 现在**仅走自建 NeteaseCloudMusicApi 后端（custom）**。删除 `_parse_qzxdp`、`_parse_wyapi` 两个方法，以及仅被它们使用的 `_post_json`、`_post_form` 辅助函数。
  - 清理无用依赖：`import time`、`import urllib.parse` 一并移除。
  - `wyy_music_type` 现在接入自建后端的 `/song/url?level=`，配置保持有效。
  - `_conf_schema.json`：删除 `wyy_backend` / `wyy_api_base` / `wyy_api_path` 三项；`wyy_custom_url` 改为「唯一后端地址」描述。
  - `main.py`：解析失败提示去掉 `wyy_backend` 引用，改为提示检查 `wyy_custom_url`。
  - 自测脚本 `tools/check_qzxdp.py` 重写为 `tools/check_netease_api.py`（仅检测自建 NeteaseCloudMusicApi）。
  - 同步更新 README / metadata.yaml，版本号 → 1.9.3。

## v1.9.2 — 2026-07-11

### 🐛 修复：网易云解析失败的根本原因（此前所有后端都静默失效）

- **根因**：`core/netease.py` 中 `_get_json` / `_post_json` / `_post_form` 是**模块级函数**，但三个后端方法（`_parse_wyapi` / `_parse_qzxdp` / `_parse_custom`）却以 `self._get_json(...)` 形式调用，运行时抛 `AttributeError`。该异常被各方法内的 `try/except` 吞掉，导致三个后端**全部静默返回 `None`** → 插件永远报「解析失败」。这才是解析失败的真正主因（公共站 wyapi 对服务器 IP 的 WAF 404 是叠加因素）。
- **修复**：统一改为模块级调用（去掉 `self.`），三个后端恢复正常执行。

### 🚀 增强：custom 后端对接标准 NeteaseCloudMusicApi + 失败原因可见

- `wyy_custom_url` 现支持两种填法：
  - 基础地址（推荐）：`http://127.0.0.1:3000` —— 自动调用 `/song/url`（直链）+ `/song/detail`（歌名/歌手/专辑/封面），名片信息完整。
  - 旧 `{id}` 模板：向后兼容，仅能拿直链。
- 解析失败时，`NeteaseParser.last_error` 会记录具体原因（如「wyapi 被 WAF 拦截返回 404」「custom /song/url 请求失败：实例地址不可达」），并在用户侧的「❌ 网易云解析失败」提示中直接展示，便于秒定位。
- 新增 `tools/netease-api/`：开箱即用的 `docker-compose.yml` + `Dockerfile`，一条命令自建 NeteaseCloudMusicApi 实例，规避公共站 WAF 拦截。
- 同步更新 README（自建后端章节）、配置 schema 说明、版本号 → 1.9.2。

## v1.9.1 — 2026-07-11

### 🔧 调整：网易云语音名片默认解析后端切换为 wyapi.toubiec.cn

- **背景**：原默认后端 `tools.qzxdp.cn` 在数据中心 / 云服务器 IP 被站点 WAF 拦截（返回 404），导致插件在多数部署环境无法解析。
- **变更**：`wyy_backend` 默认值由 `qzxdp` 改为 `wyapi`（即 `wyapi.toubiec.cn`，经用户在浏览器验证可用）。
  - wyapi 为 NeteaseCloudMusicApi 风格接口，需两次请求：
    - `POST /api/getSongInfo` → 歌曲元数据（歌名 / 歌手 / 专辑 / 封面）
    - `POST /api/getSongUrl`（body 含 `id` / `level` / `timestamp`）→ 播放直链
  - 新增专用 JSON POST 辅助 `_post_json`，请求体与前端完全一致（带 `timestamp`）。
  - `qzxdp` 与 `custom` 后端保留为可选 fallback。
- **注意**：wyapi 在数据中心 IP 同样可能被 WAF 拦截（本机自测脚本已确认 404）。若你的 AstrBot 部署在云服务器，请：
  1. 在部署机运行 `python tools/check_qzxdp.py` 确认可用性；
  2. 若不可用，将 `wyy_backend` 改为 `custom` 并填入自建 NeteaseCloudMusicApi 实例地址。
- 配套：`tools/check_qzxdp.py` 自测脚本改为默认检测 wyapi（加 `--qzxdp` / `--custom` 可叠加检测）。

## v1.9.0 — 2026-07-11

### ✨ 新增：网易云语音名片

- 发送网易云歌曲链接（`music.163.com` 多种形态 / `163cn.tv` 短链 / 移动端分享 / `orpheus://`）或 QQ 转发的网易云**小程序卡片**，自动解析为 mp3 直链。
- 下载后用 ffmpeg 截取**中间高潮片段**（默认 60 秒，从歌曲 33% 处起；三分钟歌曲取 60s~120s；歌曲短于片段则发整首）。
- 通过 QQ 语音（`Record`）发送，并附歌曲名片（歌名 / 歌手 / 专辑）；AstrBot 不支持语音组件时自动降级为发送文件。
- **自动模式**：`wyy_auto_parse=true`（默认）时，消息含网易云链接或小程序即触发，`stop_event()` 抢占 LLM。
- **命令模式**：`/wyy <网易云链接或歌曲ID>` 手动触发，支持短链自动展开。
- **解析后端**：`wyapi`（默认）/ `qzxdp`（旧站）/ `custom`（自建 NeteaseCloudMusicApi，最稳定）。
- **部署前提**：
  - 运行环境需安装 **ffmpeg**（未安装则退化为发送完整音频并提示）。
  - 公共解析站可能被 WAF 拦截，必要时切换 `custom` 后端。
- 新增文件：`core/netease.py`（检测 / 解析 / 下载）、`core/audio_clip.py`（时长探测 / 片段截取）、`tools/check_qzxdp.py`（接口可用性自测）。
- 新增配置：`wyy_auto_parse` / `wyy_only_command` / `wyy_backend` / `wyy_api_base` / `wyy_api_path` / `wyy_music_type` / `wyy_custom_url` / `wyy_clip_seconds` / `wyy_clip_start_ratio` / `wyy_audio_format`。

## v1.7.5 — 2026-07-08

### ✨ 优化 + 🐛 Bugfix：选集简化 / 线路翻页 / 集数 m3u8 错位 / LLM 查百科

#### Feature 1：选集页简化
**之前**（剧时）：
```
📺 「庆余年 2」全 36 集（共 36 集可切换）：
====================================
[1] 第1集
[2] 第2集
... (33 行)
```
**现在**：
```
📺 「庆余年 2」全 36 集
====================================

💬 请输入想看的集数（1-36），例如「5」= 第 5 集

⏱️ 120 秒无操作自动取消。回复 0 取消。
```
实现：`core/movie.py` 的 `format_episodes` 重写，不再循环列 `[1][2][3]`，只显示总数 + 提示用户。

#### Feature 2：线路分页 15/页
- `format_sources(detail, page=0, page_size=15)` —— 新增 page / page_size 参数
- on_any_message 和 session_waiter 路径都加翻页分支：
  - 「下一页」/「下一页线路」→ page + 1
  - 「上一页」/「上一页线路」→ page - 1
- 翻到边界提示「已经是最后一页啦~」「已经是第一页啦~」
- session 加 `source_page` 字段保存当前页码

#### 🐛 Bug D：选集后 m3u8 集数不对（一直都是第 1 集）
**现象**：用户选怪奇物语第 5 集 + 线路 3，得到的 m3u8 实际是第 1 集的。

**根因**：on_any_message `select_source` 用 `parse_play_page(src["url"])` —— `src["url"]` 是详情页里所有线路通用的播放页 URL（绑第 1 集）。无论用户选哪集都拿到第 1 集的 m3u8。

**修复**：改用 `parse_play_page(ep["url"])` —— `ep["url"]` 是用户选的那集的播放页，pp.la[] 包含**该集**所有线路的 m3u8。

**测试**：
- 第 5 集 + 线路 8 → `v10.zuidazym3u8.com/yyv10/.../0nXN9iRZCa15/video/index.m3u8`
- 第 1 集 + 线路 8 → `v11.zuidazym3u8.com/yyv11/.../bBax7JbMgq3/video/index.m3u8` ✅ 不同

#### Feature 4：LLM 查百度百科 + 精简合转发
**之前**：直接从 a123tv 详情页拿简介（往往很简陋）+ 显示地区
**现在**：
- 移除地区字段
- 新增 `_fetch_movie_meta_via_llm(event, name)` —— 调用 AstrBot 的全局 LLM，让它联网查百度百科，返回 `(主演, 一句话简介)`
- 输出格式（合转发节点 1：文字，节点 2：封面）：
```
🎬 庆余年 2 第 5 集
📡 线路224
🎭 主演：张若昀、李沁、陈道明、吴刚
📖 一句话简介
🔗 https://m3u8-url/...
```
- LLM API 双路兼容：
  - v4.5.7+ 新版：`context.get_current_chat_provider_id(umo)` + `context.llm_generate(...)`
  - 旧版：`context.get_using_provider(umo).text_chat(...)`
- 失败时降级为空（不影响主流程）

#### 合转发（私聊 HTML）也同步精简：
- 不再显示地区
- 简介优先用 LLM 查的，否则用 a123tv 的

#### 代码改动
- `core/movie.py` — `format_episodes` 重写；`format_sources` 加分页
- `main.py` — on_any_message + session_waiter 加翻页 + Bug D 修复；新增 `_fetch_movie_meta_via_llm` / `_send_movie_record` helpers

## v1.7.4 — 2026-07-08

### 🐛 Bugfix：3 个用户报告的影视 Bug (年字 / 序号乱 / 缺直链)

#### Bug A：搜索结果标题末尾多"年"字

**现象**：
```
[1] 庆余年 2 年  【国产剧·2024】
[4] 庆余年之少年风流 年  【国产剧·2024】
```

**根因**：
- raw 形如 `1080p 36个线路 庆余年 2 国产剧 / 2024年`
- year regex `(\d{4})\s*年?` 只能匹配 `2024`（不带"年"）
- title 剔除 `2024` 后剩 `庆余年 2 国产剧 / 年`
- 旧代码 `re.sub(r"\d{4}\s*年?", "", title)` 只剔 `2024年`，留下孤立的"年"

**修复**：
1. 改 year regex 为 `[\s/·\-—_|]*\d{4}\s*年?[\s/·\-—_|]*` —— 整个 "/ 2024年" 段一起吃
2. 加一行 `re.sub(r"[\s/·\-—_|]年\s*[\s/·\-—_|]*", " ", title)` 清残留的孤立"年"
3. **关键**：前一个 regex 严格要求前面是分隔符（不能吞掉"余年"的"年"）
4. 顺便修了一个连带 bug：原 `sources = "1线路"`，用 `.replace("1线路", "")` 在 raw `"1个线路 庆余年..."` 中只能删"路"字符，**导致"庆余年之少年风流"被错误切成"庆余 之少 风流"**。改用 `sources_raw = "1个线路"` 精确替换。

#### Bug B：线路列表序号乱序

**现象**：
```
[8] HD · 720p
[21] HD · 720p
[22] HD · 720p
[32] 更新
[134] HD · 720p
```
序号是 a123tv 原始线路号（8, 21, 22, 32, 134 ...），有跳号

**根因**：`format_sources` 直接用 `s["n"]`（a123tv 真实线路号），但 a123tv 上有些线路被官方删了，跳号

**修复**：`format_sources` 改用 `enumerate(show, 1)`，序号按显示位置 1, 2, 3, ...
- 原始线路号仍存在 `s["n"]` 中（用户回复时用 list index 选）
- on_any_message 的 `select_source` 日志和输出改为 `线路{num}/{len(srcs)}` （按位置）

#### Bug C：直链提取（最关键）

**现象**：用户点开链接 `https://a123tv.com/v/qingyunian21/6cz8nez0.html` 还要在 a123tv 网站上看，无法直接播放

**根因**：a123tv 详情页拿到的是播放页 URL，**真正的视频直链 m3u8 藏在播放页 JS 里** (`var pp={...}`)

**修复**：
- 新增 `parse_play_page(play_url)` —— GET 播放页 → 解析 `var pp={...}` → 返回 `{ld, idx, ep_n, lines: [{ld, name, eps, m3u8}]}`
- on_any_message `select_source` 阶段：用户选完线路后**懒加载 m3u8**
  - 从 `src.url` 抓 pp.la，找 `name == f"线路{src['n']}"` 的 ld 对应的 m3u8
  - 拿不到时退回到 src.url

**测试结果**（怪奇物语 2 第 1 集 src[0] (a123tv-line=8)）：
- 修复前：`https://a123tv.com/v/guaiqiwuyu2/8z2gcz0.html`
- 修复后：`https://v2.zuidazym3u8.com/yyv2/202308/22/9pCDijwj8T2/video/index.m3u8` ✅
- 验证 m3u8 GET 返回 200，size=96B，content 是合法 m3u8 文件

#### 代码改动
- `core/movie.py` — `_clean_title` 修 2 个 regex；`format_sources` 改 enumerate；新增 `parse_play_page` / `build_play_url`
- `main.py` — `llm_select_search_result` import `parse_play_page, build_play_url`；`select_source` 懒加载 m3u8

## v1.7.3.1 — 2026-07-08

### 🐛 Bugfix：影视选择重复回复 + LLM 编造结果

#### Bug 现象（用户报告）
1. 用户用 LLM 自然语言搜索影视（如"找怪奇物语第二季"）→ 大模型机器人会重复回复（先发工具结果，再发"好嘞～系统正在处理"），并且**编造搜索结果**（讲是 LLM 自己说"怪奇物语 第二季对吧"）
2. 用户选完影视序号之后**没反应**了（没收到集数/线路列表）

#### 根因
1. `_strip_llm_chitchat_after_tool` 钩子**没有检查 `_movie_sessions`** —— 当 LLM 调用 `select_search_result` 后，插件没设置 `_llm_handled=True`，LLM 二次总结就无法被拦截
2. `llm_select_search_result` 的影视分支**只 return 文本，没有 `event.send()` 发集数/线路列表** —— 用户收不到后续选项

#### 修复
1. **`_strip_llm_chitchat_after_tool`**：增加 `ses_mv = self._movie_sessions.get(event)` 检查，target_ses 改为 `ses_sw or ses_g or ses_mv`
2. **`llm_select_search_result` 影视分支**：把 on_any_message 里 select_movie 阶段的逻辑内联过来 —— 直接 `event.send()` 发"已选择: XXX"+"获取详情中"+"集数列表/线路列表"，并设置 `_llm_handled=True`
3. 文案改为更明确的引导："**不要再调用任何工具，等待用户回复数字**"

#### 测试
- 怪奇物语 第二季（剧）→ ✅ 显示「全 9 集」
- 怪奇物语 幕后纪录片（电影）→ ✅ 直接显示 14 条播放线路
- LLM 调工具后 → ✅ _llm_handled 拦截二次总结

#### 代码改动
- `main.py` — `_strip_llm_chitchat_after_tool` + `llm_select_search_result`

## v1.7.3 — 2026-07-08

### ✨ 优化：(a) 类别 + 年份合并 / (b) 剧状态识别 / (c) LLM 工具描述

#### (a) 列表标签升级
之前：`[1] 怪物  【日本剧】`
现在：`[1] 怪物  【日本剧·2025】`

实现细节：
- `_clean_title` 重构返回 `(title, category, year, meta)` 4-tuple，**年份作为独立字段**
- 在 `raw` 中**先剔除画质和线路数**，再匹配 `(\d{4})\s*年?` —— 防止「1080p」被误识别为「1080年」
- `format_movie_list` 拼成 `【类别·年份】`，缺年份时只显示【类别】

#### (b) 剧状态智能识别
之前：用户选影视后直接列 `[1] 第1集 [2] 第2集 ...`（无法看出剧是否完结）
现在：列表开头显示 `📺 「XX」全 10 集（共 10 集可切换）` 或 `更新至 8 集`

实现细节（`get_movie_detail` 新增字段）：
- `total_eps` — 从选集区"共 N 集"解析
- `series_status` — `全N集` / `更新至N集` / `集数未知`
- 智能归并 a123tv 数据混乱：
  - 显式完结标记（`已完结` / `全N集完结` / `[全集]`）优先
  - 若同时存在"更新至 total_eps 集" → 视为完结（a123tv 数据滞后）
  - 若"更新至 M 集"且 M < total_eps → 仍在更新

测试结果：
| 影视 | series_status | total_eps |
|---|---|---|
| 怪物（日剧） | 全10集 | 10 |
| 庆余年 2 | 全36集 | 36 |
| 庆余年 1 | 全46集 | 46 |
| 鬼灭之刃 柱训练篇 | 全8集 | 8 |
| 鬼灭之刃剧场版（电影） | （空，非剧） | 0 |

#### (c) LLM 工具描述更新
`llm_search_movie` 工具 description 补充：
- 列表返回格式：`[N] 影视名  【类别·年份】`，要求 LLM 复述标签
- 详情页流程新增提示："剧标题下方会有全 N 集/更新至 N 集"

### 代码改动
- `core/movie.py` — `_clean_title` 返回 4-tuple；`search_movies` 存 `year`；`get_movie_detail` 解析 `total_eps` + `series_status`；`format_episodes` 显示状态；`format_movie_list` 用【类别·年份】
- `main.py` — `_format_mv_page` 同步用【类别·年份】；`llm_search_movie` docstring 补充说明

## v1.7.2 — 2026-07-08

### ✨ 优化：影视搜索列表加【类别】标签

之前影视搜索结果列表显示：`[1] 怪物  [1080p · 89线路 · 日本剧 · 1080]`（4 个冗余信息挤在一起）
现在改为：`[1] 怪物  【日本剧】`（**只显示类别**），用户能一眼看出影视类型

**好处**：
- 视觉清爽：每个影视只显示一个标签
- 信息精准：类别比画质/线路数更重要（用户更关心是什么类型）
- 翻页时更易扫读

**类别识别规则**（按最长优先匹配，避免「日本」截断「日本情色片」）：
- 电视剧：国产剧 / 韩国剧 / 日本剧 / 欧美剧 / 港台剧 / 日韩剧 / 海外剧 / 香港剧 / 台湾剧 / 泰国剧
- 电影：动作片 / 喜剧片 / 爱情片 / 科幻片 / 恐怖片 / 剧情片 / 战争片 / 纪录片 / 动画片 / 犯罪片 / 悬疑片 / 奇幻片 / 家庭片 / 古装片 / 历史片 / 歌舞片 / 邵氏电影 / 4K电影
- 综艺：内地综艺 / 港台综艺 / 日韩综艺 / 欧美综艺 / 国外综艺
- 动漫：国产动漫 / 日韩动漫 / 欧美动漫 / 海外动漫 / 动漫
- 福利：里番 / 韩国情色片 / 日本情色片 / ... 等

### 代码改动
- `core/movie.py` — `_clean_title` 重构：返回 `(title, category, meta)` 3-tuple，类别作为独立字段
- `core/movie.py` — `format_movie_list` 改用 `category` 字段输出【...】标签
- `main.py` — `_format_mv_page` 同步改用 `category` 字段

## v1.7.1 — 2026-07-08

### 🐛 修复：影视搜索 URL 错位（搜索结果不精准）

**根本原因**：之前用了 a123tv 的旧搜索接口 `/index.php?m=vod-search&wd={keyword}`，但这个接口**返回首页热度列表**（与关键词无关，全站最新/最热）。
**正确的接口**是 `/s/{URL编码关键词}.html`，这才是真正的站内搜索。

| 关键词 | 旧接口（首页热度） | 新接口（真搜索） |
|---|---|---|
| 庆余年 | 24 条首页热度 | **8 条** 全是庆余年系列 |
| 怪物 | 24 条首页热度 | **36 条** 全是怪物相关 |
| 陈情令 | 24 条首页热度 | **5 条** 全是陈情令 |
| 漫长的季节 | 24 条首页热度 | **1 条** 准确命中 |
| 星际穿越 | 24 条首页热度 | **9 条** 全是星际穿越 |
| abv (不存在) | 24 条首页热度 | **0 条** ✓ 正确处理 |

### 代码改动
- `core/constants.py` — `MV_SEARCH_URL` 由 `/index.php?m=vod-search&wd={keyword}` 改为 `/s/{keyword}.html`
- `core/movie.py` — `search_movies` 优化编码（`requests.utils.quote(keyword, safe="")`），加 docstring 说明

### 备注
- a123tv 的搜索页**无翻页**：搜索结果一次性返回（最多 36 条），`<div class="w4-page"><ul></ul></div>` 是空容器
- 客户端 `format_movie_list` 仍按 8 条/页 切，但其实是把同一批结果切成多页显示
- 后续如果需要更多结果，可能要换搜索关键词（a123tv 不支持多页搜索）

## v1.7.0 — 2026-07-08

### 🎬 新功能：影视搜索（a123tv.com）

**完全替换原本基于防丢链页的中文 punycode 影视搜索（xn--ykq321c.com 系列），改为更稳定、无需登录的 a123tv.com**。

- **`/找影视 <影视名>`** — 命令式
- **LLM 工具 `search_movie`** — 自然语言（"找电影"/"找电视剧"/"追剧"等关键词自动触发）
- **自动判断类型**：
  - **电视剧** → 用户先选集数（1-N），再选播放线路（1-N）
  - **电影** → 用户直接选播放线路（1-N）
- **播放线路标签自动清洗**（HD中字 / 更新HD / 720p / 1080p / 完结等）
- **无需登录/cookie/账号密码** — a123tv.com 不需要任何认证
- **群聊合并转发**：🎬 标题 + 📡 线路标签 + 📖 简介 + 🔗 链接 + 封面图
- **私聊 HTML 文件**（复用 `generate_search_html` 模板）
- **`/movie_status`** — 检查 a123tv.com 可达性

### ⚠️ 重要变化
- **完全删除**了对 `xn--ykq321c.com` 等共享数据库中文 punycode 站点的支持（Cloudflare 拦截 + 需登录 + 多账号复杂度高）
- **WebUI 配置页**不再需要 `movie_cookie / movie_login / movie_username / movie_password` 等字段（影视频道无需任何认证）
- **`select_search_result` / `select_download_link`** 在影视会话中会被插件直接拒绝（a123tv 没有网盘，引导用户走影视专属流程）

### 新增文件
- `core/movie.py` — 影视搜索核心（313 行，含 `search_movies / get_movie_detail / format_movie_list / format_episodes / format_sources / select_episode / select_source`）

### 代码改动
- `core/constants.py` — + `MV_BASE_URL / MV_SEARCH_URL / MV_HEADERS / MV_SOURCE_ICON`
- `main.py` — + import + `_movie_sessions` + `_format_mv_page` + `/找影视` + `/movie_status` + `_run_movie_search_flow` + `search_movie` LLM 工具 + `paginate_results` 扩展 + `on_llm_request` 关键词扩展 + `on_any_message` 影视处理段
- `metadata.yaml` — 版本 1.7.0 + 影视模块说明
- `README.md` — 添加 `/找影视` 文档

## v1.5.0 — 2026-07-06

### 修复（v3.3 — 扫码后无回调）
- **扫码确认后页面不跳转** — 根本原因：Chromium 参数 `--single-process` 和
  `--disable-blink-features=AutomationControlled` 是强烈的 bot 信号，QQ OAuth 检测到
  headless 浏览器后静默阻止回调完成（用户能扫码但 redirect 永不触发）
  - **去 bot 化**：移除 `--single-process`、`--disable-blink-features=AutomationControlled`
  - **加强 stealth**：覆盖 `navigator.webdriver`(含 delete proto)、`navigator.plugins`、
    `navigator.languages`、`window.chrome`、`navigator.permissions.query`、
    `navigator.hardwareConcurrency`、`navigator.deviceMemory`
  - **事件驱动轮询**：主路径用 `page.wait_for_url("**/*.xdgame.com/**")` 事件驱动，
    不用 while-sleep 轮询（更灵敏，不丢跳转事件）
  - **context.pages 检测**：回退时遍历所有 context 页面（含弹窗/新标签页），
    任一页面跳转到 xdgame.com 即提取 cookie
  - **cookie 保底**：每 10s 检查 cookie 域名是否已出现 xdgame.com 相关键，
    若 cookie 已写入但页面未跳转，主动访问 xdgame.com/user/ 完成提取
  - **iframe 深度采样**：心跳日志输出所有 frame 的前 80 字内容，
    方便诊断扫码检测是否遗漏

### 修复（v3.2 — 真正解决字体超时）
- **QR 扫码截图超时** — 根本原因：Playwright 的 `page.screenshot()` **内置了 `document.fonts.ready` 等待机制**，
  即使用 `--disable-remote-fonts` 阻止字体下载，Playwright 仍然会等待字体 promise resolve，
  而字体下载被阻止后 promise 永不 resolve → 截图必超时。
  - **修复 A：设置 `PW_TEST_SCREENSHOT_NO_FONTS_READY=1`** — Playwright 内建环境变量，
    跳过字体 readiness 检查（参考 [GitHub #35200](https://github.com/microsoft/playwright/issues/35200)、
    [GitHub #35972](https://github.com/microsoft/playwright/issues/35972)、
    [Momentic 博客](https://momentic.ai/blog/playwright-pitfalls)）
  - **修复 B：`page.route()` 拦截所有字体请求** (`**/*.{woff,woff2,ttf,otf,eot,svg}`)，
    确保字体请求永不发出，`document.fonts.ready` 立即 resolve
  - 改用 `page.screenshot(clip=box)` 裁剪二维码区域代替 `element.screenshot()`
- **二维码元素检测不到** — QQ OAuth 的二维码 iframe 加载较慢
  - 初始等待从 3s → 5s
  - QR 查找改为带重试的循环（最长 20s，渐进间隔 2~5s）
  - 增加更多选择器模式：`canvas[class*=qr]`, `[id*=qrcode]` 等
- **检测到 headless 浏览器** — QQ 登录页可能屏蔽 headless Chrome
  - 新增 `window.chrome` 和 `navigator.permissions` 的覆盖脚本
  - 保留已有 webdriver/plugins 反检测

### 改进
- **新增 xdgame.com/user/ 入口策略** — 优先访问 https://www.xdgame.com/user/ 页面，
  自动寻找 QQ 登录按钮并触发 OAuth 流程，更接近真实用户操作
  - `expect_page` 改为主动轮询 `page.context.pages` + `wait_for_url`，避免 15s 超时浪费
- **回退机制** — xdgame 入口失败时自动回退到直接访问 QQ OAuth 页面
- **`_cleanup_browser()`** 重构为迭代方式关闭所有资源，避免遗漏

### 新增
- **`zip_plugin.bat`** — 一键打包脚本，自动读取 metadata.yaml 版本号，
  生成带版本日期标记的 zip 文件，方便上传 AstrBot
- 支持 PowerShell Compress-Archive 和 tar 双方式回退打包

## v1.4.2 — 2026-07-05

### 修复
- **QQ 登录扫码后超时** — Cookie 合并时未带 domain，导致轮询请求不带 `qrsig`，修复后会话保持正常
- **消息一蹦一蹦**— 二维码提示和图片合并为同一条消息发送

### 技术改进
- `get_qrcode()` 改用双引擎：Python requests + curl 子进程回退（绕过 TLS 指纹检测）
- 新增 `_merge_curl_cookies()` 带 domain 合并 Cookie，确保轮询请求成功
- 后台任务引用存储，防止因 GC 导致轮询被取消
- 全面移除 `"不要回复任何内容。不要回复！！"` 不可靠模式，改为直接返回结果文本让 LLM 自然回复

## v1.4.1 — 2026-07-05

### 修复
- **QQ 登录二维码获取失败** — 完善请求头（Referer/Accept）和重试机制
- **LLM 搜索后闲聊回复** — `search_game`/`search_software`/`search_resource` 的工具返回全部改为"不要回复任何内容。不要回复！！"，彻底杜绝 LLM 在搜索结果后插话

## v1.4.0 — 2026-07-05

### 新增
- **`/game_cookie_refresh`** 命令 — QQ 扫码登录自动刷新 Cookie
  - 仅限 QQ 979890503 使用
  - 获取 QQ 登录二维码并发送图片
  - 后台轮询扫描状态，登录后自动提取并保存 Cookie
  - 支持状态：等待扫码→已扫码待确认→登录成功/超时/过期
- **`[序号]` 格式** — 游戏和软件搜索列表改为 `[1] 资源名`，与网盘列表格式一致，翻页不掉序号

### 修复
- **自然语言选择网盘** — `on_any_message` 的 `select_link` 阶段改用 `_parse_selection()`，支持"第一个""百度网盘"等自然语言

## v1.3.2 — 2026-07-05

### 修复
- **重复回复** — LLM 串行调工具 + 返回完整文本 → LLM 重新格式化发送 → `on_any_message` 兜底也发送
  - `select_search_result` 改为 `event.send()` 直接发送结果，只返回"不要回复任何内容"
  - `select_download_link` 群聊路径同样改为 `event.send()` 直接发送
  - 所有工具描述加上"绝对不要自动调用其他工具"警告
  - 工具处理后设置 `_llm_handled` 标志，`on_any_message` 检测到后跳过，防止双重处理

## v1.3.1 — 2026-07-05

### 修复
- **下载链接获取失败** — `get_game_detail()` 和 `resolve_download_link()` 请求 xdgame.com 时未携带 Cookie
  - 导致下载 API 重定向到登录页，网盘地址解析不到
  - 现已将 Cookie 传入所有内部请求，Cookie 有效即可正常获取下载链接

## v1.3.0 — 2026-07-05

### 新增
- **`/game_cookie`** 命令 — 检测游戏资源站 Cookie 状态
  - ✅ 有效 — 可正常搜索下载
  - ❌ 失效 — 提示重新登录
  - ⚠️ 次数用尽 — 提示重新获取
  - ❓ 无法确认 — 建议更新
- 所有 LLM 工具改用 `event.send()` + `return` 双通道输出，彻底解决分段
- `paginate_results` 翻页工具（LLM 路径不掉序号）
- 截图数量不限（去掉 `[:3]`）
- 自然语言选择支持（"第一个""最后一个"等）

## v1.2.0 — 2026-07-05

### 关键修复：LLM 编造虚假结果
- **问题**：LLM 在调用工具前后各编造文本，用户看到3条消息分不清真假
- **修复**：所有工具改为 return 格式化文本（不再单独 event.send）
  - LLM 收到工具返回文本 → 将其作为回复发送 → 用户只看到1条消息
  - 所有真实内容带 `【暮黎资源】` 标签，用户一眼可辨

### 关键修复：会话丢失
- **问题**：用户选网盘→LLM不调工具→编造"已取消"；下次选→会话被覆盖→"无活跃会话"
- **修复**：防覆盖机制 + on_any_message 兜底拦截

### 新增：完整日志系统
- 所有关键步骤输出 `[暮黎资源]` 标签日志
- 日志格式：`[暮黎资源] search_resource('死亡搁浅') → 游戏3条 会话已创建`

### 架构简化
- 工具统一 return 文本，不再 event.send
- 移除不可靠的 asyncio.create_task session_waiter
- 代码从 1686行 → 1401行

---

## v1.1.0 — 2026-07-05

### Bug 修复
- 修复文本分段发送（LLM虚构结果）
- 修复虚假回复（新增 select_search_result / select_download_link 工具）
- 修复双重回复（移除 on_natural_search）

### 新增
- search_resource 统一智能搜索（自动判断游戏/软件）
- 智能回退（游戏无结果自动尝试软件搜索）
- session_waiter 导入
