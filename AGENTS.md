# 项目入口

先读 `/data/LFT-W02_data/jiaan/jiaan/agent-guide/AGENTS.md`，再读本项目 [docs/JIAAN.md](docs/JIAAN.md) 与 [迁移记录](docs/MIGRATION.md)。按用户当前任务执行，保留已有成果和其他对话的改动。

项目：vla-platform。目标：以 FluxVLA 为代码基础，逐步纳入现有模型、Cobot／Franka 适配、数采训练部署范式、RTC、动作处理和真机／仿真评测。

当前已迁入 π0.5 兼容入口及 FluxVLA 旧固定版本运行组件；π0.5 dry-run、FluxVLA 离线 baseline/prefix-RTC 验收通过，未做新的真机成功率测试。详见迁移记录。不得把资产归档或源码clone视为推理/RTC运行验证。跨项目问题按项目说明交给对应领域，证据与进展写回所属项目。
