"""动画时间轴解析：把 p:timing 的行为树翻译成可执行的时间轴。

PowerPoint 已经把动画写成了精确的行为描述（attrName + tavLst 关键帧），
所以这里不做"预设近似"，而是照着行为树翻译成 WAAPI 关键帧。
presetID 只用来做语义命名和覆盖报告的判定。
"""

from __future__ import annotations

from typing import Any, Optional

from ..model import AnimationGroup, Behavior, Timeline
from .xmlutil import find, findall

# 行为节点的标签 → 模型类型
_BEHAVIOR_TAGS = {
    "set": "set",
    "anim": "anim",
    "animRot": "animRot",
    "animScale": "animScale",
    "animClr": "animClr",
    "animMotion": "animMotion",
    "animEffect": "animEffect",
    "cmd": "cmd",
}

_EFFECT_NODE_TYPES = {
    "clickEffect",
    "withEffect",
    "afterEffect",
    "withGroup",
    "afterGroup",
    "clickPar",
    "interactiveSeq",
}

# presetID → 语义名（进入/退出/强调 三类），用于覆盖报告
_PRESET_NAMES: dict[tuple[str, int], str] = {}


def parse_timing(
    slide_el,
    slide_width_emu: int = 0,
    slide_height_emu: int = 0,
) -> Timeline:
    """解析幻灯片的 p:timing。"""
    timeline = Timeline()
    timing = find(slide_el, "p:timing")
    if timing is None:
        return timeline
    timeline.has_timing = True

    tn_lst = find(timing, "p:tnLst")
    if tn_lst is None:
        return timeline

    # 结构：tnLst > par(tmRoot) > cTn > childTnLst > seq(mainSeq / interactiveSeq)
    for root_par in findall(tn_lst, "p:par"):
        seq_lst = find(root_par, "p:cTn/p:childTnLst")
        for seq in findall(seq_lst, "p:seq"):
            _process_seq(seq, timeline, slide_width_emu, slide_height_emu)

    return timeline


def _process_seq(
    seq,
    timeline: Timeline,
    slide_width_emu: int = 0,
    slide_height_emu: int = 0,
) -> None:
    seq_cTn = find(seq, "p:cTn")
    node_type = seq_cTn.get("nodeType") if seq_cTn is not None else None
    seq_id = seq_cTn.get("id") if seq_cTn is not None else None
    child_lst = find(seq, "p:cTn/p:childTnLst")
    if child_lst is None:
        return
    if node_type == "interactiveSeq":
        # 交互式触发动画：单独成一组，trigger=interactive
        group = AnimationGroup(trigger="interactive")
        state = {"prev_start": 0, "prev_end": 0}
        _collect_effects(
            child_lst, group, 0, slide_width_emu, slide_height_emu, state
        )
        if group.behaviors:
            timeline.groups.append(group)
        return

    # mainSeq：直接子 par 是"点击组"
    for par in findall(child_lst, "p:par"):
        c_tn = find(par, "p:cTn")
        trigger, base_delay = _trigger_of(c_tn, seq_id)
        group = AnimationGroup(trigger=trigger)
        group.start_delay_ms = base_delay
        state = {"prev_start": base_delay, "prev_end": base_delay}
        inner = find(par, "p:cTn/p:childTnLst")
        if inner is not None:
            _collect_effects(
                inner, group, base_delay, slide_width_emu, slide_height_emu, state
            )
        if group.behaviors:
            timeline.groups.append(group)


def _trigger_of(c_tn, seq_id: Optional[str]) -> tuple[str, int]:
    """一组动画怎么触发。

    OOXML 里"等点击"和"随页自动"是**两个并列的 cond**：

    .. code-block:: xml

        <p:cond delay="indefinite"/>                     <!-- 等点击 -->
        <p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond>  <!-- 随 seq 开始 -->

    以前只取第一个 cond，看到 ``indefinite`` 就一律判成"点击"，
    于是第 1/2 页那两组"进页自动播"的动画全被算成了点击组。

    ``evt="onBegin"`` 里的 ``<p:tn val="N"/>`` 指明"节点 N 开始时触发"——
    只有当 N 就是**这个 seq 自己**时才是"随页自动"；
    指向组内更早的节点则是"上一个效果结束后"。
    """
    st = find(c_tn, "p:stCondLst") if c_tn is not None else None
    conds = findall(st, "p:cond") if st is not None else []
    for cond in conds:
        if cond.get("evt") != "onBegin":
            continue
        ref = find(cond, "p:tn")
        ref_id = ref.get("val") if ref is not None else None
        if ref_id is not None and seq_id is not None and ref_id != seq_id:
            # 指向组内更早的节点 → "上一个效果结束后"，不是自动
            continue
        return "auto", _delay_of(cond)
    for cond in conds:
        if cond.get("delay") == "indefinite":
            return "click", 0
    if conds:
        return "auto", _delay_of(conds[0])
    return "click", 0


def _delay_of(cond) -> int:
    raw = cond.get("delay")
    if raw is None or raw == "indefinite":
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def _collect_effects(
    container,
    group: AnimationGroup,
    group_start: int,
    slide_width_emu: int,
    slide_height_emu: int,
    state: dict,
    after_wait: int = 0,
):
    """递归找出效果节点（带 presetID / nodeType 的 cTn），收集其行为。

    延时语义（PowerPoint 的实际行为）：

    * ``clickEffect`` —— 本组第一个效果，点击后立刻开始
    * ``withEffect``  —— 和上一个效果**同时**开始
    * ``afterEffect`` —— **上一个效果结束后**再等 N 毫秒

    ``afterEffect`` 的"N 毫秒"写在**外层那个 par** 的 ``stCondLst`` 上
    （效果自己的 cTn 里写的是 0），所以要沿递归往下传（``after_wait``）。
    以前是把外层的 500 直接当成"点击后 500ms"，少了"等上一个效果结束"，
    第 1/24 页的淡入就提前了整整 500ms。

    ``state`` 是**跨递归共享**的可变字典：上一个效果的起止时间要在
    兄弟节点之间传递，普通参数传不回去（效果节点往往比承载它的 par 深一层）。
    """
    for child in container:
        tag = child.tag.split("}")[-1]
        if tag not in ("par", "seq"):
            continue
        c_tn = find(child, "p:cTn")
        if c_tn is None:
            continue
        par_delay = _start_delay(c_tn)
        par_wait = par_delay if par_delay is not None else 0
        node_type = c_tn.get("nodeType")
        is_effect = c_tn.get("presetID") is not None or node_type in _EFFECT_NODE_TYPES

        if is_effect:
            own_delay = par_wait
            if node_type in ("afterEffect", "afterGroup"):
                start = state["prev_end"] + after_wait + own_delay
            elif node_type in ("withEffect", "withGroup"):
                start = state["prev_start"] + own_delay
            else:
                start = group_start + own_delay
            preset_id = c_tn.get("presetID")
            preset_class = c_tn.get("presetClass")
            behaviors = _read_behaviors(
                child,
                c_tn,
                preset_id,
                preset_class,
                start,
                slide_width_emu,
                slide_height_emu,
            )
            group.behaviors.extend(behaviors)
            for b in behaviors:
                if b.target_id and b.target_id not in group.target_ids:
                    group.target_ids.append(b.target_id)
            duration = max((b.duration_ms for b in behaviors), default=0)
            state["prev_start"] = start
            state["prev_end"] = start + duration
        else:
            inner = find(child, "p:cTn/p:childTnLst")
            if inner is not None:
                _collect_effects(
                    inner,
                    group,
                    group_start,
                    slide_width_emu,
                    slide_height_emu,
                    state,
                    after_wait + par_wait,
                )


def _start_delay(c_tn) -> Optional[int]:
    """cTn 的起始条件延时。None 表示 indefinite（等待触发）。"""
    if c_tn is None:
        return 0
    st = find(c_tn, "p:stCondLst")
    if st is None:
        return 0
    cond = find(st, "p:cond")
    if cond is None:
        return 0
    delay = cond.get("delay")
    if delay is None:
        return 0
    if delay == "indefinite":
        return None
    try:
        return int(delay)
    except ValueError:
        return 0


def _read_behaviors(
    effect_el,
    effect_c_tn,
    preset_id,
    preset_class,
    effect_delay: int,
    slide_width_emu: int = 0,
    slide_height_emu: int = 0,
) -> list[Behavior]:
    behaviors: list[Behavior] = []
    child_lst = find(effect_el, "p:cTn/p:childTnLst")
    if child_lst is None:
        return behaviors
    for el in child_lst:
        tag = el.tag.split("}")[-1]
        kind = _BEHAVIOR_TAGS.get(tag)
        if kind is None:
            continue
        c_bhvr = find(el, "p:cBhvr")
        if c_bhvr is None:
            continue
        c_tn = find(c_bhvr, "p:cTn")
        duration = int(c_tn.get("dur")) if c_tn is not None and c_tn.get("dur") else 0
        own_delay = _start_delay(c_tn)
        if own_delay is None:
            own_delay = 0

        target = find(c_bhvr, "p:tgtEl/p:spTgt")
        target_id = target.get("spid") if target is not None else None

        attr_names = [n.text or "" for n in findall(c_bhvr, "p:attrNameLst/p:attrName")]

        notes: list[str] = []
        keyframes = _read_keyframes(
            find(el, "p:tavLst"),
            attr_names[0] if attr_names else "",
            slide_width_emu,
            slide_height_emu,
            notes,
        )
        if not keyframes:
            keyframes = _read_from_to(
                el,
                attr_names[0] if attr_names else "",
                slide_width_emu,
                slide_height_emu,
                notes,
            )

        behavior = Behavior(
            type=kind,
            attr_name=attr_names[0] if attr_names else _default_attr(kind),
            target_id=target_id,
            duration_ms=duration,
            delay_ms=effect_delay + own_delay,
            keyframes=keyframes,
            preset_id=preset_id,
            preset_class=preset_class,
            calc_mode=el.get("calcmode") or "lin",
            notes=notes,
        )
        if kind == "animEffect":
            # 入场效果的具体做法：filter="wipe(left)" / "circle(in)" / "fade" …
            # 这是 PowerPoint 真正用来渲染的信息（presetID 只是 UI 标签），
            # 照着它翻译成 clip-path / opacity 才是逐帧一致的原生实现。
            behavior.filter_name = el.get("filter")
            behavior.transition = el.get("transition") or "in"
        if kind == "animMotion":
            path = el.get("path")
            if path:
                behavior.notes.append(f"path={path}")
        if kind == "cmd":
            # 命令型行为：``cmd="playFrom(0.0)"`` 之类 —— 播放媒体。
            # 媒体本体挂在目标形状上（``a:audioFile``），由 deck 层补上。
            behavior.command = el.get("cmd")
        behaviors.append(behavior)
    return behaviors


def _default_attr(kind: str) -> str:
    return {
        "animRot": "r",
        "animScale": "scale",
        "animMotion": "ppt_x",
        "animClr": "fillcolor",
        "set": "style.visibility",
    }.get(kind, "ppt_x")


def _read_keyframes(
    tav_lst,
    attr_name: str,
    slide_width_emu: int = 0,
    slide_height_emu: int = 0,
    notes: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    keyframes: list[dict[str, Any]] = []
    for tav in findall(tav_lst, "p:tav"):
        tm = tav.get("tm")
        try:
            t = int(tm) / 100000 if tm is not None else 0.0
        except ValueError:
            t = 0.0
        val = find(tav, "p:val")
        if val is None:
            continue
        value = _read_val(
            val, attr_name, slide_width_emu, slide_height_emu, notes
        )
        if value is not None:
            keyframes.append({"t": t, "v": value})
    keyframes.sort(key=lambda k: k["t"])
    return keyframes


def _read_val(
    val_el,
    attr_name: str,
    slide_width_emu: int = 0,
    slide_height_emu: int = 0,
    notes: Optional[list[str]] = None,
) -> Any:
    """读一个 <p:val>/<p:to>/<p:from> 里的值。

    OOXML 有两种"符号值"写法：
      "#ppt_w" / "ppt_w" —— 该属性的**当前值**（宽度=满、位移=0）
      "#ppt_y+.1"       —— 当前值 **加上**一个相对量（"浮入"效果就靠它）
    这里按属性语义解析成数值，运行时才知道怎么用。

    带相对量时把原始公式记进 ``notes`` —— 覆盖报告要靠它区分
    "源文件本来就让它不动"（``#ppt_x`` → ``#ppt_x``）和
    "相对位移被抹平了"（``#ppt_y+.1`` 却算出两个一样的值）。
    """
    str_val = find(val_el, "p:strVal")
    flt_val = find(val_el, "p:fltVal")
    clr_val = find(val_el, "p:clrVal")
    int_val = find(val_el, "p:intVal")
    if str_val is not None:
        raw = str_val.get("val") or ""
        if raw.startswith("#") or raw == attr_name:
            value = _self_value(
                raw.lstrip("#"), attr_name, slide_width_emu, slide_height_emu
            )
            if notes is not None and _has_relative_offset(raw):
                notes.append(f"公式 {raw}")
            return value
        return raw
    if flt_val is not None:
        return float(flt_val.get("val", 0))
    if int_val is not None:
        return int(int_val.get("val", 0))
    if clr_val is not None:
        srgb = find(clr_val, "a:srgbClr")
        scheme = find(clr_val, "a:schemeClr")
        if srgb is not None:
            return f"#{srgb.get('val')}"
        if scheme is not None:
            return f"theme:{scheme.get('val')}"
    return None


#: 符号值的名字 → 是不是位移类（位移类的相对量按"整页的比例"算）
_OFFSET_ATTRS = ("ppt_x", "ppt_y")


def _has_relative_offset(raw: str) -> bool:
    """公式里有没有相对量（``#ppt_y+.1`` / ``#ppt_y-.1``）。"""
    body = raw.lstrip("#")
    for sign in ("+", "-"):
        idx = body.find(sign)
        if idx > 0 and body[:idx] in ("ppt_x", "ppt_y", "ppt_w", "ppt_h", "r"):
            return True
    return False


def _self_value(
    name: str,
    attr_name: str,
    slide_width_emu: int = 0,
    slide_height_emu: int = 0,
) -> Any:
    """符号值 "ppt_w" / "ppt_y+.1" → 该属性在动画开始时的取值。

    ``ppt_x`` / ``ppt_y`` 在公式语言里是"相对整页宽/高的比例"，
    所以 ``#ppt_y+.1`` = 往下偏移整页高度的 10%。运行时把位移通道
    当作 **EMU 的 translate 偏移量**，所以这里直接换算成 EMU。

    以前只认精确的名字，``ppt_y+.1`` 落到兜底分支变成 0.0 ——
    "浮入"效果的位移被静默抹平了，而且报告还判它 native。
    """
    base = name
    delta = 0.0
    for sign in ("+", "-"):
        idx = name.find(sign)
        if idx > 0:
            head = name[:idx]
            tail = name[idx + 1 :]
            if head in _OFFSET_ATTRS or head in ("ppt_w", "ppt_h", "r"):
                try:
                    base = head
                    delta = float(tail)
                except ValueError:
                    base = name
                    delta = 0.0
                if sign == "-":
                    delta = -delta
                break

    if base in ("ppt_w", "ppt_h"):
        return 1.0  # 尺寸类的"当前值"就是满尺寸（渲染时按比例 1 处理）
    if base in _OFFSET_ATTRS:
        if delta == 0.0:
            return 0.0  # 位移类的"当前值"就是原位
        span = slide_width_emu if base == "ppt_x" else slide_height_emu
        return delta * span
    if base == "r":
        return 0.0
    if base == "style.opacity":
        return 1.0
    if base == "style.visibility":
        return "visible"
    return 0.0


def _read_from_to(
    el,
    attr_name: str,
    slide_width_emu: int = 0,
    slide_height_emu: int = 0,
    notes: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """退化路径：只有 <p:from>/<p:to> 子元素时读出关键帧。"""
    out: list[dict[str, Any]] = []
    frm = find(el, "p:from")
    to = find(el, "p:to")
    if frm is not None:
        value = _read_val(frm, attr_name, slide_width_emu, slide_height_emu, notes)
        if value is not None:
            out.append({"t": 0.0, "v": value})
    if to is not None:
        value = _read_val(to, attr_name, slide_width_emu, slide_height_emu, notes)
        if value is not None:
            out.append({"t": 1.0, "v": value})
    return out


def _maybe_num(value: str):
    try:
        return float(value)
    except ValueError:
        return value
