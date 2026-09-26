# 论文工作区

本目录保存论文大纲、章节草稿、版本快照和已编译论文。正文中的数字、图表和结论只能来自 `results/` 与 `figures/` 的已核对产物；模型代码与原始输入仍保留在仓库根目录对应位置。

- `outline/`：论文结构和主张—证据映射；
- `draft/`：章节草稿和项目说明副本；
- `checkpoints/`：可回滚的稳定版本；
- `references/`：经核验的参考文献记录；
- `Q1_Paper-LaTeX/`：模拟合并论文的 Q1 正文片段、模板封面、图表和构建清单；
- `Q1_Paper.pdf`：当前阶段编译稿（页数以最新构建为准）。

## Q1 模拟论文

这是一份模拟合并论文中的 Q1 正文部分，不是正式参赛稿。为完整模拟所给模板，封面保留华为杯赛事名称和徽标，学校、队号及队员信息栏保留空白，不代表真实参赛身份。论文摘要、关键词、总引言、总结论尚未撰写，待 Q2–Q4 正文并入后统一完成。源模板来自根目录 `HuaweiCup23_LaTeX_Template/`，仅在项目副本中调整；原模板保持不变。能耗方程属于题目未明确时采用的条件性建模口径，所有依赖该口径的结论均在论文中披露。

主要文件：

- LaTeX 正文：[`Q1_Paper-LaTeX/HuaweiCup23_LaTeX_Template.tex`](Q1_Paper-LaTeX/HuaweiCup23_LaTeX_Template.tex)
- 编译稿：[`Q1_Paper.pdf`](Q1_Paper.pdf)
- 构建哈希清单：[`Q1_Paper.build.json`](Q1_Paper.build.json)

可在仓库根目录使用 `uv` 重建 Q1 结果；论文 PDF 使用数学建模 LaTeX 工具与 XeLaTeX 编译。当前 PDF 是阶段稿，完整论文级摘要/章节覆盖检查应在其余子题和总论部分合并后执行。
