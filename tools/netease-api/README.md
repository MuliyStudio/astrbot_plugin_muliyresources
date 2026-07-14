# NeteaseCloudMusicApi 自建部署指南（AstrBot Docker 环境）

> 📱 **手机 / 多设备场景**（AstrBot 装在手机 Termux、或想多设备共用一个实例）：请看同目录 **[`手机与多设备搭建指南.md`](手机与多设备搭建指南.md)**，内含一键脚本 `setup_termux.sh`。

## 适用场景
- 插件 `astrbot_plugin_muliyresources` 的「网易云语音名片」功能（v1.9.3+ 仅支持自建后端 `custom`）
- 你的 AstrBot 运行在 Docker 容器中，数据目录示例：`/www/dk_project/dk_app/astrbot/astrbot_RLHF/data/`
- 公共解析站 `wyapi` / `qzxdp` 已被网易云 WAF 对服务器 IP 拦截，故必须自建

## 拓扑
```
[宿主机 Linux]
 ├── AstrBot 容器 (Docker)        ──http──►  http://<宿主机内网IP>:3000
 └── NeteaseCloudMusicApi 容器 (本部署, Docker)  :3000
```
**关键**：AstrBot 容器访问 NeteaseCloudMusicApi 容器，必须用【宿主机内网 IP】，不能填 `localhost`/`127.0.0.1`。

## 步骤

### 1. 准备部署目录与文件
把插件里的 `tools/netease-api/` 整目录传到服务器（例如 `/www/netease-api/`），内含：
- `docker-compose.yml`
- `Dockerfile`

若没传文件，手动在服务器创建 `/www/netease-api/` 并写入文末两份文件内容。

### 2. 启动服务
```bash
cd /www/netease-api
docker compose up -d --build
```
- 首次会克隆官方源码 + `npm install`，约需几分钟，需服务器能访问 GitHub。
- 国内依赖安装已配置 npmmirror 镜像加速；若 GitHub 也不可达，把 `Dockerfile` 里 clone 地址换成 Gitee 镜像（见注释）。
- 查看启动日志：
  ```bash
  docker compose logs -f netease-api
  ```
  看到 `server running @ http://0.0.0.0:3000` 即成功。

### 3. ⚠️ 填写 wyy_custom_url（最容易踩坑的一步）
进入 AstrBot 后台 → 插件配置 → `muliyresources`，把：
```
wyy_custom_url = http://<宿主机内网IP>:3000
```
填成**宿主机真实内网 IP**，例如 `http://192.168.1.100:3000`。

- ❌ 不要填 `http://127.0.0.1:3000` 或 `localhost:3000` —— 那指向 AstrBot 容器自己，连不到 NeteaseCloudMusicApi。
- ✅ 查宿主机内网 IP：`ip addr` / `hostname -I` 看 `eth0` 地址。
- ✅ 进阶：若两容器在同一 docker 网络，可用服务名 `http://netease-api:3000`。

### 4. 在 AstrBot 容器内验证连通性（关键自检）
在** AstrBot 容器里**执行（不是宿主机），确认它能访问到 NeteaseCloudMusicApi：
```bash
docker exec -it <astrbot容器名> sh -c \
  "curl -s 'http://<宿主机内网IP>:3000/song/url?id=28921655&level=standard'"
```
返回含 `"url":"http://..."` 即网络通。不通说明网络/防火墙问题，先排查再继续。

### 5. 宿主机侧验证
```bash
curl "http://127.0.0.1:3000/song/url?id=28921655&level=standard"
```

### 6. 用插件自测脚本（可选）
把 `tools/check_netease_api.py` 放到服务器，运行：
```bash
python3 tools/check_netease_api.py --url http://127.0.0.1:3000
```

## 防火墙（建议仅对内网开放）
```bash
# 以 ufw 为例，仅允许内网访问 3000，不从公网暴露
sudo ufw allow from 192.168.0.0/16 to any port 3000
sudo ufw deny 3000   # 默认拒绝公网（按需）
```

## 可选：登录 Cookie（MUSIC_U）
部分 VIP 单曲 `/song/url` 会返回 `null`。可把网易云网页登录 Cookie 中的 `MUSIC_U` 注入：
编辑 `docker-compose.yml` 取消注释：
```yaml
environment:
  - MUSIC_U=你的MUSIC_U值
```
然后 `docker compose up -d` 重启生效。

## 常见问题
- **AstrBot 报解析失败 / 连不上** → 99% 是 `wyy_custom_url` 填了 `localhost`。改成宿主机内网 IP，并在 AstrBot 容器内 `curl` 验证。
- **build 卡在 git clone** → 服务器无法访问 GitHub，改用 Gitee 镜像（Dockerfile 注释已说明）。
- **返回 200 但 url 为 null** → 该曲为 VIP/版权限制，换普通歌曲；或配置 `MUSIC_U`。
- **ffmpeg 缺失** → AstrBot 容器内若无 ffmpeg，插件退化为发送完整音频（仍可用）；要截取 60 秒高潮需在 AstrBot 容器内装 ffmpeg。

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
#   4) 插件配置（AstrBot Web 后台 → 插件配置 → muliyresources）：
#        wyy_custom_url = http://<宿主机内网IP>:3000
#                        ⚠️ 注意：AstrBot 自己也跑在 Docker 里时，
#                           这里【不能】填 localhost / 127.0.0.1（那是 AstrBot 容器自己），
#                           必须填宿主机的真实内网 IP（如 http://192.168.1.100:3000），
#                           或两个容器加入同一 docker 网络后用服务名 http://netease-api:3000。
#
# 注意：
#   - 若 AstrBot 也跑在 Docker 里且与本服务在同一 compose 网络，可用服务名： http://netease-api:3000
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
