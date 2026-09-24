# 比赛范围与规则核验

状态：`2026 国际赛道 / 已完成公开信息核验，队伍专属提交页仍需由队长登录确认`

## 1. 已确认的比赛身份

| 项目 | 已确认内容 | 来源 |
|---|---|---|
| 竞赛 | 2026 年“华为杯”第二十三届中国研究生数学建模竞赛 | [2026 年官方参赛邀请函](https://cpipc.acge.org.cn/cw/contestNews/detail/4/2c9080189dcfa24e019dddacc24a1314?page=0) |
| 赛道 | International Track / 国际赛道 | 仓库内国际赛道报名与提交手册；国际赛道队伍专属提交链接 |
| 题目 | Problem H: *Cooperative Optimization of UAV Transport and Communication Under Mountain Flood Disaster Scenarios* | `questions/Cooperative Optimization of UAV Transport and Communication Under Mountain Flood Disaster Scenarios.docx` |
| 承办单位 | 西安交通大学 | 官方参赛邀请函 |
| 竞赛秘书处 | 东南大学 | 官方参赛邀请函 |
| 论文语言 | 英文 | 国际赛道流程手册与题目文件均为英文；最终以当届提交页面要求为准 |
| 论文格式 | PDF；使用竞赛指定的标准论文文档 | 官方参赛邀请函；国际赛道流程手册 |
| 组队 | 每队 3 人（1 名队长、2 名队员） | 2026 官方邀请函的组队规则；国际赛道流程手册的注册流程 |

## 2. 题目与仓库材料映射

题目文件明确给出 4 个子问题，围绕山洪灾害场景下的无人机运输、通信中继和救援资源分配：

1. 单目的地往返运输能力与货物箱分批；
2. 异构无人机的多目的地、多架次运输调度；
3. 通信约束下运输无人机与中继无人机的联合调度；
4. 救援任务划分与资源分配优化。

题目附件包括：

- 运输无人机、接力无人机、通信链路、需求与时限等 Excel 数据；
- 30 m DEM 及道路、水体、居民点等地理空间数据；
- 地理空间数据说明文档；
- 题目要求的结果文件、验证文档和可执行程序。

对应仓库路径：

- 原始题目与数据：`questions/`；
- 模型合同和验证计划：`analysis/`；
- 代码：`src/`；
- 结果与复现记录：`results/`；
- 图表：`figures/`；
- 论文工作区：`paper/`。

## 