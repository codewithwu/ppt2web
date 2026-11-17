"""音频/视频素材解析（``p:audio`` / ``a:audioFile``）。

**目前只解析、不播放。**

但这一步不能省：源文件里的背景音是靠两处信息表达的 ——
``<a:audioFile r:link="..."/>``（挂在哪个形状上、文件在哪）和
``<p:audio><p:cMediaNode vol="..." repeatCount="indefinite">``（音量、是否循环）。
两处都不读，这个媒体就彻底消失了，而且没有任何地方会提醒：
``verify`` 只校验"产物里已有的媒体"，源里多出来的媒体对它是隐形的。

解析出来之后，报告里会有一节"音频"，``verify`` 会把"源里有、产物里没有"
的媒体判成硬失败 —— 显式化比静默丢失好。
"""

from __future__ import annotations

import hashlib
from typing import Optional

from ..model import AudioClip
from ..ooxml import find, iter_descendants, qn
from ..package import Package

#: 素材挂在形状上的位置（图片图元 / 形状 / 媒体框）
_NVPR_PATHS = (
    "p:nvPicPr/p:nvPr",
    "p:nvSpPr/p:nvPr",
    "p:nvMediaPr/p:nvPr",
)


def parse_audio(
    package: Package,
    partname: str,
    slide_el,
) -> list[AudioClip]:
    """解析一页里的音频/视频素材。"""
    clips: list[AudioClip] = []

    # 1. 素材本体：挂在形状上的 a:audioFile / a:videoFile
    for el in slide_el.iter():
        tag = el.tag.split("}")[-1]
        if tag not in ("audioFile", "videoFile", "mediaFile"):
            continue
        r_id = el.get(qn("r:link")) or el.get(qn("r:embed"))
        if not r_id:
            continue
        target = package.rel_target_for(partname, r_id)
        if not target:
            continue
        try:
            blob = package.read(target)
        except KeyError:
            continue
        ext = package.extension(target)
        clip = AudioClip(
            part_name=target,
            ext=ext,
            blob=blob,
            sha256=hashlib.sha256(blob).hexdigest(),
            kind="video" if tag == "videoFile" else "audio",
        )
        clips.append(clip)

    # 2. 播放设置：音量、循环、挂在哪个形状上
    #    p:audio 藏在 p:timing 的时间轴树深处（不是 p:timing 的直接子节点）
    timing = find(slide_el, "p:timing")
    for audio_el in iter_descendants(timing, "p:audio") if timing is not None else []:
        media_node = find(audio_el, "p:cMediaNode")
        if media_node is None:
            continue
        volume = media_node.get("vol")
        vol = int(volume) if volume and volume.isdigit() else 100000
        c_tn = find(media_node, "p:cTn")
        loop = bool(c_tn is not None and c_tn.get("repeatCount") == "indefinite")
        target_el = find(media_node, "p:tgtEl/p:spTgt")
        target_id = target_el.get("spid") if target_el is not None else ""
        if not clips:
            # 有播放设置但找不到素材文件（关系缺失）—— 记一条空的
            clips.append(AudioClip(volume=vol, loop=loop, target_id=target_id))
            continue
        for clip in clips:
            clip.volume = vol
            clip.loop = loop
            clip.target_id = target_id
    return clips
