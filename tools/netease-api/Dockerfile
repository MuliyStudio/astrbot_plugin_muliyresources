# 自建 NeteaseCloudMusicApi 镜像
# 直接从 npm 安装官方发布的 NeteaseCloudMusicApi 包（内含完整服务），
# 不依赖 git / github / gitee，受限网络下最稳（只要 npm 源可达即可）。
FROM node:18-alpine

WORKDIR /app

# 使用 npmmirror 国内源（受限网络必备；服务器能直连 npm 官方源可删掉此行）
RUN npm config set registry https://registry.npmmirror.com

# 全局安装 NeteaseCloudMusicApi 包，其 bin 命令即启动服务（app.js，默认 0.0.0.0:3000）
RUN npm install -g NeteaseCloudMusicApi

EXPOSE 3000

# 启动服务（bin 命令，等价于 node app.js）
CMD ["NeteaseCloudMusicApi"]
