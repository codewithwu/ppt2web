# 阶段 1：文字矢量化与保真补齐

日期：2026-11-16
样本：`6a5a1942aff40.pptx`（24 页，73MB，真实业务稿）

## 为什么做这一轮

原稿转出来的网页包有几处硬伤：

1. **字体不对** —— 全篇用 `思源宋体 CN`（衬线），转换器回落成 Noto Sans（无衬线）
2. **主题字体槽丢失** —— `+mn-ea` / `+mj-lt` 这类 token 没被解析，字体名直接丢了
3. **渐变文字变黑** —— run 级 `a:gradFill` 没读，章节标题该是橙黄渐变却是黑色
4. **矢量媒体被降级** —— 2 个原生 SVG（`asvg:svgBlip`）整个丢失，PowerPoint 靠
   `a:blip r:embed` 指向的位图兜底，位图被当成正式图源
5. **custGeom 退化成矩形** —— `a:custGeom` 早就解析出来了，但渲染层没用
6. **48 条动画是"近似"** —— `p:animEffect`（PowerPoint 的入场效果）被近似成位移
7. **图表/表格是占位框**（7 个图表 + 1 个表格）
8. **第 2 页文字溢出**压住下一行标题（浏览器排版和 PowerPoint 的行高/换行不一样）
9. **verify 对文字零断言** —— 文字全丢也能全绿

## 关键决策

| # | 决策 | 结论 |
|---|---|---|
| 1 | 保真契约 | **结构级**（元素/层级/动效/文字内容/数据全还原）为主，字体允许用度量兼容替代；有原字体时自动升级为字形一致 |
| 2 | 轮廓提取 | **fontTools**（构建期依赖，产物仍然零运行时依赖） |
| 3 | 矢量粒度 | **全量转路径**为默认，保留 `--text html` 逃生开关；DOM 里另留一层不可见的真实文本（可选中/可搜索/读屏器可读） |
| 4 | 节奏 | 分三阶段：阶段 1 = 本文档；阶段 2 = 图表 + 表格；阶段 3 = 音频 + 视觉回归基线 |
| 5 | 字体来源 | OFL 字体进项目（`ppt2web/fonts/`），商用字体走 `ppt2web/fonts/local/` 用户自放，自动优先用真身 |
| 6 | 验收 | **结构级硬断言**为门禁（`verify --pptx` 回读源文件逐字符比对）+ 人工目视 |
| 7 | 产物形态 | 多文件为主 + `--single` 可选单文件导出（阶段 2 实现） |
| 8 | 测试 | 标准库 `unittest`（零新依赖）+ verify 门禁 + 黄金样本回归 |

## 查清的事实（决定了方案）

- **动画目标只有形状级**：`parse/animation.py` 只读 `p:tgtEl/p:spTgt/@spid`，
  `p:txEl`（按段落/run 动画）在解析层就被丢掉；运行时只认
  `[data-shape-id] .anim`。所以**文字换 SVG 不会断动画链** —— `.anim` 容器还在，
  WAAPI 照常作用。
- **入场效果可以做到原生**：全稿 48 条 `animEffect` 只用了 7 种滤镜
  （`wipe(left)`×24、`wipe(down)`×9、`fade`×8、`randombar(horizontal)`×3、
  `circle(in)`×2、`dissolve`×1、`barn(inVertical)`×1），全部能用 `clip-path`/`opacity` 表达。
  → native 64 → 108，approx 48 → 4。
- **字体解析的真实结构**：latin / ea 两个槽分开，且 **78 处 run 只有 latin 没有 ea**
  （中文实际走 latin 通道）；形状级 `a:lstStyle` 里的默认字体（`微软雅黑`、
  `思源黑体 CN`、`Monoton`）也必须参与继承。
- **没有符号字体坑**：全稿无 Wingdings / emoji / 私用区字符。
- **媒体**：13 个文件（6 jpg + 4 png + 2 svg + 1 mp3），无 EMF/WMF；音频在第 1 页。

## 实现要点

### 字体名解析（`ppt2web/fontmap.py`）
把 PPT 的 typeface 拆成「族 + 字重」：`思源宋体 CN Heavy` → 族 `思源宋体 CN`、字重 900；
`阿里巴巴普惠体 2.0 45 Light` → 族 `阿里巴巴普惠体`、字重 300。
再映射到替代规格（思源宋体 CN ≡ Noto Serif SC，Calibri ≡ Carlito …）。

### 主题字体槽（`parse/theme.py` / `parse/deck.py`）
`+mn-ea` 这类 token 按 **token 自身的槽**解析（真实文件里存在
`<a:latin typeface="+mj-ea"/>` 这种写法）。run / 段落都没指定 ea 时，
沿「形状 lstStyle → 段落 defRPr → 主题 minorFont」继承。

### 矢量文字（`render/glyphs.py` / `render/textlayout.py` / `render/vectortext.py`）
- `glyphs.py`：fontTools 取字形轮廓（SVGPathPen）+ advance width + 变量字体实例化；
  fontsource 的中文可变字体按 unicode-range 切片，所以"某字用哪个分片"靠
  unicode-range 找 —— 和 HTML 模式的子集化是同一套逻辑
- `textlayout.py`：自己排版。断行单元 = 西文按词 + 汉字逐字；贪心填行；
  中文标点禁则（行首收尾标点**悬挂**到上一行，行尾开头标点挪到下一行）；
  行高用字体的 ascent/descent（和 PowerPoint 的行距基准一致）
- `vectortext.py`：一行（一个字体一种颜色）合并成一条 path；另出一层
  `.tx-a11y` 真实文本
- **缺字形时整个形状退回 HTML 文字** —— 宁可丑，不能让文字消失

### 动效滤镜（`runtime/slide.js` / `render/effects.py`）
`p:animEffect` 的 `filter` 属性翻译成 clip-path / opacity。Python 的判定表和
JS 的实现表由单测交叉检查（判定表说 native，运行时没实现 → 测试红）。

擦除方向有歧义（OOXML 没说死，`filter` 与 `presetSubtype` 在真实文件里还会互相
矛盾），两种读法都实现，用 `--wipe-direction motion|side` 切换。

### 验收（`verify.py`）
新增：文字逐字符比对（回读源 PPT）、字体覆盖检查、滤镜实现交叉检查、
占位元素统计。

## 遗留

- 擦除方向需要人工在 PowerPoint 里目视确认一次（两种约定都实现了）
- `演示夏行楷` 无开源等价物，用真身或接受替代
- 图表 / 表格 / 音频属于阶段 2、3
