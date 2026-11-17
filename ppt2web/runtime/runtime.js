/* ppt2web —— 播放器外壳
 *
 * 两个 iframe 叠在一起：转场时新页在**后台**那个 iframe 里加载，
 * 加载完再交叉播放转场（旧页退出 + 新页进入）。
 * 所有数据都内联在页面里，file:// 直接双击也能跑（不依赖 fetch）。
 */
(function () {
  "use strict";

  var deck = window.PPT2WEB;
  if (!deck) return;

  var slides = deck.slides || [];
  var current = 0;
  var frame = document.getElementById("deck-frame");
  var iframe = document.getElementById("deck-iframe");
  var iframeBack = document.getElementById("deck-iframe-back");
  var posLabel = document.getElementById("deck-pos");
  var bar = document.getElementById("deck-bar");

  /* 哪些转场是原生实现的（和 render/report.py 的表对应） */
  var NATIVE_TRANSITIONS = {
    fade: 1,
    wipe: 1,
    push: 1,
    cover: 1,
    split: 1,
    cut: 1,
    dissolve: 1,
    zoom: 1
  };
  /* 近似实现的（3D 转场降级成 2D 效果） */
  var APPROX_TRANSITIONS = { flythrough: 1 };

  function slideSrc(i) {
    return slides[i].file;
  }

  /* ---------------------------------------------------------------- */
  /* 页面转场                                                          */
  /* ---------------------------------------------------------------- */

  /*
   * OOXML 的 dir 表示"擦除边缘移动的方向"（和动效滤镜一个约定）：
   *   u —— 边缘往上移 → 新页从**下**边出来
   *   d —— 边缘往下移 → 新页从**上**边出来
   *   l —— 边缘往左移 → 新页从**右**边出来
   *   r —— 边缘往右移 → 新页从**左**边出来
   */
  function revealFrom(dir) {
    switch (dir || "l") {
      case "u": return { x: 0, y: 100 };
      case "d": return { x: 0, y: 0 };
      case "r": return { x: 0, y: 0, fromLeft: true };
      default: return { x: 100, y: 0 };
    }
  }

  function wipeInset(dir, p) {
    var r = revealFrom(dir);
    var edge = 100 - p * 100;
    if (dir === "u") return "inset(0 0 " + edge + "% 0)";
    if (dir === "d") return "inset(" + edge + "% 0 0 0)";
    if (dir === "r") return "inset(0 " + edge + "% 0 0)";
    return "inset(0 0 0 " + edge + "%)";
  }

  function pushOffset(dir) {
    switch (dir || "l") {
      case "u": return { from: "0, 100%", to: "0, -100%" };
      case "d": return { from: "0, -100%", to: "0, 100%" };
      case "r": return { from: "-100%, 0", to: "100%, 0" };
      default: return { from: "100%, 0", to: "-100%, 0" };
    }
  }

  function coverOffset(dir) {
    switch (dir || "l") {
      case "u": return "0, 100%";
      case "d": return "0, -100%";
      case "r": return "-100%, 0";
      default: return "100%, 0";
    }
  }

  function resetFrame(el) {
    el.style.opacity = "";
    el.style.transform = "";
    el.style.clipPath = "";
  }

  /* 播放一次转场：cur 退出、back 进入。结束后 back 成为前台。 */
  function playTransition(cur, back, kind, dir, ms) {
    var dur = ms > 0 ? ms : 500;
    var opts = { duration: dur, fill: "both", easing: "ease-in-out" };
    var curAnim = null;
    var backAnim = null;

    resetFrame(cur);
    resetFrame(back);

    if (kind === "fade" || kind === "dissolve") {
      back.style.opacity = "0";
      backAnim = back.animate([{ opacity: 0 }, { opacity: 1 }], opts);
    } else if (kind === "wipe") {
      back.style.clipPath = wipeInset(dir, 1);
      backAnim = back.animate(
        [{ clipPath: wipeInset(dir, 1) }, { clipPath: wipeInset(dir, 0) }],
        opts
      );
    } else if (kind === "push") {
      var off = pushOffset(dir);
      back.style.transform = "translate(" + off.from + ")";
      cur.style.transform = "translate(0,0)";
      backAnim = back.animate(
        [{ transform: "translate(" + off.from + ")" }, { transform: "translate(0,0)" }],
        opts
      );
      curAnim = cur.animate(
        [{ transform: "translate(0,0)" }, { transform: "translate(" + off.to + ")" }],
        opts
      );
    } else if (kind === "cover") {
      var off2 = coverOffset(dir);
      back.style.transform = "translate(" + off2 + ")";
      backAnim = back.animate(
        [{ transform: "translate(" + off2 + ")" }, { transform: "translate(0,0)" }],
        opts
      );
    } else if (kind === "split") {
      back.style.clipPath = "inset(0 50% 0 50%)";
      backAnim = back.animate(
        [{ clipPath: "inset(0 50% 0 50%)" }, { clipPath: "inset(0 0% 0 0%)" }],
        opts
      );
    } else if (kind === "zoom") {
      back.style.transform = "scale(1.15)";
      back.style.opacity = "0.4";
      backAnim = back.animate(
        [
          { transform: "scale(1.15)", opacity: 0.4 },
          { transform: "scale(1)", opacity: 1 }
        ],
        opts
      );
    } else if (kind === "flythrough") {
      /* 3D 镜头运动在 CSS 里还原不了（离轴投影、非等比缩放）——
       * 降级成"推近 + 淡入"，在报告里标 approx。 */
      back.style.transform = "scale(1.25)";
      back.style.opacity = "0";
      backAnim = back.animate(
        [
          { transform: "scale(1.25)", opacity: 0 },
          { transform: "scale(1)", opacity: 1 }
        ],
        opts
      );
    } else {
      /* cut / 未知：直接换 */
      resetFrame(back);
      back.style.opacity = "1";
    }

    var anims = [curAnim, backAnim].filter(Boolean);
    var done = function () {
      if (curAnim) curAnim.cancel();
      resetFrame(cur);
      resetFrame(back);
      back.style.opacity = "1";
      cur.hidden = true;
      back.hidden = false;
    };
    if (!anims.length) {
      done();
      return;
    }
    Promise.all(anims.map(function (a) { return a.finished.catch(function () {}); })).then(
      done
    );
  }

  function show(i, opts) {
    if (i < 0) i = 0;
    if (i > slides.length - 1) i = slides.length - 1;
    current = i;
    var entry = slides[i] || {};
    var kind = entry.transition;
    var ms = entry.transitionMs || 0;
    var useTransition =
      (!opts || opts.animate !== false) &&
      kind &&
      (NATIVE_TRANSITIONS[kind] || APPROX_TRANSITIONS[kind]);

    if (!useTransition || !iframeBack) {
      resetFrame(iframe);
      iframe.hidden = false;
      iframe.src = slideSrc(i);
      if (iframeBack) {
        iframeBack.hidden = true;
        resetFrame(iframeBack);
      }
    } else {
      var cur = iframe;
      var back = iframeBack;
      back.hidden = false;
      resetFrame(back);
      back.onload = function () {
        back.onload = null;
        playTransition(cur, back, kind, entry.transitionDir, ms);
        /* 转场结束后，后台 iframe 成为前台 */
        iframe = back;
        iframeBack = cur;
      };
      back.src = slideSrc(i);
    }

    if (posLabel) posLabel.textContent = (i + 1) + " / " + slides.length;
    try {
      history.replaceState(null, "", "#" + (i + 1));
    } catch (e) {
      /* file:// 下可能不可用，忽略 */
    }
    scheduleAutoAdvance(i);
  }

  /* ``p:transition@advTm`` = 转场之后多少毫秒自动翻页 */
  var autoAdvanceTimer = null;

  function scheduleAutoAdvance(i) {
    if (autoAdvanceTimer) {
      clearTimeout(autoAdvanceTimer);
      autoAdvanceTimer = null;
    }
    var ms = (slides[i] || {}).advanceMs || 0;
    if (ms <= 0) return;
    autoAdvanceTimer = setTimeout(function () {
      autoAdvanceTimer = null;
      next();
    }, ms);
  }

  function next() {
    if (current < slides.length - 1) show(current + 1);
  }

  function prev() {
    if (current > 0) show(current - 1);
  }

  /* 等比缩放铺满视口（不做重排，保证版式一致） */
  function fit() {
    if (!deck.slideWidth || !deck.slideHeight) return;
    var scale = Math.min(
      window.innerWidth / deck.slideWidth,
      window.innerHeight / deck.slideHeight
    );
    frame.style.width = deck.slideWidth + "px";
    frame.style.height = deck.slideHeight + "px";
    /* transform-origin 默认 center，缩放后仍然居中 */
    frame.style.transform = "scale(" + scale + ")";
  }

  window.addEventListener("resize", fit);

  window.addEventListener("message", function (e) {
    var msg = e.data;
    if (!msg || typeof msg !== "object") return;
    switch (msg.type) {
      case "ppt2web-advance":
        next();
        break;
      case "ppt2web-prev":
        prev();
        break;
      case "ppt2web-ready":
        if (bar) bar.classList.add("live");
        break;
      default:
        break;
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ") {
      /* 幻灯片页要自己处理动画推进，这里转发过去而不是抢 */
      forwardKey(e.key);
    } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
      prev();
    } else if (e.key === "Home") {
      show(0);
    } else if (e.key === "End") {
      show(slides.length - 1);
    } else if (e.key === "f" || e.key === "F") {
      if (document.fullscreenElement) document.exitFullscreen();
      else document.documentElement.requestFullscreen && document.documentElement.requestFullscreen();
    } else if (e.key === "o" || e.key === "O") {
      if (bar) bar.style.opacity = bar.style.opacity === "1" ? "0" : "1";
    }
  });

  /* 把按键转发给当前幻灯片页（焦点不在 iframe 里时） */
  function forwardKey(key) {
    try {
      iframe.contentWindow.postMessage({ type: "ppt2web-key", key: key }, "*");
    } catch (e) {
      /* 跨源时忽略 */
    }
  }

  var btnPrev = document.getElementById("deck-prev");
  var btnNext = document.getElementById("deck-next");
  if (btnPrev) btnPrev.addEventListener("click", function (e) { e.stopPropagation(); prev(); });
  if (btnNext) btnNext.addEventListener("click", function (e) { e.stopPropagation(); next(); });

  var hash = parseInt((location.hash || "").replace("#", ""), 10);
  fit();
  /* 首页直接显示，不播转场 */
  show(isNaN(hash) ? 0 : hash - 1, { animate: false });
})();
