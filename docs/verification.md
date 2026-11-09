# v0.1.0 验证记录

验证环境：Linux / Python 3.12.14 / Node 24.22.1；Python 依赖以 uv.lock 为准，ELK 固定 0.12.1。GitHub Actions 配置覆盖 Python 3.11 / 3.12 与 Node 22；远端执行结果以 Actions 页面为准。

本地已完成：

- 50 项 pytest 检查通过：输入约束、相对路径、样式稳定、区间含义、缺失策略、图引用/端口位宽、模板覆盖、几何端点与批量错误报告。
- 10 张示例各输出 PDF / SVG / PNG；检查 PNG 像素、SVG 宽度、PDF MediaBox；输出保持声明的物理尺寸。
- 六类统计图案例的 portable resolved 配置重绘，SVG 字节一致；结构图 fixed 快照禁用 Node 后重绘，SVG 字节一致。
- 实测 ELK 跨分组和嵌套分组、固定端口侧、循环与分支路由；决策节点端点投影到真实菱形边界。
- 缺失/零值区分、未知系列 ID、无效区间、重复数据、超出画布、长标签重叠、过期 fixed 布局均有失败用例。
- 失败渲染保留旧输出；未受 manifest 管理的同名文件拒绝覆盖。
- Ruff 检查与格式检查通过；sdist / wheel 构建通过。
- 将 wheel 安装到独立虚拟环境，在源码目录之外生成柱状图和 ELK 架构图；确认主题、init 样例、worker 及 Node 锁文件随包发布。

代表图见 [样例画廊](gallery/overview.svg)。它是文档缩略图集合，不是论文拼版接口。更新方式：

```bash
uv run figdraw build examples/paper.yaml
uv run python tools/generate_gallery.py
```

已知边界：本环境没有中文字体，中文渲染需用户安装指定字体后验证；缺字会明确报错。文本重叠自动检查主要覆盖坐标轴刻度和画布边界，复杂结构图仍需视觉检查。输入数据的统计正确性由实验流程保证；本工具验证格式、数值和显式语义。
