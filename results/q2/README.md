# Q2 实验结果

`Q2_Results_Submission_Template.xlsx` 与同目录 CSV 是当前 24 架次架次数优先推荐方案；其求解记录为 `alns_sortie_k400_seed20260929.json`，候选池为 `candidate_pool_k400.json`。迟到优先基线的表格和工作簿单独保存在 `baseline_lateness/`。

## 验证与导出

```powershell
.\.venv\Scripts\python.exe -m src.experiments.q2_revalidate_alns
.\.venv\Scripts\python.exe -m src.experiments.q2_export_sortie_k400
.\.venv\Scripts\python.exe -m src.experiments.q2_figures
```

第一条命令复核并导出 39 架次基线；第二条按冻结的 K=400 求解记录生成正式 24 架次结果；第三条生成 `figures/` 中的 Q2 图表和 `figure_previews/` 灰度预览。候选路线池、随机种子、软件依赖和 SHA-256 摘要记录在 `复现清单.json`。完整实验累计求解时间约 76 分钟，低于五小时预算。

完整模型、变量与验证口径见 [Q2 模型说明](../../analysis/problems/Q2.md)。完整全量精确 MILP 不作为求解入口；精确 MILP 仅用于 [微型实例交叉核对](../../analysis/validation/q2_miniature_milp.py)。
