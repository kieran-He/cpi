# `src/` 代码结构

代码按以下边界组织，避免把数据清洗、模型、实验和绘图混在一个脚本中：

```text
src/
├─ common/          # 路径、日志、随机种子、配置
├─ data/            # 原始数据读取、清洗、单位转换
├─ models/          # 各子问题模型与约束
├─ experiments/     # 可复现实验、参数扫描、敏感性分析
└─ visualization/   # 图表与流程图生成
```

用 uv 锁定并运行 Q1 P1 真实数据切片（本机 uv 当前不在 PATH，因此示例使用已安装的绝对路径；其他机器可直接用 `uv`）：

```powershell
& "D:\Research\tools\uv\uv.exe" sync --locked
& "D:\Research\tools\uv\uv.exe" run python -m src.experiments.q1_p1
```

该切片读取 O01、S001 和该区清单前 3 个货箱，执行候选生成、物理可行性筛选及最少架次精确集合划分；结果写入 `results/tables/` 和 `results/logs/`。运行日志会记录当前解释器路径及复现命令。此切片仅用于验证输入到求解的纵向链路，不是 80 箱正式 Q1 方案；正式运行前须完成独立 P1 质检。
