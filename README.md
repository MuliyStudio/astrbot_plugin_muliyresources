<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/logo.png" width="300" alt="暮黎 Muliy Logo">
</p>

<h1 align="center">🍄 暮黎资源聚合</h1>

<p align="center">
  <strong>一个 AstrBot 插件，搞定你的影视 / 游戏 / 软件 / 短剧 / 小说搜索与日报推送</strong>
</p>

<p align="center">
  <a href="https://github.com/MuliyStudio/astrbot_plugin_muliyresources/releases"><img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/badges/version.svg?v=1.16.1" alt="版本"></a>
  <img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/badges/astrbot.svg" alt="AstrBot 版本">
  <img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/badges/platform.svg" alt="支持平台">
  <img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/badges/novel.svg" alt="so-novel">
  <img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/badges/license.svg" alt="MIT">
</p>

---

> ⚠️ **免责声明**：本插件仅用于内部测试与学习交流，请勿用于商业用途，侵权请联系删除。
> 
> 💬 交流群：**1084453386**

---

## 📑 目录

[功能特性](#-功能特性) · [效果预览](#-效果预览) · [安装](#-安装) · [快速上手](#-快速上手小白使用手册) · [配置指南](#-配置指南) · [功能详解](#-功能详解) · [依赖说明](#-依赖说明) · [常见问题](#-常见问题faq) · [更新日志](#-更新日志) · [交流群](#-交流群) · [许可证](#-许可证)

---

## ✨ 功能特性

| | 功能 | 说明 |
|---|------|------|
| 🎬 | **影视搜索（pdy0 默认 / 片库备用）** | 默认走 **pdy0 系站点**（片库注册站，地址发布页 `988lm.com` 自动选可用站点，免登录，在线播放 + 磁力 + 网盘下载）；搜索可能弹 4 位图片验证码，装 `ddddocr` 自动识别，否则把验证码图发给用户手动输入。`movie_source=old` 时切到**片库主站**（需 `muliy_username`/`muliy_password` 或 `muliy_cookie`）。剧集自动选集数、电影直接选线路 |
| 🎮 | **游戏搜索** | 搜索 xdgame.com，返回多网盘下载链接（百度/夸克/阿里/123/天翼…） |
| 💿 | **软件搜索** | 搜索 x6d.com 软件/应用/工具资源 |
| 📺 | **短剧搜索** | 搜索网盘贴吧短剧（wangpant8.com），选中后直接返回**夸克网盘资源链接** |
| 📖 | **小说搜索与下载** | 基于 [so-novel](https://github.com/freeok/so-novel) 多源聚合，搜书名/作者 → 选源 → 选格式（txt/epub/html/pdf）→ 整本发送 |
| 🖼️ | **长列表出图** | 小说 / 网盘 / 游戏 / 软件 / 影视 / 短剧搜索结果，以及积分卡、积分排行，条目多时自动排版成图片（思源黑体正文 + 思源宋体标题 + MDI 图标，带 logo、序号、页码与操作提示），回复数字选择与翻页指令不变 |
| 📰 | **日报推送** | 软件 / 游戏 / 影视 / 短剧四套**定时日报**，自动渲染成图片以文件形式推送到群 |
| 🎵 | **网易云语音名片** | 发网易云链接/小程序卡片，自动解析成**语音**发出来（内置直连，零部署） |
| 🎞️ | **VIP 视频解析** | 爱奇艺 / 腾讯 / 优酷 / 芒果 VIP 链接自动解析成播放直链（发送前验证接口，失效自动换下一个） |
| 🧠 | **LLM 自然语言** | 接入 LLM 后直接说「帮我找原神」「想看流浪地球」即可，无需记命令 |
| 💰 | **签到与积分** | `/签到` 领取每日积分，并生成一张带 **Bing 每日壁纸 / Epic 喜加一 / 每日一言 / 资源推荐** 的签到卡片；搜索资源按类型扣除积分，积分跨群聊全局共享 |
| 🤚 | **表情包娱乐** | `摸摸 @某人` / `给你一脚 @某人` / `给我按摩 @某人` 生成 GIF |
| 🔐 | **入群审核（QQ）** | 新成员入群 @ 他并发送「20-100 加减法」**图形验证码**，限时答对才留下，答错达上限/超时自动移出群聊 |

---

## 🖼️ 效果预览

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/screenshots/search_drama.jpg" width="45%" alt="短剧搜索">&nbsp;
  <img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/screenshots/drama_daily.jpg" width="45%" alt="短剧日报">
</p>

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/screenshots/movie_daily.jpg" width="45%" alt="影视日报">&nbsp;
  <img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/screenshots/software_daily.jpg" width="45%" alt="软件日报">
</p>

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/screenshots/game_daily.jpg" width="45%" alt="游戏日报">
</p>

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/screenshots/checkin_card.jpg" width="45%" alt="每日签到卡片">&nbsp;
  <img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/screenshots/search_novel_card.jpg" width="45%" alt="小说搜索列表">
</p>

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/screenshots/search_pan_card.jpg" width="45%" alt="网盘资源列表">
</p>

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/screenshots/points_card.jpg" width="45%" alt="积分卡片">&nbsp;
  <img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/screenshots/points_rank.jpg" width="45%" alt="积分排行">
</p>

> 以上均为**真实运行效果**（从左到右、上到下）：短剧搜索 → 网盘链接 · 短剧日报（杂志风）· 影视日报（毛玻璃）· 软件日报（夏日风）· 游戏日报（卡通风）· 签到卡片 · 小说搜索列表 · 网盘资源列表 · 积分卡片 · 积分排行。
> 条目较多的搜索列表会自动排版成图片（带 logo、序号、页码与操作提示），回复数字选择、翻页指令不变。

---

## 📦 安装

### 方式一：AstrBot 插件市场（⭐ 推荐）

1. 打开 AstrBot WebUI → **插件管理**
2. 搜索「**暮黎资源聚合**」→ 点击安装
3. 安装完成后**重启 AstrBot**，插件自动安装依赖

### 方式二：手动安装

```bash
cd <astrbot>/data/plugins/
git clone https://github.com/MuliyStudio/astrbot_plugin_muliyresources.git
# 重启 AstrBot
```

### ✅ 首次使用检查清单

装好插件重启后，**大部分功能直接可用**，不用配任何东西：

| 功能 | 装好即用？ | 备注 |
|------|:---:|------|
| 🎬 影视搜索（pdy0 默认） | ✅ | 免登录即用；想用片库主站作备用 → 配 `muliy_username` + `muliy_password`（或 `muliy_cookie`），并把 `movie_source` 设为 `old` |
| 🎮 游戏搜索 | ✅ | 默认走 xdgame，配账密后可用 `/game_cookie_refresh` 自动登录 |
| 💿 软件搜索 | ✅ | |
| 📺 短剧搜索 | ✅ | 搜「搜短剧XX / 看短剧XX」即可，返回夸克网盘资源链接 |
| 📰 软件 / 游戏 / 影视 / 短剧日报 | ✅ | 无浏览器也能出图（Pillow 兜底）；想更精美 → 装 Chromium（可选） |
| 🎵 网易云语音名片 | ✅ | 免费歌直接解析；VIP 歌需填会员 Cookie |
| 🎞️ VIP 视频解析 | ✅ | |
| 🤚 表情包 | ✅ | |
| 🔐 入群审核（QQ） | ⚙️ 需手动开启 | 默认关闭；在 `verify` 组开启并填生效群号，机器人需为群管理员 |
| 📖 **小说搜索** | ⚠️ 需额外部署 | 需另跑一个 so-novel 服务，见下文 |

> **想省事的话**：什么都不用装、什么都不用配，装好插件就能搜影视/游戏/软件、能收日报、能发语音。

---

## 🚀 快速上手（小白使用手册）

### 第 1 步：先试试命令式用法（无需任何配置）

直接对机器人发下面任意一条：

```
/找影视 流浪地球        # 搜索影视
/找游戏 黑神话悟空      # 搜索游戏
/找软件 微信            # 搜索软件
/找短剧 穿越            # 搜索短剧（返回夸克网盘链接）
/找小说 斗破苍穹        # 搜索小说（需 so-novel）
/software_report        # 手动触发软件日报
```

发「想看电影：流浪地球」「帮我找原神」这类自然语言也**会被自动识别**并路由到对应搜索。

### 第 2 步：接入 LLM，体验自然语言

在 AstrBot 里配好任意 LLM 提供商后，直接说：

```
用户：想看流浪地球
机器人：🎬 影视搜索结果（共 5 个，第 1/1 页）……
用户：1
机器人：已选择：流浪地球 …在线播放/网盘资源
用户：1
机器人：🎬 流浪地球 + 播放链接……
```

> LLM 只是「翻译官」，搜索/详情/下载全部由插件工具执行，不会编造结果。

### 第 3 步：按需开启高级功能

| 想用 | 需要配置 |
|------|---------|
| 片库主站影视（备用源） | `movie` → `movie_source=old` + `muliy_username`/`muliy_password`（账号密码，插件自动登录）或 `muliy_cookie`（浏览器登录 Cookie，含 `app_auth`、`PHPSESSID`） |
| 游戏自动登录刷新 Cookie | `game` → `xdgame_username` + `xdgame_password` |
| 小说搜索下载 | 部署 so-novel + `novel` → `sonovel_base_url` |
| 网易云 VIP 歌曲 | `music` → `wyy_cookie`（黑胶会员 `MUSIC_U`） |
| 日报推到群聊 | 各自分组填 `xxx_group_ids`（软件/游戏/影视/短剧独立） |
| 入群审核（QQ 图形验证码） | `verify` → 开启 `join_verify_enabled` + 填 `join_verify_group_ids`（机器人需为群管理员） |

### 常用命令速查

| 命令 | 权限 | 说明 |
|------|------|------|
| `/找游戏 <名称>` | 所有人 | 搜索游戏 |
| `/找软件 <名称>` | 所有人 | 搜索软件 |
| `/找影视 <名称>` | 所有人 | 搜索影视（自动选源） |
| `/找短剧 <名称>` | 所有人 | 搜索短剧（返回夸克网盘链接） |
| `/找小说 <名称>` | 所有人 | 搜索小说（需 so-novel） |
| `/game_cookie_refresh` | 管理员 | 自动登录 xdgame 刷新 Cookie |
| `/game_cookie` | 所有人 | 查看游戏 Cookie 状态 |
| `/movie_cookie` | 管理员 | 查看/检测/设置片库 Cookie（`/movie_cookie set <cookie>`） |
| `/software_report` `/game_report` `/movie_report` `/drama_report` | 可配置 | 手动触发日报 |
| `/wyy <链接或ID>` | 所有人 | 手动解析网易云歌曲为语音 |
| `/wyy_login` | 管理员 | 网易云扫码登录（自动写入会员 Cookie） |
| `/novel_status` | 所有人 | 检查 so-novel 是否可达 |
| `/签到` `/每日签到` | 所有人 | 每日签到领取积分（连续签到加成 + Bing 壁纸/天气/一言/推荐卡片） |
| `/积分` `/我的积分` | 所有人 | 查看自己的积分、连续签到与搜索消耗 |
| `/积分排行` | 所有人 | 查看积分排行榜（前 10 名） |
| `/积分管理 <用户ID> <数量>` | 管理员 | 增减用户积分（正加负扣）；`设置 <ID> <数量>` 直接设置，`查询 [ID]` 查询（省略 ID 查自己）；目标支持 `@某人`、`回复`（引用对象）或 `平台:用户ID` |
| `/movie_status` | 所有人 | 检查影视站可达性 |
| `/入群验证 状态` | 管理员 | 查看入群审核配置与在验证人数 |
| `/入群验证 测试` | 管理员 | 发送一张示例验证码图片（不修改群成员） |

> 开启 LLM 后，以上功能均可自然语言触发，无需记命令。
>
> ⚠️ `/积分管理` 的「管理员」指 **AstrBot 管理员**（WebUI 配置里的管理员ID列表），群主/群管理员默认没有权限。

### 😜 表情包触发（无需 @，直接发）

| 表情 | 触发词 | 说明 |
|------|--------|------|
| 🤚 摸头杀 | `摸摸` / `摸头` / `pat` / `rua` + `@某人` | 无 @ 摸自己 |
| 🐴 舔狗 | `给你一脚` / `踹` / `kick` + `@某人` | 马踢舔狗 GIF |
| 💆 按摩 | `给我按摩` / `给我揉揉` + `@某人` | 柴犬按摩 GIF |

---

## ⚙️ 配置指南

在 AstrBot WebUI → 插件设置 →「暮黎资源聚合」中，按分组填写。**大部分留空即可用默认功能。**

> 配置页已按使用频率重排：图片渲染 → 游戏 / 软件 / 影视 → 短剧 / 小说 → 音乐 / VIP / 审核 / 积分。
> 账号凭据、日报时间、超时等高级项默认收进每组的「**更多配置**」，展开才显示；关掉某个总开关（日报、积分、入群审核）时，相关项会自动隐藏。

### 🎮 游戏（game）

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `xdgame_username` / `xdgame_password` | `""` | xdgame 账号密码（用于 `/game_cookie_refresh` 自动登录） |
| `cookie` | `""` | xdgame 登录 Cookie（自动登录后自动写入，一般不用手填） |
| `game_source` | `auto` | 游戏源：`auto`（有 xdgame 账密走 xdgame，否则 switch618）/ `xdgame` / `switch618` |
| `max_search_results` | `32` | 游戏搜索最大结果数 |
| `game_report_enabled` | `true` | 游戏日报开关 |
| `game_schedule_hour` / `minute` | `23:00` | 游戏日报定时（独立） |
| `game_group_ids` | `[]` | 游戏日报推送群号 |
| `game_report_max` | `24` | 游戏日报每期上限 |

### 🎬 影视（movie）

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `movie_source` | `""` | `new` / 留空 = **pdy0（默认）**；`old` = 片库主站（备用，需登录）。兼容旧写法 `片库`/`a123tv`（都视为 old） |
| `pdy_auto_captcha` | `true` | pdy0 搜索验证码自动识别；需 `pip install ddddocr`，未安装时把验证码图发给用户手动输入 |
| `muliy_username` / `muliy_password` | `""` | **片库主站（备用源）账号密码**：仅 `movie_source=old` 时需要，插件自动登录 |
| `muliy_cookie` | `""` | **片库主站（备用源）Cookie**（`app_auth=...;PHPSESSID=...`，用 `;` 隔开）。与账号密码二选一，两者都填时 Cookie 优先。⚠️ 勿填 `browser_verified`/`browser_pow`（插件自动求解 PoW） |
| `muliy_release_url` | `""` | 片库系发布页（默认挂了.com，留空即可） |
| `muliy_cache_ttl` | `3600` | 片库主站登录态缓存秒数 |
| `movie_report_*` / `movie_group_ids` / `movie_sections` | — | 影视日报开关/定时/群/区块（mv电影·tv剧集·ac动漫；日报 pdy0 优先、片库备用） |

### 🎵 网易云（music）

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `wyy_auto_parse` | `true` | 自动识别网易云链接/卡片并解析成语音 |
| `wyy_backend` | `direct` | `direct`（内置直连，**零部署推荐**）/ `custom`（自建实例） |
| `wyy_custom_url` | `""` | 仅 `custom` 后端需要：自建 NeteaseCloudMusicApi 地址 |
| `wyy_cookie` | `""` | 黑胶会员 Cookie（`MUSIC_U=...`），解析 VIP 歌曲用 |
| `wyy_music_type` | `standard` | 音质：standard/exhigh/lossless/hires/sky/jymaster |
| `wyy_clip_seconds` | `600` | 最大语音时长（秒），默认整曲 |
| `wyy_audio_format` | `wav` | mp3 / wav |
| `wyy_proxy` | `""` | 网易云请求代理（云服务器 IP 被风控时填住宅代理） |

### 📖 小说（novel）

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `sonovel_base_url` | `http://127.0.0.1:7765` | so-novel 服务地址 |
| `sonovel_search_limit` | `20` | 每源结果上限 |
| `sonovel_format` | `["txt"]` | 默认下载格式（txt/epub/html/pdf） |
| `sonovel_timeout` | `30` | 搜索超时（秒） |
| `sonovel_download_timeout` | `600` | 整本下载超时（秒） |

### 🖼️ 长列表图片（list_card）

> 小说 / 网盘 / 游戏 / 软件 / 影视 / 短剧搜索结果、积分卡与积分排行，条目较多时自动排版成一张图片（白纸 + 网格 + 暖黄高亮，思源黑体正文、思源宋体标题、MDI 图标）；回复数字选择、翻页指令与原来完全一致。

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `list_card_enabled` | `true` | 长列表图片总开关（关闭后全部回到纯文本） |
| `list_card_threshold` | `5` | 结果条数大于该值就出图；条目少但纯文本很长（>400 字）时也会自动出图 |

卡片用本地渲染：插件初始化时后台预热 Chromium，单张约 0.1–0.3 秒，同一张卡片 10 分钟内命中缓存；空闲 10 分钟自动释放浏览器内存。渲染失败或未安装 Playwright 时自动回退文本，功能不受影响。

字体为 SIL OFL 授权的思源黑体 / 思源宋体子集（GB2312 常用字 + 标点）：卡片用 4.5 MB，日报用 Heavy 子集 3.4 MB，随插件打包，不依赖服务器装没装中文字体。卡片文本会自动去掉 emoji 与装饰符号，不依赖 emoji 字体。

### 📺 短剧（shortdrama）

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `drama_enabled` | `true` | 短剧搜索总开关（`搜短剧XX` / `看短剧XX`） |
| `drama_search_limit` | `20` | 单次搜索结果上限 |
| `drama_report_enabled` | `true` | 短剧日报开关 |
| `drama_schedule_hour` / `drama_schedule_minute` | `21:00` | 短剧日报定时（独立） |
| `drama_group_ids` | `[]` | 短剧日报推送群号 |
| `drama_report_max` | `12` | 短剧日报每期上限 |
| `drama_timeout` | `15` | 请求超时（秒） |

### 💰 签到与积分（points）

> 积分按用户（平台 + 用户ID）全局保存，跨群聊/私聊共享；数据文件为 AstrBot data 目录下 `plugin_data/astrbot_plugin_muliyresources/points.json`，覆盖安装/热重载不丢。

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `points_enabled` | `false` | 签到积分总开关（关闭时搜索不扣积分） |
| `points_initial` | `0` | 新用户初始积分 |
| `checkin_points` | `10` | 每日签到基础积分 |
| `checkin_streak_bonus` | `0` | 连续签到每日额外加成（第 2 天起） |
| `checkin_streak_max` | `7` | 连续加成最多累计天数 |
| `checkin_card_enabled` | `true` | 签到成功卡片（HTML 出图；失败自动回退文字） |
| `checkin_info_module` | `epic` | 卡片左下内容：`epic` 喜加一 / `history` 历史上的今天 / `poem` 今日诗词 / `weather` 天气 / `off` 关闭 |
| `checkin_weather_city` | 空 | 仅 `weather` 模式生效；留空按服务器出口 IP 自动定位 |
| `checkin_recommend_dynamic` | `true` | 推荐优先从当前搜索源动态取：影视按 pdy0 / 片库主站当前源随机、游戏按当前源随机、软件从 x6d 随机；失败回退静态清单 |
| `checkin_recommend_games` | 见后台 | 推荐游戏清单，每行 `名称|一句话推荐`，每天轮换一款 |
| `checkin_recommend_software` | 见后台 | 推荐软件清单，格式同上 |
| `checkin_recommend_movies` | 见后台 | 推荐影视清单，格式同上 |
| `points_cost_game` | `5` | 每次成功搜索游戏消耗积分（0=免费） |
| `points_cost_software` | `5` | 每次成功搜索软件消耗积分 |
| `points_cost_movie` | `5` | 每次成功搜索影视消耗积分 |
| `points_cost_drama` | `5` | 每次成功搜索短剧消耗积分 |
| `points_cost_novel` | `5` | 每次成功搜索小说消耗积分 |

> 仅在**搜到结果**时扣费；未找到、接口失败或用户主动取消不扣积分。搜索前会检查余额，不足时提示先 `/签到`。
>
> 签到卡片数据源：Bing 每日壁纸、Epic 喜加一 / 历史上的今天 / 今日诗词 / UAPI 天气、Hitokoto 每日一言；Bing 按天缓存，Epic 缓存 30 分钟，历史/诗词缓存 6 小时，一言按天缓存，天气缓存 30 分钟，动态推荐按「类型 + 源 + 日期」缓存一天。任一接口失败时卡片会显示占位内容或自动降级，不影响签到本身。推荐清单留空即不显示该类型。

### 🔐 入群审核（verify）

> 仅支持 **QQ（aiocqhttp / OneBot v11，如 NapCat、Lagrange）**，且机器人需为**群管理员**（撤回/踢人依赖管理权限）。

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `join_verify_enabled` | `false` | 入群审核总开关（默认关，开启后生效） |
| `join_verify_group_ids` | `[]` | 生效群白名单，留空表示**所有群**生效（建议填写） |
| `join_verify_timeout` | `120` | 验证限时（秒），超时移出群聊 |
| `join_verify_max_attempts` | `2` | 答题机会，第 2 次答错立即移出群聊 |
| `join_verify_recall` | `true` | 撤回机制：验证期间撤回成员发言，结束时撤回机器人本次发的验证消息（清屏不留痕） |
| `join_verify_kick` | `true` | 失败时移出群聊（关闭则只清屏不踢人） |
| `join_verify_welcome_text` | `✅ 验证成功，欢迎加入群聊！` | 验证通过后**唯一保留**的消息；留空则静默通过（不发任何消息） |

### 🎞️ VIP 解析（vip_video）/ 🌐 浏览器（browser）

- `video_vip_parse`（默认 `true`）：VIP 视频自动解析开关
- `video_vip_timeout`：单个解析接口超时（毫秒）
- `browser_channel` / `browser_exe`：日报 / VIP 解析共用浏览器（留空自动；日报无浏览器时自动用 Pillow 兜底出图）
- 解析接口：菜单里 **M1907 / 789** 为实测可用（⭐）；其余接口**实时从片库主站 `/zjx` 读取**（15 分钟缓存，失败回退内置列表）。选择接口后插件会先验证播放器，失效自动尝试下一个可用接口，并保留本次解析让你换序号重试。
- 片库主站 `https://www.xn--wcv59z.com/zjx` **免登录可用**（默认「冰豆解析」`bd.jx.cn`）；该页是 JS + PoW 前端，插件用浏览器完成验证后读取接口下拉框，不直接拼 `/zjx?url=`。

### ⚠️ 配置注意事项（从配置项提示里精简后移到这里）

- **片库 Cookie**（`muliy_cookie`）：只需 `app_auth`、`PHPSESSID`；**不要填 `browser_verified` / `browser_pow`**（这两个与 IP/域名绑定、极易失效，插件会自动重新求解 PoW）。填了会导致详情/播放页始终被「浏览器安全验证」页拦截。
- **片库发布页**（`muliy_release_url`）：留空即可，插件会用默认发布页自动探测当前可用域名；仅当默认发布页不可用时才需改为其它同系发布页。
- **so-novel**（`sonovel_base_url`）：必须以 Web 模式启动（`-Dmode=web`，默认端口 7765），否则 7765 不监听。Docker 且与 AstrBot 同宿主机时，填 Docker 网关 `http://172.17.0.1:7765`（别填公网 IP）。
- **网易云**（`wyy_*`）：`wyy_backend=direct`（默认）零部署即可用；网易云 CDN 可能封锁云服务器 IP，若发语音失败会自动降级为「歌曲名片 + 播放链接」。被风控时可在 `wyy_proxy` 填代理换出口 IP。
- **游戏 Cookie**：`cookie` / `switch618_cookie` 由 `/game_cookie_refresh` 自动写入，一般无需手填。

---

## 📖 功能详解

### 🎬 影视：pdy0 默认，片库主站备用

- **默认走 pdy0 系站点**（片库的注册站，注册开放；原片库主站已关闭注册）：免登录即可搜索/播放/取网盘，资源含**在线播放（多线路）+ 磁力 + 网盘下载**。插件会从地址发布页 `https://www.988lm.com/` 自动读取当前可用站点（pdy0~6 / pys1~3），并发探测延迟后自动选站，站点失效会自动切换。
- **搜索验证码**：pdy0 的搜索页会弹 4 位图片验证码（字母数字混合）。安装 `ddddocr`（`pip install ddddocr`）后插件自动识别（最多换 3 张重试）；未安装或识别失败时，插件把验证码图片直接发到当前会话，用户回复图中验证码即可继续搜索，验证通过后同会话内复用登录态。
- **搜索限流**：pdy0 要求两次搜索间隔 3 秒，插件会自动等待并重试；相同关键词 5 分钟内走缓存，避免频繁请求。
- **片库主站（备用）**：把 `movie_source` 设为 `old`，并配置 `muliy_username`+`muliy_password`（或 `muliy_cookie`）。片库主站会自动探测最低延迟节点、自动求解「浏览器安全验证」PoW，资源含**在线播放 + 网盘**。
- 关键字：`new`（或留空）= pdy0；`old` = 片库主站。旧的 `片库` / `a123tv` 写法仍兼容（都归到 old）。
- 指令 `/找影视` 与 LLM「想看XX」统一走同一套源路由，无需手动切换。
- **会话内回复免 @**：出搜索结果后，回复数字选片、翻页、选集、选线路/网盘、回复 pdy0 验证码都不需要 @ 机器人；@ 了也能识别。只有首次发起搜索需要 @ 或唤醒词。
- `/movie_cookie` 命令可随时查看 / 检测片库主站登录态（Cookie 或账号密码）；`/movie_status` 查看当前源状态。
- 影视日报：**pdy0 优先**（免登录抓最新列表），pdy0 不可用且配了片库凭据时自动回退片库主站。

### 🔐 游戏 Cookie 刷新

xdgame Cookie 约 30 天过期。配置账密后执行 `/game_cookie_refresh`：

1. 插件纯 HTTP 自动登录 xdgame，**自动求解新版「人机验证」(Cap PoW)**，无需人工输验证码
2. 登录成功后 Cookie 自动保存，无需再操作

### 📺 短剧：搜索 → 网盘链接

- 数据源为**网盘贴吧**（wangpant8.com，Next.js 站点，无需登录/签名）。
- 发「搜短剧XX / 看短剧XX」或 `/找短剧 <剧名>`：搜索 → 回复序号选择 → 直接返回**剧名 + 夸克网盘资源链接**。
- 资源全部为**夸克网盘**，复制链接转存即可观看。

### 🔐 入群审核：图形验证码（QQ）

- 新成员入群时，机器人 @ 他并发送一张 **20-100 以内加减法**的图形验证码（随机底色 + 多层干扰线/弧线 + 大量噪点色斑 + **逐字符随机旋转**，抗 OCR 验码机器人）。
- 成员在 **2 分钟**内回复正确答案即通过；**答错 2 次**或**超时**会被移出群聊。
- **验证通过**：撤回机器人本次发的所有验证消息，只保留一条欢迎语（`join_verify_welcome_text` 可配置，留空则静默通过）。
- **验证失败/超时**：同样先撤回所有验证消息，再把这些成员移出群聊，群里不留痕。
- 验证期间自动**撤回**该成员的发言防刷屏；非数字发言不计入答题次数。
- **为什么不禁言？** QQ 中被禁言的成员**无法发送任何群消息**，「先禁言再让他在群里答题」在协议上无法成立，所以本功能用「撤回非答案发言」替代禁言来防刷屏。
- 成员退群/被踢会自动清理验证状态并撤回首屏消息，插件卸载或热重载会取消后台超时任务。

### 🎮 日报推送

- 四套日报（软件 / 游戏 / 影视 / 短剧）各自独立定时、独立群配置。
- **渲染（三级降级，无需装任何东西）**：
  1. 本地 Chromium（若已安装）→ 最高清
  2. **AstrBot 内置 `html_render`**（官方 T2I 服务）→ 装好插件即用，无需浏览器
  3. Pillow 纯 Python 兜底 → 永远可用
- 以**文件形式**发送到群，绕开发图体积上限。
- **重装/重启不会重复补发**：四套日报的「今日已发送」状态持久化在 data 目录（`plugin_data/astrbot_plugin_muliyresources/daily_reports_state.json`，插件目录之外），重装或热重载后自动恢复，不会把当天已发过的日报再抓一遍。
- **底部留白自适应**：内置 T2I 按固定视口高度出图，内容不足一屏时底部会留白；渲染后会自动裁掉与页面底色一致的空白行（四套日报通用）。

### 📖 小说：so-novel 部署（唯一需要额外服务的功能）

so-novel 是独立服务，跑起来后小说搜索/下载才能用：

```bash
# Docker 一键起（Web 模式，端口 7765）
docker run -d --name sonovel -p 7765:7765 \
  -e JAVA_TOOL_OPTIONS="-Dmode=web" \
  ghcr.io/freeok/sonovel:latest
```

然后在插件 `novel` 分组填：

- **so-novel 与 AstrBot 同宿主机（都是 Docker）**：`http://172.17.0.1:7765`
- **AstrBot 非 Docker / 同机**：`http://127.0.0.1:7765`
- **跨机器**：`http://<内网IP>:7765`

> 更多部署与排错细节见 [SO-NOVEL部署指南.md](./SO-NOVEL%E9%83%A8%E7%BD%B2%E6%8C%87%E5%8D%97.md)。

### 🎵 网易云

- **免费歌**：发链接/卡片即自动解析成语音，零配置。
- **VIP 歌**：填 `wyy_cookie`（黑胶会员 `MUSIC_U`）或 `/wyy_login` 扫码。
- **云服务器被风控**（扫码提示「设备环境异常」/ 解析 403）：直接手填已登录的 `MUSIC_U` 到 `wyy_cookie`（推荐），或填 `wyy_proxy` 住宅代理。

---

## 🔧 依赖说明

| 依赖 | 用途 | 必需？ |
|------|------|:---:|
| Pillow | 图片生成 / 日报兜底渲染 | ✅ 必需 |
| requests / bs4 / apscheduler / httpx / aiohttp | 搜索 / 解析 / 调度 | ✅ 必需（AstrBot 一般自带） |
| **Chromium**（`playwright install chromium`） | 日报高清 HTML 渲染、搜索列表卡片出图 | ⚠️ 可选（日报有内置渲染 / Pillow 兜底；列表卡片没装 Chromium 时自动回退文本） |
| **so-novel** | 小说搜索下载 | ⚠️ 可选（仅小说功能需要） |
| ffmpeg | 网易云语音截取 | ⚠️ 可选（不装发完整音频） |

> 日报渲染默认走三级降级：**本地 Chromium（若已安装）→ AstrBot 内置 `html_render`（官方 T2I 服务）→ Pillow 纯 Python**，三级都不需要你手动装任何东西。
> 若想用本地 Chromium 获得最高清渲染（可选），国内可加速安装：

```bash
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright \
  python -m playwright install chromium
```

---

## ❓ 常见问题（FAQ）

**Q：提示「Cookie 已失效」？**
执行 `/game_cookie_refresh` 自动刷新（需已配 xdgame 账密）。

**Q：日报提示「图片渲染失败」？**
新版已内置 Pillow 兜底渲染，**不再需要 Chromium**。若仍失败，看 AstrBot 日志中的具体报错。

**Q：小说搜索提示「so-novel 不可达」？**
确认 so-novel 容器加了 `-e JAVA_TOOL_OPTIONS="-Dmode=web"`（默认镜像启动的是 TUI 菜单不监听端口），并填对 `sonovel_base_url`。

**Q：LLM 不调用搜索工具？**
确认 AstrBot 已配置 LLM 且开启了工具调用；关闭 LLM 也能用 `/找XX` 命令。

**Q：网易云扫码提示「设备环境异常」？**
云服务器 IP 被网易云风控，见上文「云服务器被风控」方案：直接手填 `MUSIC_U` 到 `wyy_cookie` 即可。

**Q：支持哪些平台？**
aiocqhttp(OneBot v11)、企业微信、个人微信、QQ官方、Telegram、飞书、Slack、Discord 等。非 OneBot 平台自动用「文本+图片 / Markdown 卡片」发送结果，不依赖合并转发。

---

## 📝 更新日志

见 [CHANGELOG.md](./CHANGELOG.md) 与 [GitHub Releases](https://github.com/MuliyStudio/astrbot_plugin_muliyresources/releases)

---

## 💬 交流群

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/MuliyStudio/astrbot_plugin_muliyresources@main/assets/qq_group_qrcode.jpg" width="240" alt="暮黎交流群二维码">
</p>

<p align="center">
  <strong>QQ 群：1084453386</strong> · 扫码或搜群号加入，欢迎反馈问题与交流
</p>

---

## 📄 许可证

MIT License © 2026 暮黎 Muliy
