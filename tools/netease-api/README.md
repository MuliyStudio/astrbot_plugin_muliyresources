# 自建 NeteaseCloudMusicApi 部署与自检指南（手机 / 服务器 / 电脑 通用）

> 插件 `astrbot_plugin_muliyresources` 的「网易云语音名片」功能**只支持自建后端**（`wyy_custom_url`）。
> 公共解析站（wyapi / qzxdp）已在 v1.9.3 移除（被网易云 WAF 对服务器 IP 拦截），所以**每台要用的设备都得能连到一个 NeteaseCloudMusicApi 实例**。
>
> 最省事的做法：搭**一个**实例（手机本机 / 一台常开服务器 / 云），让手机和电脑的插件填**同一个地址**，而不是每台设备各搭一个。

---

## 0. 一句话记住填什么

| 你的 AstrBot 跑在哪 | `wyy_custom_url` 填什么 | 说明 |
|---------------------|--------------------------|------|
| **手机 Termux / Ubuntu(proot) 里**（同环境） | `http://127.0.0.1:3000` | 本机 127.0.0.1 可用 ✅ |
| **手机 / 电脑连远程服务器** | `http://<服务器IP>:3000` | 跨机填真实 IP |
| AstrBot 在 **Docker 容器**里 | `http://<宿主机内网IP>:3000` | 容器里填 127.0.0.1 ❌ 错（那是容器自己） |

> ⚠️ **127.0.0.1 语义坑**：AStrBot 与 NeteaseCloudMusicApi **同一环境**（手机 Termux 本机）→ `127.0.0.1:3000` 正确；
> AStrBot 在 **Docker 容器**、API 在宿主机/另一容器 → 要填宿主机真实 IP，不能填 127.0.0.1。

---

## 1. 手机（Termux / Ubuntu proot）

适合：AstrBot 装在手机 Termux 或 Termux + proot Ubuntu 里，不需要别的设备访问。

> 你的环境是 **AstrBot 装在 Ubuntu（proot）里、不在 Docker**：`127.0.0.1` 完全可用（Ubuntu 与 netease-api 同处一个环境），脚本会自动识别 Ubuntu 用 `apt` 装 Node.js。

### 方法一：一键脚本（推荐）
把同目录 `setup_termux.sh` 传到手机，在 **Ubuntu 终端**里执行：
```bash
bash setup_termux.sh
```
脚本自动：装 Node.js（apt）→ 后台启动 API（端口 3000）→ 生成 `start_api.sh` 便于重启。看到 `server running @ http://localhost:3000` 即成功。

### 方法二：手动两行（Ubuntu 内）
```bash
apt-get update && apt-get install -y nodejs npm
npx NeteaseCloudMusicApi@latest
```

### ⚠️ 手机本机的致命坑：后台被杀
Termux 切后台，系统几秒~几分钟就会杀进程，API 一停插件就解析失败。三选一：
1. 把 Termux 加入系统「电池优化白名单 / 省电例外」
2. 在 **Termux 原生终端**（不是 Ubuntu 里）执行 `termux-wake-lock`，并保持终端在前台
3. 改用下方「服务器」方案把服务放常开机器（最稳）

> 💡 AstrBot 占着终端输不了命令？开第二个 Termux 会话 / 用 AstrBot Web 面板 / tmux 后台化，详见 [`手机与多设备搭建指南.md`](手机与多设备搭建指南.md) 第 7 节。

---

## 2. 服务器（Linux 常开，多设备共用，最推荐）

搭一次，手机 + 电脑 + 任意设备填同一个地址，常开不掉线。

### 方式 A：Docker Compose（推荐，自带镜像构建）
把本目录（`tools/netease-api/`）整目录传到服务器 `/www/netease-api/`，执行：
```bash
cd /www/netease-api
docker compose up -d --build
```
看到 `server running @ http://0.0.0.0:3000` 即成功。所有设备填 `http://<服务器IP>:3000`。

### 方式 B：无 Docker，直接 npx 常驻
```bash
# 安装 Node.js（已装可跳过）
curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt-get install -y nodejs

# 后台启动（生成重启脚本）
mkdir -p /opt/netease-api && cd /opt/netease-api
cat > start_api.sh <<'EOF'
#!/bin/bash
exec npx NeteaseCloudMusicApi@latest
EOF
chmod +x start_api.sh
nohup ./start_api.sh > netease_api.log 2>&1 &
echo "PID=$!"
```
> 想开机自启可加 systemd 服务或 `crontab @reboot`。

### 防火墙（建议仅对内网开放）
```bash
sudo ufw allow from 192.168.0.0/16 to any port 3000   # 仅内网
sudo ufw deny 3000                                      # 拒绝公网（按需）
```

---

## 3. 电脑（macOS / Linux 桌面）

本地调试或临时用，最快：

### 方式 A：一行 npx
```bash
npx NeteaseCloudMusicApi@latest
# 然后浏览器访问 http://127.0.0.1:3000 看到 server running 即成功
```
插件填 `http://127.0.0.1:3000`（电脑本机 AstrBot 同机时）。

### 方式 B：Docker（与服务器一致）
```bash
docker run -d -p 3000:3000 --name netease_api binaryify/netease_cloud_music_api
```

### 方式 C：Vercel 一键部署（云，多设备共用）
1. Fork https://github.com/Binaryify/NeteaseCloudMusicApi
2. 在 https://vercel.com New Project → Import → Deploy
3. 拿到 `https://xxx.vercel.app` 填进 `wyy_custom_url`

> ⚠️ Vercel 部分接口需要 `realIP` 参数，而插件调用时未带，可能导致解析失败；建议绑定备案域名或直接用服务器方案。国内访问也偏慢。

---

## 4. 配置到插件（每台设备都填）

AstrBot 后台 → 插件配置 → `muliyresources`：

| 配置项 | 填什么 | 说明 |
|--------|--------|------|
| `wyy_custom_url` | 实例地址（见上表） | **必填**，否则功能不工作 |
| `wyy_cookie` | 黑胶会员 `MUSIC_U` Cookie（可选） | 填了才能解析 VIP/付费歌曲，否则这类歌返回 `null` |
| `wyy_backend` | `custom` | 固定值，使用自建后端 |
| `wyy_music_type` | `standard` / `exhigh` / `lossless`（可选） | 音质，VIP 音质需配合 `wyy_cookie` |

---

## 5. 跨平台自检脚本（手机 / 服务器 / 电脑都能跑）

同目录 `test_netease_api.sh` —— **同一份脚本三端通用**，自动探测 `curl / wget / python3`，
逐个验证：服务在线 → 歌曲直链 → 歌曲详情（曾经报 `Extra data` 的接口）→ 搜索。
测试前请先确保 NeteaseCloudMusicApi 已启动。

### 用法
```bash
# 本机（手机 Termux / 电脑 Mac / Linux 桌面，默认 127.0.0.1:3000）
bash test_netease_api.sh

# 测服务器实例（手机 / 电脑连远程）
bash test_netease_api.sh http://192.168.1.100:3000

# 带会员 Cookie 测（验证 VIP 歌曲）
bash test_netease_api.sh --url http://x.x.x.x:3000 --cookie "MUSIC_U=你的Cookie值" --id 28921655
```

### 各平台示例
```bash
# 手机 Ubuntu 里（已启动 netease-api 本机）
bash tools/netease-api/test_netease_api.sh

# 服务器上（实例就在本机）
bash tools/netease-api/test_netease_api.sh

# 电脑 Mac 终端（本机 npx 起的）
bash tools/netease-api/test_netease_api.sh
```

### 输出示例（全部通过）
```
==================================================
 NeteaseCloudMusicApi 自检  →  http://127.0.0.1:3000
 客户端: curl
==================================================
✅ 服务在线 (HTTP 200)
✅ /song/url 直链可用
✅ 歌曲详情 /song/detail  (HTTP 200，命中 '"code"')
✅ 搜索 /search  (HTTP 200，命中 '"result"')
--------------------------------------------------
 结果：通过 4 / 失败 0
--------------------------------------------------
🎉 全部通过，可把 wyy_custom_url = http://127.0.0.1:3000 填进插件
```

### 脚本全文
```bash
#!/usr/bin/env bash
# =============================================================================
# test_netease_api.sh — 跨平台 NeteaseCloudMusicApi 自检脚本
#
# 同一份脚本，三端通用：
#   - 手机：Termux 原生 / Termux + proot Ubuntu（AstrBot 装在 Ubuntu 里）
#   - 服务器：Linux（宝塔 / 云服务器 / VPS）
#   - 电脑：macOS / Linux 桌面
#
# 作用：一键检测你的 NeteaseCloudMusicApi 实例是否在线、能否正常返回
#       歌曲直链 / 详情 / 搜索结果（含曾经报 Extra data 的 /song/detail）。
#
# 用法：
#   bash test_netease_api.sh                                    # 测本机 127.0.0.1:3000
#   bash test_netease_api.sh http://192.168.1.100:3000          # 测服务器内网 IP
#   bash test_netease_api.sh --url http://x.x.x.x:3000 \
#        --cookie "MUSIC_U=xxxx" --id 28921655 --kw 晴天
#
# 退出码：全部通过 = 0，有失败 = 1
# =============================================================================

set -u

# ---------- 参数解析 ----------
BASE="http://127.0.0.1:3000"
COOKIE=""
SONG_ID="28921655"
KEYWORD="晴天"

while [ $# -gt 0 ]; do
  case "$1" in
    --url)    BASE="$2"; shift 2;;
    --cookie) COOKIE="$2"; shift 2;;
    --id)     SONG_ID="$2"; shift 2;;
    --kw)     KEYWORD="$2"; shift 2;;
    http*)    BASE="$1"; shift;;
    *)        shift;;
  esac
done
BASE="${BASE%/}"

# ---------- 探测可用的 HTTP 客户端 ----------
if command -v curl >/dev/null 2>&1; then
  CLIENT="curl"
elif command -v wget >/dev/null 2>&1; then
  CLIENT="wget"
elif command -v python3 >/dev/null 2>&1; then
  CLIENT="python3"
else
  echo "❌ 未找到 curl / wget / python3，无法测试"; exit 1
fi

# ---------- http_get <url>  → 输出 "HTTP_CODE|BODY" ----------
http_get() {
  local url="$1"
  if [ "$CLIENT" = "curl" ]; then
    local -a args=()
    [ -n "$COOKIE" ] && args+=(-H "Cookie: $COOKIE")
    curl -s --max-time 20 -o /tmp/ncm_test_body -w '%{http_code}' "${args[@]}" "$url" > /tmp/ncm_test_code 2>/dev/null
    local code; code=$(cat /tmp/ncm_test_code 2>/dev/null)
    [ -z "$code" ] && code=000
    echo "$code|$(cat /tmp/ncm_test_body 2>/dev/null)"
  elif [ "$CLIENT" = "wget" ]; then
    local body
    body=$(wget -qO- --timeout=20 "$url" 2>/dev/null)
    [ $? -ne 0 ] && { echo "000|"; return; }
    echo "200|$body"
  else
    NCM_COOKIE="$COOKIE" python3 - "$url" <<'PY'
import sys, os, urllib.request
url = sys.argv[1]
cookie = os.environ.get("NCM_COOKIE", "")
req = urllib.request.Request(url)
if cookie:
    req.add_header("Cookie", cookie)
try:
    r = urllib.request.urlopen(req, timeout=20)
    print("200|" + r.read().decode("utf-8", "replace"))
except Exception as e:
    print("000|ERR:" + str(e))
PY
  fi
}

# ---------- 断言：HTTP 200 且响应包含期望字符串 ----------
PASS=0; FAIL=0
check() {
  local name="$1" resp="$2" expect="$3"
  local code="${resp%%|*}" body="${resp#*|}"
  if [ "$code" = "200" ] && printf '%s' "$body" | grep -q -- "$expect"; then
    echo "✅ $name  (HTTP $code，命中 '$expect')"
    PASS=$((PASS+1))
  else
    echo "❌ $name  (HTTP $code)"
    [ -n "$body" ] && echo "   ↳ 响应片段: ${body:0:160}"
    FAIL=$((FAIL+1))
  fi
}

echo "=================================================="
echo " NeteaseCloudMusicApi 自检  →  $BASE"
echo " 客户端: $CLIENT"
echo "=================================================="

# 1) 健康检查（根路径返回 200 即说明服务已起）
resp=$(http_get "$BASE/")
if [ "${resp%%|*}" = "200" ]; then
  echo "✅ 服务在线 (HTTP 200)"
  PASS=$((PASS+1))
else
  echo "❌ 服务未响应 (HTTP ${resp%%|*}) —— 请确认已启动且地址正确"
  FAIL=$((FAIL+1))
fi

# 2) 歌曲直链（带音质）
resp=$(http_get "$BASE/song/url?id=$SONG_ID&level=standard")
body="${resp#*|}"
if printf '%s' "$body" | grep -q '"url":null'; then
  echo "⚠️  /song/url 返回 200 但 url 为 null（该曲可能 VIP/版权限制，或需 MUSIC_U Cookie）"
  FAIL=$((FAIL+1))
elif printf '%s' "$body" | grep -q '"url"'; then
  echo "✅ /song/url 直链可用"
  PASS=$((PASS+1))
else
  echo "❌ /song/url 未返回 url 字段"
  FAIL=$((FAIL+1))
fi

# 3) 歌曲详情（曾经在服务端报 Extra data 的接口，重点验证）
resp=$(http_get "$BASE/song/detail?id=$SONG_ID")
check "歌曲详情 /song/detail" "$resp" '"songs"\|"code"'

# 4) 搜索
resp=$(http_get "$BASE/search?keywords=$KEYWORD")
check "搜索 /search" "$resp" '"result"\|"songs"'

echo "--------------------------------------------------"
echo " 结果：通过 $PASS / 失败 $FAIL"
echo "--------------------------------------------------"
if [ "$FAIL" -eq 0 ]; then
  echo "🎉 全部通过，可把 wyy_custom_url = $BASE 填进插件"
  exit 0
fi
echo "⚠️  有失败项，请检查：服务是否启动 / 地址是否正确 / 防火墙是否放行 3000 端口"
exit 1
```

---

## 6. 常见坑速查

- **解析失败 / 连不上** → 99% 是 `wyy_custom_url` 填错。Docker 容器里别填 `127.0.0.1`；跨机填真实 IP。
- **返回 200 但 url 为 null** → 该曲是 VIP/版权限制，换普通歌；或配置 `wyy_cookie`（MUSIC_U）。
- **`Extra data` / JSON 解析报错** → 旧版 netease-api 会把多个 JSON 拼在响应体，插件已做容错解析（v1.10.x）。重启用 `test_netease_api.sh` 验证 `/song/detail` 是否正常。
- **手机本机跑了但过会儿失效** → Termux 被后台杀，看第 1 节保活三招。
- **ffmpeg 缺失** → 插件退化为发完整音频（仍可用）；要截片段需在 AstrBot 环境装 ffmpeg。
- **语音发送超时（WebSocket API call timeout）** → 歌曲太长（如 600s）体积过大，把「最大发送歌曲时长」调小，或保持默认 120s 更稳。

---

## 附：docker-compose.yml
```yaml
# 自建网易云解析后端（NeteaseCloudMusicApi）
# 用途：插件 astrbot_plugin_muliyresources 网易云语音名片功能的唯一解析后端
#       （wyapi / qzxdp 公共站已于 v1.9.3 移除，因其对服务器 IP 有 WAF 拦截）。
#
# 使用步骤：
#   1) 宿主机安装 Docker 与 Docker Compose（docker --version 确认）
#   2) 在本目录执行：  docker compose up -d --build
#   3) 确认服务在线：  curl http://127.0.0.1:3000/song/url?id=28921655
#   4) 插件配置（AStrBot Web 后台 → 插件配置 → muliyresources）：
#        wyy_custom_url = http://<宿主机内网IP>:3000
#                        ⚠️ 注意：AStrBot 自己也跑在 Docker 里时，
#                           这里【不能】填 localhost / 127.0.0.1（那是 AStrBot 容器自己），
#                           必须填宿主机的真实内网 IP（如 http://192.168.1.100:3000），
#                           或两个容器加入同一 docker 网络后用服务名 http://netease-api:3000。
#
# 注意：
#   - 若 AStrBot 也跑在 Docker 里且与本服务在同一 compose 网络，可用服务名： http://netease-api:3000
#   - 默认端口 3000，如与已有服务冲突，改下方 ports 的宿主机端口（左侧）即可，如 "3001:3000"
#   - 部分 VIP 单曲 /song/url 可能返回 null（网易云限制），属正常，换普通歌曲即可
#   - 仅对内网开放 3000 端口即可，无需暴露公网

services:
  netease-api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: netease-api
    ports:
      - "3000:3000"
    restart: unless-stopped
    environment:
      - NODE_ENV=production
      # 可选：填入你自己的网易云登录 Cookie（MUSIC_U=...）以提升可用歌曲范围
      # - MUSIC_U=
```

## 附：Dockerfile
```dockerfile
# 自建 NeteaseCloudMusicApi 镜像（从官方源码构建）
FROM node:18-alpine

WORKDIR /app

# 加速 npm 依赖安装（国内服务器推荐；如不需要可删掉此行）
RUN npm config set registry https://registry.npmmirror.com

# 克隆官方仓库（--depth 1 仅拉最新提交，加快构建）
# 若 GitHub 不可达，可改用 Gitee 镜像，把下一行替换为：
#   && git clone --depth 1 https://gitee.com/mirrors/NeteaseCloudMusicApi.git . \
RUN apk add --no-cache git \
    && git clone --depth 1 https://github.com/Binaryify/NeteaseCloudMusicApi.git . \
    && npm install --omit=dev

EXPOSE 3000

# 官方启动脚本，默认监听 0.0.0.0:3000
CMD ["npm", "start"]
```
