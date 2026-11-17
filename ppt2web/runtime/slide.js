/* ppt2web —— 幻灯片动画引擎
 *
 * 直接解释 PPT 的行为树（p:anim / p:animRot / p:set ...），
 * 把每个形状的多条行为合并成一条 WAAPI 关键帧动画。
 * presetID 只用于覆盖报告的语义命名，不参与播放逻辑。
 */
(function () {
  "use strict";

  var timeline = window.PPT2WEB_TIMELINE;
  if (!timeline || !timeline.groups || !timeline.groups.length) {
    window.parent !== window && post({ type: "ppt2web-settled" });
    return;
  }

  var groups = timeline.groups;
  var groupIndex = 0;
  var playing = false;

  /* 擦除方向约定（motion / side）—— 见 FILTERS 注释 */
  if (timeline.options && timeline.options.wipeDirection) {
    WIPE_MODE = timeline.options.wipeDirection;
  }

  function post(msg) {
    try {
      window.parent.postMessage(msg, "*");
    } catch (e) {
      /* 独立打开时忽略 */
    }
  }

  function byId(id) {
    return document.querySelector('[data-shape-id="' + id + '"] .anim');
  }

  /* ---------------------------------------------------------------- */
  /* 行为 → 通道                                                       */
  /* ---------------------------------------------------------------- */

  var CHANNEL_BY_ATTR = {
    ppt_x: "tx",
    ppt_y: "ty",
    ppt_w: "sx",
    ppt_h: "sy",
    r: "rot",
    "style.opacity": "opacity",
    "style.visibility": "visibility",
    fillcolor: "fillcolor",
  };

  function channelOf(behavior) {
    if (behavior.type === "animRot") return "rot";
    if (behavior.type === "animScale") return "scale";
    if (behavior.type === "animMotion") return "tx";
    if (behavior.type === "set") return "visibility";
    if (behavior.type === "animClr") return "fillcolor";
    return CHANNEL_BY_ATTR[behavior.attr_name] || "tx";
  }

  /* ---------------------------------------------------------------- */
  /* 入场效果滤镜（p:animEffect）                                       */
  /* ---------------------------------------------------------------- */

  /*
   * PowerPoint 把入场效果写成了 filter="wipe(left)" 这种精确描述，
   * presetID 只是 UI 标签。照着 filter 翻译成 clip-path / opacity
   * 才是逐帧一致的原生实现（而不是"用位移近似"）。
   *
   * 方向约定有两种读法，OOXML 本身没说死：
   *   motion —— 名字是"擦除边缘移动的方向"：wipe(left) = 边缘向左移，内容从右侧显现
   *   side   —— 名字是"显现的起始边"：wipe(left) = 内容从左侧显现
   * 两种都实现，用 timeline.options.wipeDirection 切换（默认 motion）。
   * 真实文件里 presetSubtype（UI 标签）和 filter 可能互相矛盾，
   * 所以这个开关是必要的，不是过度设计。
   */
  var WIPE_MODE = "motion";

  function pct(v) {
    return (Math.round(v * 10) / 10).toFixed(1) + "%";
  }

  /* dir: up/down/left/right */
  function wipe(dir) {
    return function (p) {
      var x = pct((1 - p) * 100);
      if (WIPE_MODE === "side") {
        /* 起始边 = dir → 裁掉对侧 */
        if (dir === "up") return "inset(0 0 " + x + " 0)";
        if (dir === "down") return "inset(" + x + " 0 0 0)";
        if (dir === "left") return "inset(0 " + x + " 0 0)";
        return "inset(0 0 0 " + x + ")";
      }
      /* motion：边缘朝 dir 移动 → 起始边是对侧 */
      if (dir === "up") return "inset(" + x + " 0 0 0)";
      if (dir === "down") return "inset(0 0 " + x + " 0)";
      if (dir === "left") return "inset(0 0 0 " + x + ")";
      return "inset(0 " + x + " 0 0)";
    };
  }

  var FILTERS = {
    fade: { kind: "opacity" },
    dissolve: { kind: "opacity" },
    "wipe(up)": { kind: "clip", fn: wipe("up") },
    "wipe(down)": { kind: "clip", fn: wipe("down") },
    "wipe(left)": { kind: "clip", fn: wipe("left") },
    "wipe(right)": { kind: "clip", fn: wipe("right") },
    "circle(in)": {
      kind: "clip",
      fn: function (p) {
        return "circle(" + pct(p * 75) + " at 50% 50%)";
      },
    },
    "circle(out)": {
      kind: "clip",
      fn: function (p) {
        return "circle(" + pct((1 - p) * 75) + " at 50% 50%)";
      },
    },
    /* 谷仓门：从中间向左右打开（竖向） */
    "barn(inVertical)": {
      kind: "clip",
      fn: function (p) {
        var half = p * 50;
        return (
          "polygon(" +
          pct(50 - half) + " 0%, " +
          pct(50 + half) + " 0%, " +
          pct(50 + half) + " 100%, " +
          pct(50 - half) + " 100%)"
        );
      },
    },
    "barn(inHorizontal)": {
      kind: "clip",
      fn: function (p) {
        var half = p * 50;
        return (
          "polygon(0% " + pct(50 - half) + "%, 100% " + pct(50 - half) + "%, " +
          "100% " + pct(50 + half) + "%, 0% " + pct(50 + half) + "%)"
        );
      },
    },
    /* 随机条：横向若干条，各自错开时间从左向右显现 */
    "randombar(horizontal)": {
      kind: "clip",
      fn: function (p) {
        var n = 8;
        var pts = [];
        for (var i = 0; i < n; i++) {
          var phase = (i * 0.37) % 1; /* 固定错位，视觉上接近随机 */
          var local = Math.max(0, Math.min(1, (p - phase * 0.5) / 0.5));
          var w = local * 100;
          var y0 = (i / n) * 100;
          var y1 = ((i + 1) / n) * 100;
          pts.push("0% " + pct(y0));
          pts.push(pct(w) + " " + pct(y0));
          pts.push(pct(w) + " " + pct(y1));
          pts.push("0% " + pct(y1));
        }
        return "polygon(" + pts.join(", ") + ")";
      },
    },
    /* 随机条：竖向若干条，各自错开时间从上向下显现 */
    "randombar(vertical)": {
      kind: "clip",
      fn: function (p) {
        var n = 8;
        var pts = [];
        for (var i = 0; i < n; i++) {
          var phase = (i * 0.37) % 1;
          var local = Math.max(0, Math.min(1, (p - phase * 0.5) / 0.5));
          var h = local * 100;
          var x0 = (i / n) * 100;
          var x1 = ((i + 1) / n) * 100;
          pts.push(pct(x0) + " 0%");
          pts.push(pct(x1) + " 0%");
          pts.push(pct(x1) + " " + pct(h));
          pts.push(pct(x0) + " " + pct(h));
        }
        return "polygon(" + pts.join(", ") + ")";
      },
    },
  };

  function filterSpec(behavior) {
    /* 时间线 JSON 里的键是 filter（parse 层叫 filter_name） */
    var name = behavior.filter || behavior.filter_name;
    if (!name) return null;
    return FILTERS[name] || null;
  }

  /* 效果进度：0 = 还没开始，1 = 已完成 */
  function effectProgress(behavior, t) {
    var d = behavior.delay_ms || 0;
    var dur = Math.max(behavior.duration_ms || 0, 1);
    if (t <= d) return 0;
    if (t >= d + dur) return 1;
    return (t - d) / dur;
  }

  function effectValue(spec, p) {
    if (spec.kind === "opacity") return p;
    return spec.fn(p);
  }

  function isDiscrete(channel) {
    return channel === "visibility";
  }

  /* 数值通道的取值范围与单位 */
  var NUMERIC = {
    tx: { base: 0, unit: "px", scale: 1 / 9525 },
    ty: { base: 0, unit: "px", scale: 1 / 9525 },
    sx: { base: 1, unit: "", scale: 1 },
    sy: { base: 1, unit: "", scale: 1 },
    rot: { base: 0, unit: "deg", scale: 1 },
    opacity: { base: 1, unit: "", scale: 1 },
    scale: { base: 1, unit: "", scale: 1 },
  };

  function behaviorValue(behavior, localT) {
    var kfs = behavior.keyframes || [];
    if (!kfs.length) return null;
    if (kfs.length === 1) return kfs[0].v;
    if (localT <= kfs[0].t) return kfs[0].v;
    for (var i = 1; i < kfs.length; i++) {
      if (localT <= kfs[i].t) {
        var a = kfs[i - 1];
        var b = kfs[i];
        var span = b.t - a.t;
        if (span <= 0) return b.v;
        var ratio = (localT - a.t) / span;
        return lerpValue(a.v, b.v, ratio);
      }
    }
    return kfs[kfs.length - 1].v;
  }

  function lerpValue(a, b, r) {
    if (typeof a === "number" && typeof b === "number") return a + (b - a) * r;
    return r < 0.5 ? a : b;
  }

  /* ---------------------------------------------------------------- */
  /* 合并：把同一形状的多条行为折叠成一条关键帧序列                    */
  /* ---------------------------------------------------------------- */

  function buildTargetAnimation(behaviors, groupDuration) {
    var channels = {};
    var effects = [];
    var sampleTimes = { 0: true };

    behaviors.forEach(function (b) {
      var spec = filterSpec(b);
      if (spec) {
        effects.push({ behavior: b, spec: spec });
        sampleTimes[b.delay_ms] = true;
        sampleTimes[b.delay_ms + b.duration_ms] = true;
        return;
      }
      var ch = channelOf(b);
      (channels[ch] = channels[ch] || []).push(b);
      sampleTimes[b.delay_ms] = true;
      sampleTimes[b.delay_ms + b.duration_ms] = true;
      (b.keyframes || []).forEach(function (kf) {
        sampleTimes[b.delay_ms + kf.t * b.duration_ms] = true;
      });
    });

    /* 可见性在第一次 set 之前的状态：与第一次 set 的目标相反 */
    var visDefault = visibilityDefault(channels.visibility);

    var times = Object.keys(sampleTimes)
      .map(Number)
      .sort(function (a, b) {
        return a - b;
      });

    var frames = times.map(function (t) {
      var state = {};
      Object.keys(channels).forEach(function (ch) {
        state[ch] = resolveChannel(channels[ch], ch, t, visDefault);
      });
      /* 入场效果：在整条时间轴上采样，保证效果开始前元素就是"藏起来"的 */
      effects.forEach(function (eff) {
        var p = effectProgress(eff.behavior, t);
        var val = effectValue(eff.spec, p);
        if (eff.spec.kind === "opacity") {
          /* 已经有显式的透明度动画时不打架 */
          if (state.opacity === undefined) state.opacity = val;
        } else {
          state.clip = val;
        }
      });
      return {
        t: t,
        offset: groupDuration > 0 ? Math.min(1, t / groupDuration) : 0,
        state: state,
      };
    });

    var out = frames.map(function (f) {
      var s = f.state;
      var parts = [];
      if (s.tx !== undefined || s.ty !== undefined) {
        parts.push(
          "translate(" +
            fmt((s.tx || 0) * NUMERIC.tx.scale) +
            "px," +
            fmt((s.ty || 0) * NUMERIC.ty.scale) +
            "px)"
        );
      }
      if (s.rot !== undefined) parts.push("rotate(" + fmt(s.rot) + "deg)");
      if (s.sx !== undefined || s.sy !== undefined) {
        parts.push("scale(" + fmt(s.sx === undefined ? 1 : s.sx) + "," + fmt(s.sy === undefined ? 1 : s.sy) + ")");
      }
      var frame = { transform: parts.length ? parts.join(" ") : "none" };
      if (s.opacity !== undefined) frame.opacity = s.opacity;
      if (s.visibility !== undefined) frame.visibility = s.visibility;
      if (s.clip !== undefined) frame.clipPath = s.clip;
      frame.offset = f.offset;
      return frame;
    });

    /* WAAPI 要求首个 offset 为 0、末个为 1 */
    if (out.length) {
      out[0].offset = 0;
      if (out[out.length - 1].offset < 1) {
        var last = {};
        for (var key in out[out.length - 1]) last[key] = out[out.length - 1][key];
        last.offset = 1;
        out.push(last);
      }
    }
    return out;
  }

  /* 第一次 set 之前元素应该是什么状态 */
  function visibilityDefault(list) {
    if (!list || !list.length) return undefined;
    var earliest = list[0];
    for (var i = 1; i < list.length; i++) {
      if (list[i].delay_ms < earliest.delay_ms) earliest = list[i];
    }
    var v = firstValue(earliest, "visibility");
    if (v === undefined || v === null) return undefined;
    return String(v).toLowerCase() === "visible" ? "hidden" : "visible";
  }

  function fmt(v) {
    return (Math.round(v * 1000) / 1000).toString();
  }

  /* 某一时刻某通道的值：优先取"已开始且覆盖该时刻"的行为里最晚开始的那个 */
  function resolveChannel(list, channel, t, discreteDefault) {
    var covering = null;
    var latestStarted = null;
    for (var i = 0; i < list.length; i++) {
      var b = list[i];
      var end = b.delay_ms + Math.max(b.duration_ms, 1);
      if (b.delay_ms <= t && t <= end) {
        if (!covering || b.delay_ms > covering.delay_ms) covering = b;
      }
      if (b.delay_ms <= t && (!latestStarted || b.delay_ms > latestStarted.delay_ms)) {
        latestStarted = b;
      }
    }
    var chosen = covering || latestStarted;
    if (!chosen) {
      /* 还没开始：离散通道用"第一次 set 之前"的状态 */
      if (isDiscrete(channel)) return discreteDefault;
      var first = list[0];
      return firstValue(first, channel);
    }
    if (isDiscrete(channel)) {
      var v = behaviorValue(chosen, 0);
      return v === null ? undefined : v;
    }
    var localT = chosen.duration_ms > 0 ? (t - chosen.delay_ms) / chosen.duration_ms : 1;
    localT = Math.max(0, Math.min(1, localT));
    var val = behaviorValue(chosen, localT);
    if (val === null) return undefined;
    if (typeof val === "string") {
      var n = parseFloat(val);
      return isNaN(n) ? undefined : n;
    }
    return val;
  }

  function firstValue(b, channel) {
    var kfs = b.keyframes || [];
    if (!kfs.length) return undefined;
    var v = kfs[0].v;
    if (typeof v === "string") {
      var n = parseFloat(v);
      return isNaN(n) ? undefined : n;
    }
    return v;
  }

  /* ---------------------------------------------------------------- */
  /* 播放                                                               */
  /* ---------------------------------------------------------------- */

  function groupDuration(group) {
    var max = 0;
    (group.behaviors || []).forEach(function (b) {
      max = Math.max(max, b.delay_ms + b.duration_ms);
    });
    return Math.max(max, 1);
  }

  /* ---------------------------------------------------------------- */
  /* 命令型行为：播放媒体                                             */
  /* ---------------------------------------------------------------- */

  /*
   * PowerPoint 用 ``<p:cmd cmd="playFrom(0.0)">`` 表示"播放这个媒体"，
   * 媒体本体挂在目标形状上（``a:audioFile``）。
   *
   * 浏览器的自动播放策略会拦掉没有用户手势的播放 —— 那是浏览器的规矩，
   * 不是我们能绕过的。失败就静默跳过（元素还在，用户点一下就能播）。
   */
  function playMediaCommands(group) {
    (group.behaviors || []).forEach(function (b) {
      if (b.type !== "cmd" || !b.media) return;
      var el = document.getElementById("ppt2web-media-" + b.media);
      if (!el) return;
      var cmd = b.command || "";
      var m = /playFrom\(\s*([0-9.]+)\s*\)/.exec(cmd);
      if (m) {
        try {
          el.currentTime = parseFloat(m[1]) || 0;
        } catch (e) {
          /* 还没准备好，忽略 */
        }
      }
      var p = el.play();
      if (p && p.catch) p.catch(function () {});
    });
  }

  function playGroup(index) {
    if (index >= groups.length) {
      post({ type: "ppt2web-settled" });
      return;
    }
    var group = groups[index];
    playMediaCommands(group);
    var duration = groupDuration(group);
    var byTarget = {};
    (group.behaviors || []).forEach(function (b) {
      if (!b.target_id) return;
      (byTarget[b.target_id] = byTarget[b.target_id] || []).push(b);
    });

    var animations = [];
    Object.keys(byTarget).forEach(function (targetId) {
      var el = byId(targetId);
      if (!el) return;
      var frames = buildTargetAnimation(byTarget[targetId], duration);
      if (!frames.length) return;
      var anim = el.animate(frames, {
        duration: duration,
        easing: "linear",
        fill: "both",
      });
      animations.push(anim);
    });

    playing = true;
    var waitMs = duration + 40;
    setTimeout(function () {
      playing = false;
      groupIndex = index + 1;
      if (groupIndex < groups.length) {
        post({ type: "ppt2web-group", index: groupIndex, total: groups.length });
        if (groups[groupIndex].trigger === "auto") {
          playGroup(groupIndex);
        }
      } else {
        post({ type: "ppt2web-settled" });
      }
    }, waitMs);
  }

  /* 初始状态：所有参与动画的形状先摆到"动画开始前"的样子 */
  function applyInitialState() {
    var perTarget = {};
    groups.forEach(function (group) {
      (group.behaviors || []).forEach(function (b) {
        if (!b.target_id) return;
        (perTarget[b.target_id] = perTarget[b.target_id] || []).push(b);
      });
    });
    Object.keys(perTarget).forEach(function (id) {
      var el = byId(id);
      if (!el) return;
      var visList = perTarget[id].filter(function (b) {
        return b.attr_name === "style.visibility";
      });
      if (!visList.length) return;
      var def = visibilityDefault(visList);
      if (def) el.style.visibility = def;
    });
  }

  function advance() {
    if (playing) return;
    if (groupIndex < groups.length) {
      playGroup(groupIndex);
    } else {
      post({ type: "ppt2web-advance" });
    }
  }

  function init() {
    applyInitialState();
    post({ type: "ppt2web-ready" });

    /* ?autoplay=1 或 #autoplay：进页自动播第一组（演示/自检用） */
    var autoplay =
      /[?&]autoplay/.test(location.search) || location.hash.indexOf("autoplay") >= 0;

    /* 第一组如果是自动的，直接播；否则等第一次点击 */
    if (groups.length && (groups[0].trigger === "auto" || autoplay)) {
      playGroup(0);
    }

    document.addEventListener("click", function (e) {
      if (e.target && e.target.closest && e.target.closest("a")) return;
      advance();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === " " || e.key === "ArrowRight" || e.key === "PageDown" || e.key === "Enter") {
        e.preventDefault();
        advance();
      } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
        post({ type: "ppt2web-prev" });
      }
    });

    /* 播放器外壳转发过来的按键（焦点不在本页时） */
    window.addEventListener("message", function (e) {
      var msg = e.data;
      if (!msg || msg.type !== "ppt2web-key") return;
      if (msg.key === " " || msg.key === "ArrowRight" || msg.key === "PageDown") {
        advance();
      } else if (msg.key === "ArrowLeft" || msg.key === "PageUp") {
        post({ type: "ppt2web-prev" });
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
