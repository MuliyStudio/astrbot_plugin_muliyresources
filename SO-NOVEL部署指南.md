# so-novel 部署指南（专为本插件服务）

> 本文档仅服务于 **astrbot_plugin_muliyresources（暮黎资源聚合）** 的「小说搜索与下载」功能。
> 该插件本身**不内嵌**小说下载能力，而是通过 HTTP 调用一个独立运行的 **so-novel** 服务
> （基于 Web 模式暴露 REST 接口）来完成多源聚合搜索与整本小说下载。
> 因此，要使用插件里的 `/找小说` 指令，你必须**单独部署一个 so-novel 服务**，并让插件能访问它。

---

## 一、工作原理

```
  用户(QQ/微信等)
      │  /找小说 斗破苍穹
      ▼
  AstrBot 插件 astrbot_plugin_muliyresources
      │  HTTP 调用（插件所在网络可达 so-novel 即可）
      ▼
  so-novel 服务（-Dmode=web，默认端口 7765）
      │  ├─ GET /search/aggregated   多书源聚合搜索
      │  ├─ GET /book-fetch          服务端同步抓取整本小说
      │  ├─ GET /book-download       以文件流返回小说文件
      │  └─ GET /sources(/check)     书源可用性
      ▼
  插件拉取文件字节 → 以「文件」形式直接发回会话（用户无需点击链接）
```

**关键点**：下载时由**插件侧**直接把小说文件流拉取下来再转发给用户，
因此 so-novel 服务只需对**插件所在网络**可达即可，**不需要**对用户公网开放，
用户也无需访问 so-novel 的 WebUI。

---

## 二、环境依赖

| 依赖 | 说明 |
|---|---|
| Docker（推荐） | 一条命令即可拉起官方镜像，免去手动装 Java。 |
| 或 Java 21+ | 仅当你选择「原生 tar.gz」部署方式时需要（不推荐新手）。 |
| 可被插件访问的网络 | so-novel 与 AstrBot 在同一台机器/同一内网最佳。 |
| 磁盘空间 | 下载的小说默认落在 so-novel 的 `downloads` 目录，按量占用。 |

> ⚠️ so-novel 是 **Java 项目**，不是 Python 库。插件只用 HTTP 调用它，
> 因此**不需要**在 `requirements.txt` 里增加任何小说相关依赖（已自带 `requests`）。

---

## 三、部署方式

### 方式 A：Docker 部署（强烈推荐）

官方提供 Docker 镜像 `ghcr.io/freeok/sonovel:latest`。

> ⚠️ **最重要的坑**：官方镜像**默认启动的是 TUI 交互菜单模式**，不是 Web 模式！
> 在 Docker 里没有 stdin，TUI 一读取输入就会抛 `NoSuchElementException` 崩溃退出，
> 导致 7765 端口从不监听、插件全部请求 `Connection refused`。
> **必须显式开启 Web 模式**：通过 JVM 参数 `-Dmode=web`。

**部署命令（已带 Web 模式，可直接复制）：**

```bash
docker rm -f sonovel

docker run -d \
  --name sonovel \
  --restart unless-stopped \
  -p 7765:7765 \
  -e TZ=Asia/Shanghai \
  -e JAVA_TOOL_OPTIONS="-Dmode=web" \
  -v /www/wwwroot/sonovel/downloads:/sonovel/downloads \
  ghcr.io/freeok/sonovel:latest
```

参数说明：
- `-e JAVA_TOOL_OPTIONS="-Dmode=web"`：**开启 Web 模式的关键**，JVM 会自动读取。
- `-v .../downloads:/sonovel/downloads`：把下载文件持久化到宿主机，重启不丢。
- `-p 7765:7765`：暴露 Web 端口。

**如 ghcr.io 拉不动**（国内常见），用镜像加速源后改 tag：

```bash
docker pull ghcr.nju.edu.cn/freeok/sonovel:latest
docker tag ghcr.nju.edu.cn/freeok/sonovel:latest ghcr.io/freeok/sonovel:latest
# 再执行上面的 docker run
```

**备选 entrypoint（若上面的 JAVA_TOOL_OPTIONS 不生效时兜底）：**

```bash
docker run -d \
  --name sonovel --restart unless-stopped -p 7765:7765 \
  -e TZ=Asia/Shanghai \
  -v /www/wwwroot/sonovel/downloads:/sonovel/downloads \
  --entrypoint sh ghcr.io/freeok/sonovel:latest \
  -c "cd /sonovel && java -Dmode=web -jar $(ls *.jar | head -1)"
```

### 方式 B：原生 tar.gz 部署（需自备 Java 21+）

> v1.11.0 起官方 release **只发布原生 tar.gz（不再带可直接 `java -jar` 的 fat jar）**，
> 这种方式需要你自行准备 Java 运行环境，适合无法用 Docker 的环境。

```bash
# 1) 安装 Java 21（示例：Debian/Ubuntu）
sudo apt update && sudo apt install -y openjdk-21-jdk

# 2) 下载并解压官方 tar.gz（请到 so-novel 仓库 Release 页取最新链接）
wget https://github.com/freeok/so-novel/releases/latest/download/so-novel-*.tar.gz
tar -xzf so-novel-*.tar.gz -C /opt/sonovel --strip-components=1
cd /opt/sonovel

# 3) 以 Web 模式启动（关键仍是 -Dmode=web）
java -Dmode=web -jar app.jar
# 或后台运行：nohup java -Dmode=web -jar app.jar > sonovel.log 2>&1 &
```

---

## 四、可选配置（config.ini）

so-novel 默认无需配置文件即可工作。如需自定义，编辑挂载目录里的 `config.ini`
（Docker 方式在宿主机 `/www/wwwroot/sonovel/` 下创建，或在容器内 `/sonovel/config.ini`）。
常见项（按官方文档填写，例如下载并发、书源路径等）。**对本插件而言通常留默认即可。**

---

## 五、与插件对接

### 1. 确定插件应填的地址 `sonovel_base_url`

插件需要能访问到 so-novel 的 7765 端口。常见三种情况：

| 部署位置 | 插件 `sonovel_base_url` 填法 | 说明 |
|---|---|---|
| 同机直连（插件与 so-novel 同进程/同机） | `http://127.0.0.1:7765` | 最省事 |
| 同宿主机、so-novel 跑在 Docker | `http://172.17.0.1:7765` | **Docker 网关=宿主机**，推荐 |
| 跨机 / 跨容器网络 | `http://<内网IP>:7765` | 双方互通的内网地址 |

> ⚠️ **切勿填写 so-novel 宿主机的公网 IP**（如 `117.x.x.x`）——
> 多是 NAT 回环，AstrBot 容器访问会不通。优先用 `172.17.0.1`（Docker 网关）。

### 2. 在 AstrBot 插件设置中填写（WebUI → 插件 → 暮黎资源聚合 → novel 分组）

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `sonovel_base_url` | so-novel Web 服务地址（见上表） | `http://127.0.0.1:7765` |
| `sonovel_token` | 访问令牌。**官方 servlet 不做鉴权，留空即可**；仅当你在 so-novel 前套了带鉴权的封装层（如 so-novel-web）时才填其 Bearer Token | 空 |
| `sonovel_search_limit` | 每个书源返回的最大搜索结果数 | `20` |
| `sonovel_format` | 默认下载格式（**可多选**：txt / epub / html / pdf） | `["txt"]` |
| `sonovel_timeout` | 搜索/接口网络超时（秒） | `30` |
| `sonovel_download_timeout` | 整本下载等待上限（秒），大书可能需数分钟 | `600` |

> 修改后**重载插件**使其生效。

---

## 六、验证流程

### 第 1 步：确认 so-novel 自身正常

```bash
# 看日志，应出现：
#   Picked up JAVA_TOOL_OPTIONS: -Dmode=web
#   且不再打印 q/w/e 的交互菜单
docker logs -f sonovel
```

```bash
# 直接探测接口（在能访问 7765 的机器上）：
curl -s http://127.0.0.1:7765/sources/check
# 应返回 JSON 数组（书源列表及 available 状态）
```

### 第 2 步：从 AstrBot 容器侧验证互通（同宿主机场景）

若 so-novel 在 Docker、AstrBot 也在 Docker，用网关地址互测：

```bash
docker exec <astrbot容器名> curl -s http://172.17.0.1:7765/sources/check
# 返回 JSON 即说明插件→so-novel 网络互通
```

### 第 3 步：用插件指令验证

在聊天里发送：

```
/novel_status
```

插件会返回：
- ✅ so-novel 服务可访问 + 当前地址
- 📋 默认格式 / 搜索上限 / 下载超时
- 📚 已激活书源列表（✅/❌/➖ 标记可用性）

若显示「❌ so-novel 不可达」，请回头检查 `sonovel_base_url` 是否填错、
so-novel 是否真的以 Web 模式启动（日志是否有 `-Dmode=web`）。

### 第 4 步：端到端实测下载

```
/找小说 斗破苍穹
# 回复数字选择一本 → 回复「下载/确认」（或指定格式如 epub）
# 插件会先把小说文件拉取下来，再以「文件」形式直接发回会话
```

若收到文件即部署成功；若仍失败，看 AstrBot 日志中 `[暮黎资源]` 相关报错，
多半是书源失效（换一本/换格式）或下载超时（调大 `sonovel_download_timeout`）。

---

## 七、常见问题

**Q：上传插件后小说功能报 `so-novel 不可达`？**
A：九成是 so-novel 没以 Web 模式启动。确认 `docker logs sonovel` 里有没有
`Picked up JAVA_TOOL_OPTIONS: -Dmode=web`，没有就重跑带该参数的部署命令。
另确认插件 `sonovel_base_url` 用的是 `172.17.0.1`（同宿主机）而非公网 IP。

**Q：搜索得到书，但下载一直转圈/超时？**
A：大书整本抓取耗时久，调大 `sonovel_download_timeout`（如 1200）。
也可能是该书源较慢/失效，换一本或换格式（txt 最稳）。

**Q：下载返回的是 WebUI 预览页而不是文件？**
A：本插件已改为**插件侧直接拉取文件流并以文件形式发送**，不再依赖浏览器点击链接，
因此不会出现「点了链接却打开预览页」的问题。若你自行改造，请持续使用
`/book-download` 接口拿文件字节，而非打开 WebUI。

**Q：要不要给 so-novel 设 Token？**
A：官方 servlet 不鉴权，留空即可。只有套了带鉴权的封装层才需要填 `sonovel_token`。

**Q：书源太少/想增删书源？**
A：书源由 so-novel 自身管理（其 `config.ini` / 书源目录）。插件只负责调用，
不管理书源。增删书源请参考 so-novel 官方文档。

---

## 八、与本插件相关的文件

| 文件 | 作用 |
|---|---|
| `core/novel.py` | so-novel HTTP 客户端（搜索 / 抓取 / 文件流下载 / 书源检查） |
| `main.py` 的 `/找小说`、`/novel_status` 指令 | 搜索下载入口与状态自检 |
| `_conf_schema.json` 的 `novel` 分组 | 上述 6 个配置项定义 |

> 本指南随插件功能更新而更新；如 so-novel 官方接口有变动，以 so-novel 官方文档为准。
