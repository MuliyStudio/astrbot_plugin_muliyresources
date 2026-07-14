# -*- coding: utf-8 -*-
"""
音频剪辑模块（暮黎资源聚合 v1.9.0 新增）

依赖 ffmpeg（需在运行环境 PATH 中）。
负责：探测 mp3 时长、截取「歌曲中间三分之一」片段作为语音发送。
"""

import asyncio
import logging
import os
import shutil
import subprocess

logger = logging.getLogger("astrbot_plugin_muliyresources.audioclip")


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


async def get_duration_seconds(path: str) -> float:
    """用 ffprobe 获取音频时长（秒）。失败返回 0.0。"""
    if not shutil.which("ffprobe"):
        return 0.0
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        val = out.decode().strip().splitlines()
        if val:
            return float(val[0])
    except Exception as e:
        logger.warning(f"[剪辑] 获取时长失败: {e}")
    return 0.0


def compute_middle_third_range(duration: float, max_seconds: int = 600):
    """计算「歌曲中间三分之一」剪辑区间（秒）。

    需求：把整首歌时长分成三份，发送中间那一段（QQ 语音 10 分钟内均无限制）。

    规则：
      - duration <= 0：返回 (0, 0)，由调用方回退发送完整音频
      - 否则：每段 = duration/3，取第 2 段（start=duration/3, length=duration/3）
      - max_seconds 作为安全上限（默认 600=10 分钟，对应 QQ 语音常规上限）：
        若中间段超过该上限，则从原起点截断到 max_seconds（仍落在中段附近）。
    例：240s 歌曲 → 取 80s~160s（中间三分之一）；
        2400s(40min) 歌曲 → 中间段 800s 超上限，截断为 800s~1400s（取前 600s）。
    """
    if duration <= 0:
        return 0.0, 0.0
    max_seconds = max(1, int(max_seconds))
    seg = duration / 3.0
    start = seg
    length = seg
    if length > max_seconds:
        length = float(max_seconds)
    return float(start), float(length)


async def cut_clip(src: str, dst: str, start: float, clip_seconds: float, audio_format: str = "mp3") -> str:
    """用 ffmpeg 截取音频片段，写到 dst，返回 dst 路径。

    audio_format: "mp3"（默认，QQ 语音兼容性好）或 "wav"（部分 OneBot 实现要求）。
    """
    if audio_format == "wav":
        acodec = "pcm_s16le"
        extra = ["-ar", "16000", "-ac", "1"]
    else:  # mp3
        acodec = "libmp3lame"
        extra = ["-ar", "44100", "-ac", "2", "-b:a", "128k"]
    cmd = [
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", src,
        "-t", f"{clip_seconds:.3f}", "-vn", "-acodec", acodec,
    ] + extra + [dst]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg 退出码 {proc.returncode}: {err.decode()[:300]}")
        if not os.path.exists(dst) or os.path.getsize(dst) == 0:
            raise RuntimeError("ffmpeg 未产出有效片段文件")
    except Exception as e:
        logger.error(f"[剪辑] 剪辑失败: {e}")
        raise
    return dst
