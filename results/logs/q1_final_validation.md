# Q1 最终验证回执

- 日期：2026-09-25（UTC）
- 最终签字状态与回执更新时间：2026-09-25 05:25:24 UTC
- 版本：`q1-exact-subset-pareto-dp-v3.2`
- 输入文档指纹：以 `results/logs/q1_full_report_status.json` 中的当前指纹为准；该指纹绑定 Q1 文档、模型代码、实验入口、原始工作簿、DEM 和依赖锁文件。
- 独立 M1：`PASS WITH CONDITIONS`。条件是将能耗分项公式作为题目未明确时采用的条件性建模口径，并在结果中披露。

## 检查结果

| 检查 | 命令/证据 | 结果 |
|---|---|---|
| 全场景报告 | `uv run --locked python -m src.experiments.q1_full_report --check-only` | exit 0；`all_27_proven`，27/27 已解决，18 个完整可行前沿、9 个已证不可行、无缺失或未证场景 |
| 图表源数据合同 | `uv run --locked python -m src.visualization.q1_full_figures --check-only` | exit 0；80 个货箱、15 个服务区、10 份图表合同 |
| 图表生成 | `uv run --locked python -m src.visualization.q1_full_figures` | exit 0；SVG、PNG 和灰度预览均生成 |
| 复现清单命令 | 对 `results/复现清单.json` 中 `reproduce_command` 执行 PowerShell AST 解析，并实际运行完整命令 | 解析错误 0；实验 checkpoint 匹配并读取，报告和图表阶段 exit 0 |
| 复现清单哈希 | `results/复现清单.json` 的 Q1 文档 SHA-256 与本地文件比较 | 一致；文档字节数一致 |
| 仓库结构 | `scripts/check_repo.ps1`（PowerShell 7） | exit 0 |

完整实验在更新 Q1 文件指纹和 M1 状态后重新计算；报告、工作簿和图表随后重建。复现清单中的 Q1 文档 SHA-256/字节数已同步到本次最终文件。
