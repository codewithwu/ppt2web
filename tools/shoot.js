#!/usr/bin/env node
/* ppt2web 开发工具：把产物页渲染成截图（可抓动画中间帧）。
 *
 *   node tools/shoot.js --out /tmp/shots --slides 001,002 --anim --frames 100,300,600
 *
 * 依赖本机已有的 puppeteer-core（~/.npm/_npx 里）+ chrome-headless-shell。
 * 截图用于人工目视比对（PowerPoint 原稿 vs 产物）以及阶段 3 的视觉回归基线。
 */
"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");

/* puppeteer-core / chrome-headless-shell 的位置（可用环境变量覆盖） */
function findModule(name) {
  const candidates = [
    process.env.PPT2WEB_NODE_MODULES,
    path.join(os.homedir(), ".npm/_npx"),
  ].filter(Boolean);
  for (const base of candidates) {
    if (!fs.existsSync(base)) continue;
    for (const entry of fs.readdirSync(base)) {
      const p = path.join(base, entry, "node_modules", name);
      if (fs.existsSync(p)) return p;
    }
    const direct = path.join(base, name);
    if (fs.existsSync(direct)) return direct;
  }
  throw new Error("找不到 " + name + "（设置 PPT2WEB_NODE_MODULES 指向 node_modules 目录）");
}

function findChrome() {
  const bases = [
    path.join(os.homedir(), ".cache/hyperframes/chrome"),
    "/usr/bin",
  ];
  for (const base of bases) {
    if (!fs.existsSync(base)) continue;
    const stack = [base];
    while (stack.length) {
      const dir = stack.pop();
      for (const entry of fs.readdirSync(dir)) {
        const full = path.join(dir, entry);
        const st = fs.statSync(full);
        if (st.isDirectory()) {
          stack.push(full);
        } else if (entry === "chrome-headless-shell" || entry === "chrome") {
          return full;
        }
      }
    }
  }
  for (const name of ["google-chrome", "chromium", "chromium-browser"]) {
    const p = require("child_process")
      .execSync(`command -v ${name} || true`, { encoding: "utf8" })
      .trim();
    if (p) return p;
  }
  throw new Error("找不到 chrome-headless-shell");
}

function parseArgs(argv) {
  const out = { out: "/tmp/shots", slides: [], anim: false, frames: [0], prefix: "", width: 1280, height: 720, deck: "", freeze: null, probe: false };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--out") out.out = argv[++i];
    else if (a === "--slides") out.slides = argv[++i].split(",").map((s) => s.trim()).filter(Boolean);
    else if (a === "--anim") out.anim = true;
    else if (a === "--frames") out.frames = argv[++i].split(",").map(Number);
    else if (a === "--prefix") out.prefix = argv[++i];
    else if (a === "--deck") out.deck = argv[++i];
    else if (a === "--freeze") out.freeze = Number(argv[++i]);
    else if (a === "--probe") out.probe = true;
    else if (a === "--width") out.width = Number(argv[++i]);
    else if (a === "--clip") out.clip = argv[++i];            /* "x,y,w,h"（页面像素） */
    else if (a === "--scale") out.scale = Number(argv[++i]);  /* 设备像素比，放大看细节 */
    else if (a === "--height") out.height = Number(argv[++i]);
  }
  return out;
}

(async () => {
  const args = parseArgs(process.argv);
  const puppeteer = require(findModule("puppeteer-core"));
  const executablePath = findChrome();
  fs.mkdirSync(args.out, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath,
    headless: "shell",
    args: ["--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1"],
    defaultViewport: { width: args.width, height: args.height },
  });

  const page = await browser.newPage();
  for (const slide of args.slides) {
    const file = path.resolve(args.deck, "slides", slide + ".html");
    if (!fs.existsSync(file)) {
      console.error("跳过（不存在）：" + file);
      continue;
    }
    const url = "file://" + file + (args.anim ? "?autoplay=1" : "");
    await page.goto(url, { waitUntil: "load" });
    if (args.freeze !== null) {
      /* 定格：把 WAAPI 动画停到指定时刻，截图才可复现 */
      const frozen = await page.evaluate((t) => {
        const out = [];
        document.getAnimations().forEach((a) => {
          try {
            a.currentTime = t;
            a.pause();
            out.push({ ok: true, state: a.playState, ct: a.currentTime });
          } catch (e) {
            out.push({ ok: false, err: String(e) });
          }
        });
        return out;
      }, args.freeze);
      if (args.probe) console.log("  frozen: " + JSON.stringify(frozen));
      await new Promise((r) => setTimeout(r, 150));
    }
    if (args.probe) {
      const state = await page.evaluate(() => {
        const anims = document.getAnimations().map((a) => ({
          state: a.playState,
          currentTime: a.currentTime,
          target: a.effect && a.effect.target ? a.effect.target.className : null,
          keys: a.effect ? a.effect.getKeyframes() : null,
        }));
        const shells = [...document.querySelectorAll(".shell")].map((el) => {
          const anim = el.querySelector(".anim");
          if (!anim) return null;
          const cs = getComputedStyle(anim);
          return {
            id: el.getAttribute("data-shape-id"),
            clip: cs.clipPath,
            vis: cs.visibility,
            op: cs.opacity,
            inlineVis: anim.style.visibility || "",
          };
        });
        return { anims, shells };
      });
      console.log("  animations: " + JSON.stringify(state.anims));
      console.log("  shells: " + JSON.stringify(state.shells));
    }
    let elapsed = 0;
    for (const frame of args.frames) {
      const wait = Math.max(0, frame - elapsed);
      if (wait) await new Promise((r) => setTimeout(r, wait));
      elapsed = frame;
      const name = `${args.prefix}${slide}${frame ? "-" + frame + "ms" : ""}.png`;
      const shot = { path: path.join(args.out, name) };
      if (args.clip) {
        const [cx, cy, cw, ch] = args.clip.split(",").map(Number);
        shot.clip = { x: cx, y: cy, width: cw, height: ch };
      }
      if (args.scale) shot.deviceScaleFactor = args.scale;
      await page.screenshot(shot);
      console.log("  " + path.join(args.out, name));
    }
  }
  await browser.close();
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
