#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
# 手机一键启动 NeteaseCloudMusicApi（供 AstrBot 插件「网易云语音名片」使用）
#
# 适用环境：
#   - 原生 Termux
#   - Termux + proot-distro Ubuntu（AstrBot 装在 Ubuntu 里的情况，自动识别）
#
# 用法（在手机终端里）：
#   bash setup_termux.sh
#
# 作用：
#   1) 安装 Node.js（Ubuntu 用 apt，Termux 用 pkg，自动判断）
#   2) 尽量保活（原生 Termux 调 termux-wake-lock；Ubuntu 内则给手动提示）
#   3) 后台启动 NeteaseCloudMusicApi（默认端口 3000），并生成 start_api.sh 便于重启
#
# 启动成功后，去 AstrBot 后台 → 插件配置 → muliyresources 填：
#   wyy_custom_url = http://127.0.0.1:3000
#
# 注意：
#   - 首次运行 npx 会联网下载包，耗时几十秒~几分钟，请耐心等
#   - 手机上 AstrBot 与 netease-api 同处一个 Ubuntu 环境，127.0.0.1 直接可用
#     （无需像 Docker 那样换宿主机 IP）
#   - proot Ubuntu 内没有 termux-wake-lock，请在【Termux 原生终端】先执行
#     termux-wake-lock，再把 Termux 加入系统省电白名单，防止后台被杀
# =============================================================================

set -e

echo "==> [1/3] 安装 Node.js ..."
if command -v pkg >/dev/null 2>&1; then
  echo "    检测到 Termux 环境，使用 pkg"
  pkg update -y && pkg install nodejs -y
elif command -v apt-get >/dev/null 2>&1; then
  echo "    检测到 Ubuntu/Debian 环境，使用 apt"
  (sudo apt-get update -y || apt-get update -y)
  (sudo apt-get install -y nodejs npm || apt-get install -y nodejs npm)
else
  echo "    未找到 pkg / apt-get，请手动安装 Node.js (含 npm) 后重试"
  exit 1
fi

# 确认 npx 可用
if ! command -v npx >/dev/null 2>&1; then
  echo "    npx 未找到，尝试安装 npm ..."
  (sudo apt-get install -y npm || apt-get install -y npm || pkg install nodejs -y)
fi

echo "==> [2/3] 保活处理 ..."
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock 2>/dev/null && echo "    (已锁定唤醒，请保持 Termux 在前台)"
else
  echo "    (当前在 Ubuntu 内，termux-wake-lock 不可用)"
  echo "    请先在【Termux 原生终端】执行: termux-wake-lock"
  echo "    再把 Termux 加入系统电池优化白名单，防止后台被杀"
fi

echo "==> [3/3] 启动 NeteaseCloudMusicApi (后台, 端口 3000) ..."
cd "$(dirname "$0")"

# 生成独立启动脚本，方便以后重启
cat > start_api.sh <<'EOF'
#!/bin/bash
cd "$(dirname "$0")"
exec npx NeteaseCloudMusicApi@latest
EOF
chmod +x start_api.sh

nohup ./start_api.sh > netease_api.log 2>&1 &
API_PID=$!
echo "    已后台启动, PID=$API_PID"
echo "    日志文件: netease_api.log"
echo "    停止服务: kill $API_PID"
sleep 5
echo "--- 启动日志 (前 15 行) ---"
tail -n 15 netease_api.log 2>/dev/null || echo "    (日志暂未生成，稍后查看 netease_api.log)"
echo ""
echo "=========================================================="
echo "  配置插件：wyy_custom_url = http://127.0.0.1:3000"
echo "  (手机 AstrBot 在 Ubuntu 内, 与 API 同环境, 127.0.0.1 可用)"
echo "  看到 'server running @ http://localhost:3000' 即成功"
echo "=========================================================="
