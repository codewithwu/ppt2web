# my--playground

个人实验场仓库。当前主力项目是 **ppt2web** —— 把 `.pptx` 转成**可以在浏览器里放映的自包含网页包**。

```
pptx  ──►  ppt2web convert  ──►  out/index.html  ──►  双击就放（离线，不联网）
```

- **图片无损** —— 嵌入位图字节级原样落盘，不做任何重编码；原生 SVG 保持矢量
- **内容不丢** —— 文本、表格、图表、图形、图片、主题色全部还原；验收有逐字符断言
- **动画保留** —— 直接解释 PPT 的动画行为树（不是"预设近似"），时机/对象/方向/时长/顺序都对
- **文字矢量化** —— 默认把文字转成字形轮廓：不依赖任何字体、不依赖观看者环境、版式自己算
- **产物零依赖** —— 转换出来的网页包不联网、不引外部 JS/CSS/字体，双击 `file://` 就能放映

> 详细设计、实现细节、动效还原规则、字体匹配策略见 [`ppt2web/README.md`](./ppt2web/README.md)。

---

## 环境要求

| 用途 | 要求 |
|---|---|
| 转换（核心功能） | Python ≥ 3.11，**不需要** pip 装任何运行时依赖 |
| 文字矢量化（默认模式） | 需要 `fontTools` + `brotli`（构建期依赖，产物仍然零依赖） |
| 导出 PDF / 抓图比对 | 本机 Chrome 或 `chrome-headless-shell` |
| 重新导入开源字体 | Node.js ≥ 18 + npm（一次性，之后不再需要） |

## 安装

### 依赖分组

`pyproject.toml` 里依赖是分层放的，按需装：

| 分组 | 内容 | 什么时候需要 |
|---|---|---|
| `dependencies`（主依赖） | **空** —— 只用标准库解析 OOXML | 始终 |
| `text-vector` | `fonttools` + `brotli` | 用默认的矢量文字模式时 |
| `media` | `torch`(CPU) / `transformers` / `kokoro-onnx` / `soundfile` / `numpy` / `onnxruntime` | 只在跑本地 TTS、BGM 生成时需要（**ppt2web 本身用不到**） |
| `dev` | `ppt2web[text-vector]` | 跑单元测试时 |

### 方式一：用仓库里已有的 `.venv`（推荐）

```bash
uv pip install --python .venv/bin/python -e ".[text-vector]"
```

### 方式二：新建环境

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[text-vector]"
# 需要本地语音/音乐时再加上 media 档（会拉 ~200MB 的 CPU 版 torch）
uv pip install --python .venv/bin/python -e ".[text-vector,media]"
```

### 方式三：pip

```bash
pip install -e ".[text-vector]"
```

### 镜像配置

`pyproject.toml` 里已经配好清华源（PyPI 官方源慢 100 倍）：

```toml
[[tool.uv.index]]
url = "https://pypi.tuna.tsinghua.edu.cn/simple"
default = true
```

同时 `torch` 被钉在 PyTorch 官方 **CPU 轮子**索引上，避免误拉 ~2GB 的 CUDA 包
（pip 用户需自己加 `--extra-index-url https://download.pytorch.org/whl/cpu`）。

### 字体

开源替代字体（思源宋体/黑体 SC、Arimo、Carlito、Monoton）**已经内置**在
`ppt2web/fonts/`，开箱即用，不需要联网。

商用字体（阿里巴巴普惠体、演示夏行楷……）不进版本库，把字体文件丢进
`ppt2web/fonts/local/` 即可，转换器会自动优先使用"真身"。
字体名不必严格等于 PPT 里的 typeface（商用字体常带版本号）：

| PPT 里的 typeface | 可用的文件名 |
|---|---|
| `阿里巴巴普惠体` | `阿里巴巴普惠体.ttf`、`阿里巴巴普惠体-3.0 55 Regular.ttf` |
| `思源宋体 CN Heavy` | `思源宋体 CN Heavy.ttf`、`思源宋体CNHeavy.otf` |

需要补更多开源字体时（一次性、联网）：

```bash
npm install --prefix /tmp/ppt2web-fonts \
    @fontsource-variable/noto-serif-sc @fontsource-variable/noto-sans-sc \
    @fontsource/carlito @fontsource/arimo @fontsource/monoton
python tools/import_fonts.py --prefix /tmp/ppt2web-fonts   # 导入到 ppt2web/fonts/
```

---

## 使用

在仓库根目录跑（也可以先 `pip install -e .` 之后直接用 `ppt2web` 命令）：

```bash
python -m ppt2web <command>
```

| 命令 | 作用 |
|---|---|
| `python -m ppt2web convert <pptx> -o out/` | 转换成静态网页包 |
| `python -m ppt2web inspect <pptx>` | 结构探针：形状/几何/动画行为/字体/媒体清单 + 风险提示 |
| `python -m ppt2web verify <out/> [--pptx 源.pptx]` | 结构化断言（硬门禁）；带 `--pptx` 会回读源文件做端到端比对 |
| `python -m ppt2web export-pdf <out/> -o deck.pdf` | 用本机 Chrome 打印成逐页对齐的 PDF |
| `python -m ppt2web visual-diff <out/> --pptx 源.pptx` | 像素级视觉比对（探索工具，不做门禁） |

拿不准一个 PPT 能不能转、难度多大，**先跑 `inspect`**。

### 典型流程

```bash
# 1. 先摸清这份 PPT 里有什么、有没有坑
python -m ppt2web inspect 某文件.pptx

# 2. 转换
python -m ppt2web convert 某文件.pptx -o out/

# 3. 打开 out/index.html 放映（或丢到任意静态托管）

# 4. 跑硬门禁：有断言失败就不算转完
python -m ppt2web verify out/ --pptx 某文件.pptx

# 5. 目视比对：版式漂移是机器判不了的部分
node tools/shoot.js --deck out/ --slides 002 --anim --freeze 250 --out /tmp/shots
```

### `convert` 常用开关

| 开关 | 作用 |
|---|---|
| `--text vector\|html` | 文字渲染方式。`vector`（默认）= 字形轮廓，不依赖字体、版式自算；`html` = 保留 HTML 文字，可选中但依赖内嵌字体 |
| `--wipe-direction motion\|side` | 擦除动画的方向约定（OOXML 没说死，两种都实现了） |
| `--mirror-text` | 翻转（`flipH`/`flipV`）的形状，文字也跟着镜像。默认**不**镜像 |
| `--pdf FILE` | 转换完顺手导一份 PDF |
| `-q` | 安静模式 |

### 放映快捷键

`←` `→` 翻页 · `空格` 推进动画 · `Home` `End` 首末页 · `F` 全屏 · `O` 显示/隐藏控件栏

### 产物结构

```
out/
  index.html          播放器外壳（等比缩放、控件栏、键盘快捷键）
  runtime.js          播放器逻辑
  slide.js            动画引擎（行为树 → Web Animations API）
  manifest.json       全局信息 + 每页索引 + 媒体哈希 + 字体清单
  print.html          逐页打印视图（PDF 导出用）
  report.html         效果覆盖报告：逐条动画标注 native / approx / dropped
  slides/001.html…    每页一个（天然懒加载、单页可分享）
  assets/
    ppt2web.css       共享样式 + 内嵌字体的 @font-face（仅 HTML 文字模式）
    image1.png…       位图（原样字节）
    fonts/*.woff2     按实际用到的字符子集化的字体（仅 HTML 文字模式）
```

---

## 验收

```bash
python -m ppt2web verify out/ --pptx 某文件.pptx
```

断言分三层：

- **① 结构级** —— 媒体字节 SHA-256 一致、**源里引用到的媒体一个都不能少**、
  每页图元数一致、动画组数/行为数一致且目标不断链、
  **文字逐字符对齐**（含表格单元格和图表的系列名/类别名）、
  图表/表格不许留占位框、字体要么内嵌要么在回落清单、
  动效滤镜都在运行时实现了、产物里不能出现非法的 SVG paint
- **② 几何级** —— 每个图元的尺寸和**绝对位置**（分组变换复合后）要和源一致；
  自动调整大小的文本框**断行数**要和原稿一致
- **③ 像素级** —— `visual-diff` 是**探索工具，不做门禁**：它把
  "LibreOffice 已知会渲错"的页标出来，只提示那些**没有已知差异能解释**的页面

版式漂移多少、行高像不像，最终还是要**目视**：转换完用浏览器打开，和原稿人工比一遍。

> 页面转场和音频**已实现**（3D 转场是近似实现）。此前它们是**静默丢失**的 ——
> `verify` 报"全部通过"，但 report 里连一条提示都没有。现在丢失 = 硬失败。

---

## 开发

```bash
# 单元测试（标准库 unittest，零额外依赖）
python -m unittest discover -s tests -t .

# 抓动画中间帧（定格在指定毫秒，截图可复现），用来和原稿目视比对
node tools/shoot.js --deck out/ --slides 002 --anim --freeze 250 --out /tmp/shots

# 前端冒烟测试（Lightpanda 无头浏览器，验证 DOM/JS/资源加载）
# 见 browser-test/SKILL.md
```

设计文档：

- [`docs/plans/2026-11-15-ppt2web-plan.md`](./docs/plans/2026-11-15-ppt2web-plan.md) —— 总体设计与 12 轮决策台账
- [`docs/plans/2026-11-16-ppt2web-phase1.md`](./docs/plans/2026-11-16-ppt2web-phase1.md) —— 阶段 1：文字矢量化与保真补齐

## 已知限制

- **SmartArt**（`a:graphicData` 的 diagram）仍只渲染占位框
- 图表只支持**柱状图 / 甜甜圈 / 饼图**；折线、散点、面积、堆积、双坐标轴、图例、标题会明确降级成占位框（并在 `report.html` 注明原因），而不是画个"像但不对"的图
- 表格的**合并单元格**暂不支持
- 音频（`p:audio` / mediacall 触发）暂未支持
- Wingdings 等符号字体会退化成普通字符
- 不支持 `.ppt`（2007 前二进制）与 `.odp`（需要 LibreOffice）

## 仓库结构

```
ppt2web/          转换器本体（parse 解析 OOXML → render 渲染 → runtime 播放器）
  fonts/          内置开源字体 + fonts/local/（自放商用字体）
  runtime/        播放器 JS（runtime.js / slide.js）
tests/            单元测试（标准库 unittest）
tools/            import_fonts.py（字体导入）、shoot.js（抓图）
browser-test/     Lightpanda 无头浏览器冒烟测试 skill
docs/plans/       设计文档
out/ out_v2/      转换产物示例（已被 .gitignore 排除）
```
