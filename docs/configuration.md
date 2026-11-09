# 配置手册

协议唯一维护源是 `src/figdraw/specs/__init__.py`，导出的 `schemas/figure.schema.json` 用于编辑器补全。未知字段拒绝，YAML 重复键拒绝；跨记录/图引用约束由运行时补充检查。

## 项目系列映射

```yaml
# styles.yaml
series:
  method_a: {color: '#3B6FB6', label: Method A, marker: o, linestyle: '-'}
  method_b: {color: '#D68942', label: Method B, marker: s, linestyle: '--', hatch: '//'}
```

图实例设置 `project_style: styles.yaml`。映射按稳定 ID 查找，完全独立于当前记录顺序。内置主题中的 baseline/proposed 等仅为预设，不应将实验方法身份隐式改写成这些 ID。

## 自定义主题

复制 `src/figdraw/presets/paper@1.0.0.yaml`，将 id 改为 `my-paper@1.0.0`，在图实例中设置：

```yaml
theme: my-paper@1.0.0
theme_file: themes/my-paper.yaml
```

主题字段包括 typography（family、size_pt、title_pt、math_font）、background、foreground、grid_color、node_fill、group_fill、control_color、line_pt、data_line_pt、padding_pt、radius_pt、continuous、diverging、series。字号下限 6 pt。数学字体使用 Matplotlib 已支持的 fontset。

中文示例：系统安装 `Noto Sans CJK SC` 后设置 `typography.family: Noto Sans CJK SC`。字体不存在或缺字时拒绝输出。统计图可写 `$x^2$` 等 mathtext；结构图不解析 LaTeX。

## 自定义模板

```yaml
# templates/wide-bar.yaml
id: bar.wide@1.0.0
kind: bar
variant: grouped
max_categories: 24
max_series: 8
group_width: 0.8
defaults:
  orientation: horizontal
  label_rotation: 0
  legend_location: lower right
```

图实例 `template: bar.wide@1.0.0`、`template_file: templates/wide-bar.yaml`。模板默认值只合并到公开 options；图实例显式值优先。扩大容量不会自动扩大画布或缩小字体。新增布局算法需扩展代码，不能通过不受控后端参数绕过模型。

## 数据约定

类别缺省顺序是首次出现顺序；显式 `order` 必须恰好包含观察到的 ID，不自动筛选。CSV 中类别字符串（如 `001`）保持字符串。数值转换接受有限十进制值，拒绝布尔值、NaN、Infinity。

| 图种 | 唯一键 | 缺失行为 |
| --- | --- | --- |
| bar | x × series | 必须完整；缺组合报错 |
| line | x × series | 默认报错；`missing: gap` 对显式 null/空值断线 |
| heatmap | row × column | 默认报错；`missing: mask` 允许缺格/空值，显示遮罩与破折号 |
| pie | category | 非负且总量 > 0；normalize=false 要求总量为 1 |

折线缺少一整条记录无法推断“这里应有一个点”；要断线，显式写入该 x 的 null 值。`sort_x: true` 是排序的唯一自动开关。热力图必须指定 vmin/vmax，超出色域的值拒绝输出；center 必须位于其内部。

误差条 lower/upper 为绝对端点。CI 的 confidence 在 (0,1)，sample_size > 0，method 非空。这些字段记录统计含义，figdraw 不计算或核实区间估计方法。堆叠柱的区间与负值暂不支持。

## 结构图

节点 component 支持 block、memory、register、mux、dsp、pe、pe_array、controller、accumulator、decision、junction。它们是论文框图符号；不执行电气或 RTL 验证。junction 为显式连接结点，label 必须为空且通过 node 连接。普通线交叉不创建连接。

端口用 `{id, side, direction, width_bits}` 定义，source 引用 output/inout，target 引用 input/inout，两端已指定端口时必须位宽相等。节点/分组/边 ID 全局唯一；端口 ID 在节点内唯一。groups 的 parent 和 nodes 的 group 构成层级。

`layout.mode: template` 当前支持 pipeline：按节点数组顺序的一条链，right/down 方向，无分组，连接端口须朝向相邻节点且对齐。复杂图使用 auto。

fixed 精修流程：

1. auto 生成 `layout.json`，复制到项目的 layouts 目录。
2. 设置 `layout: {mode: fixed, source: layouts/pe.json}`。
3. 只需移动标签时使用 overrides.labels，坐标单位 pt。
4. 调整节点时，完整更新节点、端口、边折点及标签；校验器拒绝脱离端口的路线。
5. 修改拓扑、文本、字体、节点尺寸后重新 auto 布局。

完整输出使用根坐标系，禁止整体缩小以塞进画布。增大 size 或主动选择不同布局方向。当前几何检查覆盖画布边界、端点、正交性；不承诺检测全部标签重叠或人工 fixed 布局中的遮挡，最终论文图仍须视觉检查。

## 可复现与输出管理

输出子目录按稳定 figure id 命名。绘制失败保留上一版；新结果完成后替换上次 manifest 管理的文件。未经 figdraw 管理的同名文件拒绝覆盖。跨多个文件的最终写入不具备文件系统事务语义；不要并发写同一 figure id。

resolved.yaml 包含内嵌数据、具体样式与相对快照引用，可迁移整个输出目录重绘。结构图 resolved 自动使用 fixed 布局，无需再次安装/运行 ELK；PDF/PNG 仍需要 CairoSVG。字体和 Python 依赖不嵌入产物，通过 manifest 与仓库锁文件恢复环境。
