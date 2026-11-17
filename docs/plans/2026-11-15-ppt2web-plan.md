# ppt2web —— PPTX 转自包含网页播放方案

> 状态：已与需求方逐轮对齐（12 轮决策全部落定）。分支 `feature/ppt-conversion`。
> 样本：`样本.pptx`（1ppt.com 模板，2 页，PowerPoint 2010 制作）。

## 1. 目标

把 `.pptx` 转成一个**自包含的静态网页包**，在浏览器里像 PowerPoint 放映一样播放。

三条硬指标：

1. **图片无损** —— 嵌入位图**字节级原样引用**，绝不重编码
2. **内容不丢** —— 文本、表格、图形、图片、图表全部还原
3. **动画保留** —— 效果、时机、对象、方向、时长、顺序正确（效果类型允许近似）

## 2. 非目标

- 不做网页端编辑（只读放映）
- 不支持 `.ppt`（2007 前二进制）与 `.odp` —— 需要 LibreOffice，本机无免密 sudo
- 不做 Morph 转场、3D 模型、OLE 对象保真（降级处理并标注）
- 不做响应式重排（重排会破坏版式一致，只做等比缩放）

## 3. 决策台账

| # | 决策 | 结论 |
|---|---|---|
| 1 | 路线 | 网页重建（HTML+CSS+SVG）+ JSON 时间轴 runtime；位图字节级原样引用 |
| 2 | 动画精度 | **L2**：静态按 L1 还原；动画时机/对象/方向/时长/顺序全对，效果类型允许近似 |
| 3 | 投放 | 部署无关的自包含包；**零网络依赖**（字体/脚本全内嵌）；固定舞台坐标系 + 等比缩放；不重排 |
| 4 | 字体 | pptx 内嵌字体优先 → 否则度量兼容替代 + `size-adjust`/`ascent-override` 补偿；`font-map.json` 可覆盖；`--font-dir` 可升级为真字体；**L1 = 版式一致，字形允许不同**。字体文件来源见 §4.1 |
| 5 | 转换位置 | 离线 CLI（Python：`python-pptx` + `lxml` + `fontTools`/`brotli`）；runtime 纯静态 JS，与解析器分层 |
| 6 | 元素范围 | Tier1 全保 + Tier2 全做 + Tier3 保底降级 |
| 7 | 播放交互 | 点击推进 + 自动演示开关 + 键盘快捷键；**自动链（withEffect）为一等公民**；转场计入 L2；演讲者模式后置 |
| 8 | 输入输出 | 输入 `.pptx`（主线）+ `.pdf`（副线，后置，pdf.js→canvas）；输出附 `@media print` + `--pdf` 导出 |
| 9 | 动画实现 | **行为树解释器**（非预设库），presetID 仅用于语义命名与覆盖判定 |
| 10 | 规模 | ≤200 页 / 输入 ≤100MB / 静态站点首屏 ≤2s；媒体原样复制按需加载 |
| 11 | 验收 | 三层：结构化自动断言（硬门禁）+ 视觉回归（人工建基线）+ `report.html` 覆盖报告 |
| 12 | 环境 | 现代 Chrome/Edge/Safari/Firefox + iOS Safari；项目落在 `ppt2web/` |

## 4. 样本分析结论（`样本.pptx`）

| 项 | 实测 | 对方案的影响 |
|---|---|---|
| 页数/尺寸 | 2 页，12192000×6858000 EMU（16:9） | 与决策 3 假设一致 |
| 继承链 | 22 layouts / 4 masters / 3 themes | 必须实现 slide→layout→master→theme 属性合并 |
| 图形 | slide1：30 组 `grpSp`，共 60 个 ellipse（`noFill` + `accent1` 主题色） | 分组/无填充/主题色三条路径都要走通 |
| 图片 | 3 个 PNG（image1-3.png，共 39KB） | 位图原样引用路径可验证（SHA-256 比对） |
| 文本 | slide2：86 个文本 run；**微软雅黑 ×185**、Arial ×1、**Wingdings ×6** | 字体替代主战场；Wingdings 符号需降级 |
| 主题字体 | theme1 = **等线 Light**，theme2/3 = **Calibri** | 三个 Microsoft 字体本机全无 → 必须替代 |
| 动画行为 | 30 个对象：可见性 `p:set` + 宽 `ppt_w` + 高 `ppt_h` + **旋转 `r`** | 行为树解释器的目标用例 |
| 动画预设 | `presetID=23 entr ×45`、`23 exit ×45`、`8 emph ×30` | presetID 仅作语义命名 |
| **触发模型** | `withEffect ×120`，`clickEffect`/`afterEffect` **= 0** | **动画进页自动播**（delay 0→3700ms，dur 500ms）；自动链必须一等公民 |
| 转场 | `<p:transition spd="slow" p14:dur="2000"/>`（无类型子元素） | 无视觉转场，仅时长；仍需支持带类型的转场 |
| 杂项 | 78 个 `ppt/tags/tagN.xml` = `NORDRI TOOLS WATERMARK`（稻壳水印标记） | 解析器须显式忽略未知 rels 类型，否则误判"内容丢失" |
| 自动缩放 | 样本中无 `normAutofit`/`spAutoFit`/`noAutofit` | 通用实现仍须支持 |
| 外链 | slide2 有 10+ 个指向 1ppt.com 的外部超链接 | 默认**保留**（不篡改用户内容）；净化为可选 `--sanitize`（后置） |

**样本未覆盖**：图表、SmartArt、表格、公式、嵌入媒体、3D、内嵌字体 → Tier2 的图表/SmartArt 需第二份样本校准，否则为盲写（对策见 §8 探针工具）。

### 4.1 字体来源与子集化方案（探针实测后确定）

本机字体库存实测（`fc-list`）：**只有** Noto Sans/Serif CJK（SC/TC/HK/JP/KR，CFF 轮廓 `.ttc`）、文泉驿微米黑/正黑（TrueType `glyf`）、DejaVu、Lato、Ubuntu。
**没有** Carlito / Arimo / Liberation / Tinos / Calibri / Arial / 微软雅黑 / 等线 / 宋体 / Wingdings —— 样本用到的 `微软雅黑`、`等线 Light`、`Calibri`、`Wingdings` 全部缺失。
`fc-match` 对所有 Office 字体名都回落到 **DejaVu**（无汉字覆盖），所以 CJK 只能靠浏览器的字形级 fallback 兜住。

**结论：字体必须从外部取。** 可行渠道（按可靠性排序）：

| 渠道 | 结果 | 用途 |
|---|---|---|
| **npm fontsource**（npmmirror，最快最稳，0.4–5.9s 拉完） | `@fontsource/carlito` 1.4MB（Calibri 度量兼容）、`@fontsource/arimo` 2.3MB（Arial 度量兼容）、`@fontsource/noto-sans-sc` 73MB、`@fontsource-variable/noto-sans-sc` **仅 4.6MB** | 主渠道 |
| `fonts.googleapis.com/css2` + `fonts.gstatic.com` | 需带**浏览器 UA** 才返回 woff2 分片 URL（默认 curl UA 返回整份 ttf）；gstatic 下载正常 | 备选 |
| `github.com` / `raw.githubusercontent.com` | **间歇性超时**（5 次里 2–3 次失败）；`api.github.com` 与 `codeload.github.com` 100% 可用 | 仅用于取元数据 |
| `google/fonts` 仓库 tarball | **1.67GB**，不实用 | 排除 |
| 本机 Noto CJK `.ttc` | CFF 轮廓、ttc 集合，需要 fontTools 才能子集化 | 兜底 |

**关键红利：fontsource 的 CJK 包已经按 unicode-range 切成 ~100 个分片**
（`noto-sans-sc-4-normal.woff2` … `-119-`，单个 12KB–370KB）。
我们只要**扫描产物里实际用到的字符 → 反查落在哪些分片 → 只把这几个 woff2 拷进产物**，
就得到了精确子集化，**完全不需要 fontTools/brotli/hb-subset**（本机一个都没有）。
Latin 字体同理（`carlito-latin-400-normal.woff2` 仅 30KB）。

配套：
- 每个 `@font-face` 带 `unicode-range`，浏览器只下载用到的分片
- 度量补偿用 CSS `size-adjust` / `ascent-override` / `descent-override` / `line-gap-override`
- 产物内嵌字体（不引 CDN，保持零网络依赖）
- 构建期需要网络（或本地缓存 `~/.cache/ppt2web/fonts/`）

## 5. 架构

```
pptx (zip)
  │
  ├─ ppt2web/parse/     python-pptx + lxml → 中间模型
  │    slide.py  shape.py  text.py  theme.py  animation.py  media.py
  │
  ├─ ppt2web/render/    中间模型 → 静态站点
  │    html.py  css.py  svg.py  fonts.py  manifest.py  report.py
  │
  └─ ppt2web/inspect/   结构探针（任意 pptx 打印清单）
```

产物形态：

```
out/
  index.html          播放器外壳
  runtime.js          纯静态 JS，无依赖、无构建
  manifest.json       全局信息 + 每页动画时间轴索引
  slides/001.html…    每页一个（天然懒加载、单页可分享）
  assets/             位图(原样字节) / 字体(WOFF2 子集) / 媒体
  report.html         效果覆盖报告
```

数据流：pptx → 中间模型（每个 shape 一个节点，含继承后的最终属性）→ 每页独立 HTML + 每页动画 timeline（内联在 manifest.json）→ runtime 读 manifest 驱动 WAAPI。

## 6. 关键数据结构

### manifest.json

```jsonc
{
  "slideSize": { "cx": 12192000, "cy": 6858000 },   // EMU
  "slides": [
    {
      "index": 1,
      "file": "slides/001.html",
      "transition": { "type": null, "durationMs": 2000 },
      "timeline": { /* 见下 */ }
    }
  ],
  "fonts": [ { "family": "微软雅黑", "file": "assets/fonts/msyh.woff2", "unicodeRange": "U+4E00-9FFF" } ],
  "media": [ { "src": "assets/image1.png", "sha256": "…", "bytes": 31689 } ]
}
```

### 动画 timeline（每页）

```jsonc
{
  "groups": [                       // 一个 group = 一次点击（或进页自动链）推进的单元
    {
      "trigger": "auto" | "click",
      "startDelayMs": 0,
      "behaviors": [
        {
          "target": "shape-42",
          "type": "anim" | "animRot" | "animScale" | "animClr" | "animMotion" | "set",
          "attrName": "ppt_w",
          "durationMs": 500,
          "keyframes": [ { "t": 0, "v": 0 }, { "t": 1, "v": 1 } ]
        }
      ]
    }
  ]
}
```

`trigger` 的判定来自 `p:cTn/@nodeType`：`withEffect`/`afterEffect` 并入当前组的自动链，`clickEffect`/`clickPar` 开启新组，`interactiveSeq` 标记为交互式触发。

## 7. 动画：行为树解释器

**为什么不用预设库**：PowerPoint 已把动画写成完整的行为描述（`attrName` + `tavLst` 关键帧）。直接翻译成 WAAPI keyframes 比"实现预设再近似"更准，且**通用**——任何预设自动覆盖。

映射表：

| OOXML | WAAPI / CSS |
|---|---|
| `p:anim` attrName `ppt_x/ppt_y/ppt_w/ppt_h` | `transform: translate()/scale()` |
| `p:anim` attrName `r` / `p:animRot` | `transform: rotate()` |
| `p:anim` attrName `style.opacity` | `opacity` |
| `p:anim` attrName `style.visibility` / `p:set` | `visibility` + 起始态 |
| `p:animScale` | `scale()` |
| `p:animClr` | `fill` / `stroke` 颜色插值 |
| `p:animMotion` | `offset-path`（CSS）或 SVG `animateMotion` |
| `p:animEffect`（擦除等） | `clip-path` / `mask` 近似 |

覆盖报告判定（逐动画）：

- `native` —— 行为被完整表达，参数（方向/时长/延迟/缓动）与 PPT 一致
- `approx` —— 有降级维度（如"擦除条纹数未还原"）
- `dropped` —— 无法表达且近似也做不了 → 元素在动画开始前直接呈现（**绝不静默消失**）

## 8. 工具

| 命令 | 作用 |
|---|---|
| `ppt2web convert deck.pptx -o out/` | 主转换 |
| `ppt2web inspect deck.pptx` | **结构探针**：打印所有形状类型/预设/动画行为/字体/媒体清单 + 覆盖风险评估。拿到新 PPT 先探一遍再估工期 |
| `ppt2web verify out/` | 跑第 1 层结构化断言（硬门禁） |
| `ppt2web export-pdf out/ -o deck.pdf` | Chrome headless 打印（对应 `--pdf`） |

## 9. 里程碑与验收

| 里程碑 | 内容 | 验收 |
|---|---|---|
| **M0 骨架** | pptx→DOM→静态站点；manifest + runtime + 翻页 + 等比缩放 + 打印样式；inspect 工具 | 样本 2 页能翻、能缩放、能打印 |
| **M1 Tier1** | 文本（多段落/项目符号/上下标/自动缩放）、形状（prstGeom+custGeom→SVG）、渐变/图案填充、位图、表格、主题色/字体、母版继承、超链接 | 样本 slide1/slide2 与原 PPT 目视一致；位图 SHA-256 一致；断言全绿 |
| **M2 动画** | 行为树解释器、触发模型（自动链+点击组）、转场、WAAPI 播放 | 30 个对象的时序/对象/方向正确；覆盖报告无 `dropped` |
| **M3 图表** | 图表、SmartArt、阴影/发光、组合 | 需第二份样本校准 |
| **M4 验收** | 结构化断言固化为门禁、视觉回归基线、`report.html` | CI 可跑；基线 diff 可用 |
| **M5 收尾** | PDF 副线（pdf.js→canvas）、`--pdf` 导出、Tier3 降级完善 | PDF 输入可播；打印 PDF 逐页对齐 |

## 10. 三层验收

1. **结构化自动断言**（每次转换必跑，不过即失败）
   - 每个媒体 part 的 SHA-256 与产物一致 → 证明"图片无损"
   - 每个 shape/表格/图表在产物 DOM 有对应节点，数量类型逐一对应 → 证明"内容不丢"
   - timeline 条目数 == pptx 动画节点数 → 证明"动画不丢"
   - 所有元素在 slide 边界内；文本框无溢出
   - 每个 `@font-face` 的 `unicode-range` 覆盖实际用到的字符
2. **视觉回归**：Chrome headless 渲染每页截图 → 与 `baseline/` 人工确认基线做像素 diff；动画在时间轴关键点 seek 截图同样比对。**基线由人工建立**（无参考渲染器，本机无 PowerPoint/LibreOffice）
3. **覆盖报告** `report.html`：逐页逐动画列 `native/approx/dropped`，人工抽查

## 11. 风险台账

| 风险 | 影响 | 缓解 |
|---|---|---|
| 换行算法与 PowerPoint 不一致 | L1 版式偏差（最大残余风险） | 浏览器断行 + 运行时测量校正；必要时对关键文本转 SVG 轮廓 |
| 无参考渲染器 | 无法自动逐像素比对 | 人工建基线（第 2 层验收） |
| 字体度量差异 | 换行/溢出错位 | `size-adjust`/`ascent-override` 度量补偿；`font-map.json` 可指定 |
| 样本未覆盖图表/SmartArt | M3 盲写 | `inspect` 探针 + 补充样本 |
| 商业字体不可得 | 字形无法与原版一致 | 已接受"版式一致、字形不同"为 L1 标准 |
| 嵌入媒体体积 | 自包含产物体积下限 = 源媒体体积 | 原样复制 + 按需加载；产物打印体积构成 |
| 78 个 tags 部件等未知 rels | 误判内容丢失 | 解析器显式忽略未知类型 |

## 12. 待补输入

- **更多样本**：一份真实业务 PPT（含表格/图表/图片）+ 一份含 SmartArt 的（校验 M3）
- **字体渠道确认**：本机无 Calibri / 等线 / 微软雅黑 / Wingdings，替代字体（Carlito、Noto Sans CJK 等）的获取途径待核实

## 13. 依赖

**零运行时依赖。** 解析层用 Python 标准库直接读 OOXML（`zipfile` + `xml.etree`），
不引入 python-pptx / lxml —— 这个工具要在用户自己的机器上跑，不该逼人先 pip install。

字体文件来自 npm fontsource（构建期一次性，见 §4.1），转换器本身不读字体，只挑选分片。
浏览器侧只用系统 Chrome headless（`~/.cache/hyperframes/chrome/`，已存在）。
无需 sudo、无需 LibreOffice。

> 历史记录：原方案是 `python-pptx` + `lxml` + `fonttools` + `brotli`。
> fontTools/brotli 因 fontsource 的 unicode-range 分片方案而不再需要；
> python-pptx/lxml 因改用标准库实现 OOXML 读取而不再需要。

## 14. 实现记录

### 14.1 已完成（M0 + M1 主体）

| 能力 | 状态 |
|---|---|
| 零依赖 OOXML 解析（zip + rels + 继承链） | ✅ |
| 分组**嵌套** DOM（动画可以以"组"为目标） | ✅ |
| 形状几何（prstGeom 常用集 → SVG） | ✅ 常用集，未覆盖的退化为矩形并在报告标注 |
| 渐变/纯色/无填充、描边 | ✅ |
| 文本（段落/项目符号/字号/颜色/对齐/行距/上下标） | ✅ |
| 图片（字节级原样引用 + srcRect 裁剪） | ✅ |
| 主题色槽解析 + tint/shade/lumMod | ✅ |
| 动画行为树 → WAAPI（含点击组 + 自动链两种触发） | ✅ |
| 字体按字符子集化（fontsource 分片） | ✅ 101 分片 → 11 分片 |
| 结构化断言（媒体哈希/图元数/动画目标不断链） | ✅ |
| 播放器（缩放/控件栏/键盘/全屏/翻页） | ✅ |
| 打印视图 + Chrome 导出 PDF | ✅ |
| 覆盖报告 report.html | ✅ |

样本验证：`样本.pptx`（2 页）转换后 97 个图元全部有 DOM 节点、
3 个 PNG 字节级一致、300 条动画行为全部还原，动画实测播放正常。

### 14.2 实现中踩到的 OOXML 坑（重要）

1. **`p:childTnLst` 在 `p:cTn` 里面**，不在 `p:par`/`p:seq` 的直接子级。
   动画树层级是 `tnLst > par > cTn > childTnLst > seq > childTnLst > par > ...`
2. **`p:set` 的值在 `<p:to>` 里**（不是 `tavLst`）。`p:anim` 才用 `tavLst`。
3. **符号值 `"#ppt_w"` / `"ppt_w"`** 表示"该属性的当前值"：
   尺寸类（ppt_w/ppt_h）= 满尺寸 = 1，位移类（ppt_x/ppt_y）= 0。
   进出动画就是靠这个表达的（进：0→满宽；出：满宽→0）。
4. **动画可以以"组"为���标**（`p:spTgt spid="<grpSp 的 id>"`）。
   把分组展平会让动画目标凭空消失 → 必须保留嵌套 DOM。
5. **组的子坐标空间**：`chOff`/`chExt` 定义子坐标系原点与范围，
   `off`/`ext` 定义组在父系里的位置，两者之间是缩放映射。
   渲染时组的 div 用 `chExt` 尺寸、变换用 `off + (child - chOff) * ext/chExt`。
6. **形状的自身 xfrm**：旋转/翻转绕**自身中心**，所以矩阵最后要平移的是"半尺寸"，
   不是中心点（减中心点会把位置偏移抵消掉，表现为所有元素堆在左上角）。
7. CSS `matrix()` 的平移量单位是 px，而 OOXML 是 EMU → 平移量要除以 9525。
8. `p:transition` 可能是 `<p:transition spd="slow" p14:dur="2000"/>`（无类型子元素 = 无视觉转场，只有时长）。

### 14.3 下一步（M1 收尾 → M2）

- [ ] 表格（`a:tbl`）渲染
- [ ] 全部预设几何（当前约 30 种，目标 ~190 种）
- [ ] 阴影/外发光/柔光
- [ ] 组合对象的合并几何
- [ ] 视觉回归基线（人工确认后入库，之后自动像素 diff）
- [ ] 换行一致性校正（运行时测量溢出）
- [ ] 符号字体（Wingdings → Unicode 映射表）
- [ ] `ppt2web convert --pdf` 已可用；PDF 输入副线排在 M5
