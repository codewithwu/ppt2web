# 阶段 2：保真补齐 —— 让 `verify` 说真话

日期：2026-11-17
样本：`test.pptx`（24 页 / 13 个媒体 / 4 种字体 / 43 组动画）

## 为什么做这一轮

`ppt2web verify out/ --pptx test.pptx` 报的是**"✓ 结构化断言全部通过"**。

但拿 LibreOffice 渲原稿、逐页和产物做像素比对，差异大得离谱：封面页
95% 的像素对不上、橙色徽章在产物里是**黑色**、第 9/17/21 页的 5 张大图
**整个不见了**、第 1 页的背景音**丢了**、24 个页面转场**一个都没播**。

也就是说：**verify 全绿，但产物明显是坏的**。门禁在骗人。

## 查清的事实

### 真正的 bug（12 条）

| # | 问题 | 根因 | 影响 |
|---|---|---|---|
| 1 | 渐变填充的形状全变黑 | `render/html.py` 把 CSS 渐变串写进 SVG 的 `fill` 属性 —— SVG 不认，浏览器忽略 → 回退黑 | 17 页 32 处 |
| 2 | 图片填充的形状整个不渲染 | `<p:sp>` + `a:blipFill` 不是 `<p:pic>`，渲染器只认后者 | 第 9/17/21 页 5 张图（26MB） |
| 3 | 背景音丢失 | 音频**根本没解析** | `media1.mp3`（4.6MB） |
| 4 | verify 对上面 3 条完全隐形 | 只校验"产物里已有的媒体"，从不与源媒体清单比对 | — |
| 5 | 字体/形状普查漏下钻组合 | `deck.py`/`inspect.py` 只遍历 `slide.shapes`，不遍历 `shape.children` | 清单少一款字体（封面标题的「演示夏行楷」） |
| 6 | `onBegin` 自动触发被忽略 | 只取第一个 cond（`delay="indefinite"`） | 43 组**全部**标成点击组 |
| 7 | after-previous 延时算错 | 当成"点击后 N 毫秒"，实际是"上一个效果**结束后**再等 N" | 第 1/24 页淡入提前 500ms |
| 8 | 相对位移被抹平 | `#ppt_y+.1` 落到兜底分支变成 0 | "浮入"效果一动不动 |
| 9 | 报告把 8 判成 native | 判定只看属性名，不看关键帧值 | 误报 |
| 10 | 24 个页面转场全丢且无提示 | 元数据解析了、运行时只改 `iframe.src` | 静默丢失 |
| 11 | `cmd` 动画（mediacall）dropped | 运行时没有 cmd 分支 | 音频不播 |
| 12 | HTML 模式真身字体白嵌 | `@font-face` 用文件名、CSS 引用用替代族名，两边对不上 | 「演示夏行楷」在 HTML 模式下根本没生效 |

外加两条**归因更正**（一开始以为是 ppt2web 的错，查清后是 LibreOffice 的错）：

- 封面标题：源文件**显式**写了 `a:latin/a:ea typeface="演示夏行楷"`，
  产物用行楷是**对的**；LibreOffice 是因为本机没装这款字体才替换成黑体
- 图表类别名：源文件里 `c:cat` **根本不存在**，类别名只在 `c15` 扩展和内嵌
  xlsx 里；产物读 `c15` 是**对的**，LibreOffice 不支持 `c15` 才显示成 1,2,3,4

### 一个"看起来像 bug 其实不是"的

源文件里 `spAutoFit` 文本框的框高一律是 **~1.212×字号**（作者软件的行高模型），
而 PowerPoint / LibreOffice / 我们都用**字体度量**（思源宋体 → Noto Serif SC
是 1.437em）。实测 LibreOffice 的行距和产物一致、**都**和源里存的框高对不上。

所以那是**模型差异**，不是 bug —— 行高不该拿来当基准。
但**行数**可以：行高差 1% 的话"框高 ÷ (1.2×字号)"四舍五入仍还原得出行数，
而行数不一样 = 断行点变了，那才是字体替代真正带来的漂移。

## 关键决策

1. **验收分三层**：① 结构级（硬）② 几何级（硬）③ 像素级（**探索工具，不做门禁**）
2. **一切丢弃必须显式**：`report.html` 新增转场/音频/几何降级分区，
   `verify` 把"dropped == 0""转场都实现了"变成硬门禁
3. **像素 diff 是探针不是判官**：每页标注"有没有已知差异能解释它"，
   **没有**已知差异、差异又大的页面才是该查的
4. **图片填充按 OOXML 字面语义**：`a:stretch` = 把图拉伸铺到 `a:fillRect`
   指定的矩形（负内缩 = 出血），再由形状轮廓裁掉
5. **3D 转场只做近似**：CSS 3D 还原不了离轴投影，做"推近 + 淡入"并标 approx
6. **音频允许内嵌**：`<audio>` + `cmd="playFrom(...)"` 触发，
   浏览器的自动播放策略拦不住也不该绕
7. **字体替代要分清同源与否**：`same_origin` 必须按**源字体名**记
   ——同一个替代规格既服务同源字体（思源宋体 CN）又服务非同源字体
   （阿里巴巴普惠体 → Noto Sans SC 只是"能显示"）

## 实现要点

```
parse/
  xmlutil.py    _read_blip_fill：fillRect 在 a:stretch **里面**
  shapes.py     _fill_blip_fill / _fill_audio_ref：图片填充 + 形状上的音频
  animation.py  _trigger_of（onBegin）· _collect_effects（afterEffect 的
                after_wait 语义，状态跨递归共享）· _self_value（#ppt_y+.1）
  audio.py      新增：音频/视频素材解析
  deck.py       _bind_media_commands：cmd 行为 ↔ 媒体
render/
  html.py       渐变走 <defs> + url(#id)；图片填充走 <clipPath>
  gradients.py  GradientRegistry 支持径向
  report.py     转场/音频分区 + 机器可读摘要 + 关键帧全等判 approx
  fontplan.py   真身字体的 family 用文件内部名
verify.py       媒体集合比对 / 非法 paint / 转场 / dropped / 几何
verify_layout.py 新增：尺寸 + 绝对位置 + 断行数
visual.py       新增：像素比对（临时 fontconfig + 已知差异白名单）
runtime/
  runtime.js    双 iframe 交叉转场 + advTm 自动翻页
  slide.js      cmd → 播放媒体
```

## 遗留

- **「阿里巴巴普惠体」真身字体还没拿到** —— 58 个文本框的字形与原稿不同
  （断行已核对一致）。放进 `ppt2web/fonts/local/` 即可完全还原，
  同步拷到 `~/.local/share/fonts/` 能让像素基准也自洽
- 3D 页面转场只能近似
- `a:tile`（图片平铺填充）未实现，按拉伸处理
- 浏览器自动播放策略会拦掉无手势的音频播放（绕不过去，也不该绕）
- 图表类型、表格合并单元格、SmartArt 的既有降级不变
