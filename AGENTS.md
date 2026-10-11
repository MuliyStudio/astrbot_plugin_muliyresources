# AGENTS.md

## 仓库约定

- **每次更新后必须提交并推送到 GitHub**：改动完成后运行 `git add` → `git commit`（按仓库风格写中文 commit，如 `fix(1.13.1): ...`）→ `git push origin main`。
- 发布/版本变更时同步更新：`metadata.yaml` 的 `version`、`main.py` 里 `@register(...)` 的版本号、`CHANGELOG.md` 顶部新增条目、README 相关说明。
- 配置项改动需同步 `_conf_schema.json` 与 `main.py` 的 `_CONF_GROUPS`（`_KEY_TO_GROUP` 自动生成）。

## 环境注意（本机 Windows）

- **网络**：直连 `github.com` 会超时，必须走本地代理 `http://127.0.0.1:7897`（git 全局已配置 `http.proxy`/`https.proxy`）。
- **认证**：用 `gh`（GitHub CLI）。若 `gh` 认证失败或 token 失效，先带代理重新登录：
  ```powershell
  $env:HTTPS_PROXY="http://127.0.0.1:7897"; $env:HTTP_PROXY="http://127.0.0.1:7897"
  gh auth login -h github.com
  gh auth setup-git
  ```
  remote 不要再内嵌 PAT（`git remote set-url origin https://github.com/MuliyStudio/astrbot_plugin_muliyresources.git`）。

## 代码校验

- 语法检查：`python -m py_compile main.py core/*.py`
- 配置 JSON 校验：`python -c "import json; json.load(open('_conf_schema.json', encoding='utf-8'))"`
