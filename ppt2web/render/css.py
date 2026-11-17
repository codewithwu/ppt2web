"""共享样式表。"""

BASE_CSS = """/* ppt2web —— 幻灯片与播放器样式 */
* { box-sizing: content-box; }

html, body {
  margin: 0;
  padding: 0;
  background: #1a1a1c;
  font-family: "Noto Sans CJK SC", "Noto Sans", "DejaVu Sans", sans-serif;
  -webkit-font-smoothing: antialiased;
}

.stage {
  position: relative;
  overflow: hidden;
  background: #ffffff;
  transform-origin: 0 0;
}

.shell { position: absolute; }
.anim {
  position: relative;
  width: 100%;
  height: 100%;
  transform-origin: 50% 50%;
  will-change: transform, opacity;
}

.geo {
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
}

.pic { display: block; }
.picwrap {
  position: absolute;
  inset: 0;
  overflow: hidden;
}

.tx { pointer-events: none; }
.tx p { min-height: 1em; }
.bul { display: inline-block; }

/* 矢量文字：字形轮廓 + 一层看不见的真实文本（可选中/可搜索/读屏器可读） */
.tx-svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
.tx-a11y {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}

/* 表格的无障碍层：一张真的 <table>，读屏器能按行列导航 */
.tbl-a11y {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
  border-collapse: collapse;
}

.gp-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border: 1px dashed #b9b9c6;
  background: rgba(0, 0, 0, 0.03);
  color: #6b6b7b;
  font-size: 12px;
}
.gp-placeholder small { font-size: 10px; opacity: 0.7; }

/* ---------- 播放器 ---------- */
body.deck-body { overflow: hidden; }

.deck {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.deck-frame {
  position: relative;
  transform-origin: center center;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.55);
  background: #fff;
}

.deck-frame iframe {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
}

.deck-bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 16px;
  background: rgba(20, 20, 24, 0.82);
  color: #f0f0f4;
  font-size: 13px;
  opacity: 0;
  transition: opacity 0.18s ease;
  z-index: 10;
}
.deck-body:hover .deck-bar,
.deck-bar:focus-within { opacity: 1; }

.deck-bar button {
  background: rgba(255, 255, 255, 0.12);
  border: 0;
  color: inherit;
  border-radius: 6px;
  padding: 5px 12px;
  font: inherit;
  cursor: pointer;
}
.deck-bar button:hover { background: rgba(255, 255, 255, 0.22); }
.deck-bar .spacer { flex: 1; }
.deck-bar .pos { font-variant-numeric: tabular-nums; opacity: 0.85; }
.deck-bar .hint { opacity: 0.55; font-size: 12px; }

@media print {
  html, body { background: #fff; }
  .deck-bar { display: none !important; }
  .deck { position: static; display: block; }
  .deck-frame { box-shadow: none; transform: none !important; page-break-after: always; }
  .deck-frame iframe { border: 0; }
}
"""

PLAYER_CSS = """/* ppt2web —— 播放器外壳 */
body.deck-body { overflow: hidden; }
.deck { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; }
.deck-frame { position: relative; transform-origin: center center; box-shadow: 0 24px 80px rgba(0,0,0,.55); background:#fff; }
.deck-frame iframe { display:block; width:100%; height:100%; border:0; }
/* 两个 iframe 叠在一起：转场时新页在后台 iframe 加载，好了再交叉播放 */
.deck-frame iframe { position:absolute; left:0; top:0; }
.deck-bar { position: fixed; left:0; right:0; bottom:0; display:flex; align-items:center; gap:14px;
  padding:10px 16px; background:rgba(20,20,24,.82); color:#f0f0f4; font-size:13px; opacity:0;
  transition:opacity .18s ease; z-index:10; }
.deck-body:hover .deck-bar, .deck-bar:focus-within { opacity:1; }
.deck-bar button { background:rgba(255,255,255,.12); border:0; color:inherit; border-radius:6px;
  padding:5px 12px; font:inherit; cursor:pointer; }
.deck-bar button:hover { background:rgba(255,255,255,.22); }
.deck-bar .spacer { flex:1; }
.deck-bar .pos { font-variant-numeric: tabular-nums; opacity:.85; }
.deck-bar .hint { opacity:.55; font-size:12px; }
"""

PRINT_CSS = """/* ppt2web —— 打印视图（逐页对齐导出 PDF） */
html, body { margin:0; padding:0; background:#fff; }
.print-page { page-break-after: always; break-after: page; margin:0; padding:0; }
.print-page:last-child { page-break-after: auto; break-after: auto; }
.print-page iframe { display:block; width:100%; height:100%; border:0; }
"""
