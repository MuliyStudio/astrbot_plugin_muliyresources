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
