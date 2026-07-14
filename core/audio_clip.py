# -*- coding: utf-8 -*-
"""
音频剪辑模块（暮黎资源聚合 v1.9.0 新增）

依赖 ffmpeg（需在运行环境 PATH 中）。
负责：探测 mp3 时长、截取「开头不超过最大时长的片段」作为语音发送。
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


def compute_clip_range(duration: float, max_seconds: int = 600):
    """计算剪辑区间（秒）：从歌曲开头发送，时长取「歌曲时长」与「上限」的较小值。

    需求：用户通过 wyy_clip_seconds 设定「最大发送歌曲时长」，实际发送语音时长 =
    min(歌曲实际时长, 上限)。不再取歌曲中间三分之一。

    规则：
      - duration <= 0：返回 (0, 0)，由调用方回退发送完整音频
      - 否则：length = min(duration, max_seconds)，start = 0（从开头发送）
    例：歌曲 200s、上限 120 → 发前 120s；
        歌曲 180s、上限 600 → 发整曲 180s（不满上限则整曲发送）。
    """
    if duration <= 0:
        return 0.0, 0.0
    max_seconds = max(1, int(max_seconds))
    length = min(float(duration), float(max_seconds))
    return 0.0, float(length)


async def cut_clip(src: str, dst: str, start: float, clip_seconds: float, audio_format: str = "mp3") -> str:
    """用 ffmpeg 截取音频片段，写到 dst，返回 dst 路径。

    audio_format: "mp3"（默认，QQ 语音兼容性好）或 "wav"（部分 OneBot 实现要求）。
    """
    if audio_format == "wav":
        acodec = "pcm_s16le"
        extra = ["-ar", "16000", "-ac", "1"]
    else:  # mp3
        # QQ 语音最终会被 OneBot(napcat) 转码为 silk 单声道 ~24kHz，
        # 因此这里直接输出「单声道 / 24kHz / 48k」：
        #   1) 体积约为原立体声 128k 的 1/4（600s ≈ 3.6MB），
        #   2) napcat 转码/上传更快，显著降低「WebSocket API call timeout」概率，
        #   3) 对 QQ 语音听感无损（反正会被降成 silk 单声道）。
        acodec = "libmp3lame"
        extra = ["-ar", "24000", "-ac", "1", "-b:a", "48k"]
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
