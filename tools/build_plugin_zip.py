# -*- coding: utf-8 -*-
"""把插件打成可直接上传/安装的 zip（本地测试用）。

用法：python tools/build_plugin_zip.py
产物：dist/astrbot_plugin_muliyresources_v<版本>_test.zip
zip 内顶层目录为 astrbot_plugin_muliyresources/（AstrBot 要求）。
"""
import os
import re
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = "astrbot_plugin_muliyresources"
DIST = os.path.join(ROOT, "dist")

# 运行必需 + 文档；开发脚本/预览图/缓存一律不进包
INCLUDE_FILES = {
    "main.py", "metadata.yaml", "requirements.txt", "_conf_schema.json",
    "README.md", "LICENSE", "CHANGELOG.md", "SO-NOVEL部署指南.md",
    "SourceHanSansCN-Heavy.otf", "logo.png",
}
INCLUDE_DIRS = ("core", "assets")
EXCLUDE_DIRS = {"__pycache__", "preview", "screenshots", "badges", "tools",
                "qr_debug_logs", ".git", ".github", "dist"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".log"}
EXCLUDE_NAMES = {"checkin_card_preview.html", "checkin_card_preview.png",
                 "index.html", ".gitignore", ".DS_Store"}
# 只在 README / 文档里用（且走 jsDelivr 绝对地址），不进插件包
EXCLUDE_REL = {"assets/logo.png", "assets/qq_group_qrcode.jpg"}


def version() -> str:
    try:
        with open(os.path.join(ROOT, "metadata.yaml"), encoding="utf-8") as f:
            m = re.search(r'^version:\s*"?([\d.]+)"?', f.read(), re.M)
        return m.group(1) if m else "0.0.0"
    except Exception:
        return "0.0.0"


def iter_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_dir = os.path.relpath(dirpath, ROOT).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        # 跳过黑名单目录（含任意层级的 __pycache__）
        dirnames[:] = [d for d in dirnames
                       if d not in EXCLUDE_DIRS and d not in EXCLUDE_DIRS]
        if rel_dir and any(part in EXCLUDE_DIRS for part in rel_dir.split("/")):
            continue
        for fn in filenames:
            rel = f"{rel_dir}/{fn}" if rel_dir else fn
            if fn in EXCLUDE_NAMES or rel in EXCLUDE_REL:
                continue
            if os.path.splitext(fn)[1].lower() in EXCLUDE_SUFFIX:
                continue
            if rel.split("/")[0] in EXCLUDE_DIRS:
                continue
            if rel_dir == "" and rel not in INCLUDE_FILES:
                continue
            if rel_dir and rel.split("/")[0] not in INCLUDE_DIRS:
                continue
            yield rel, os.path.join(dirpath, fn)


def main():
    os.makedirs(DIST, exist_ok=True)
    ver = version()
    out = os.path.join(DIST, f"{PLUGIN_DIR}_v{ver}_test.zip")
    files = sorted(iter_files())
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, full in files:
            z.write(full, f"{PLUGIN_DIR}/{rel}")
    size = os.path.getsize(out)
    print(f"输出：{out}")
    print(f"版本：v{ver}｜文件 {len(files)} 个｜{size / 1024 / 1024:.2f} MB")
    tops = sorted(((os.path.getsize(f), r) for r, f in files), reverse=True)[:5]
    print("最大的几项：")
    for s, r in tops:
        print(f"  {s / 1024:8.0f} KB  {r}")
    required = {"main.py", "metadata.yaml", "core/brand.py",
                "assets/logo_mark_128.png", "SourceHanSansCN-Heavy.otf"}
    missing = required - {r for r, _ in files}
    print("缺失必需文件：", "无" if not missing else missing)


if __name__ == "__main__":
    main()
