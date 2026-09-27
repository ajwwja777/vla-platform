# 基于 FluxVLA 的模型训练、部署与评测平台

以 FluxVLA 为代码基础，逐步纳入现有模型、Cobot／Franka 适配、数采训练部署范式、RTC、动作处理和真机／仿真评测。

## 入口与位置

- 先读统一框架：`/data/LFT-W02_data/jiaan/jiaan/agent-guide/AGENTS.md`。
- A6000 主工作区：`/data/LFT-W02_data/jiaan/jiaan/projects/vla-platform`。
- 笔记本对话入口：`D:\Code\jiaan_workspace\vla-platform`。
- 自有独立仓库：`https://github.com/ajwwja777/vla-platform`（目标分支 `main`）。
- Cobot 目标部署位置：`/home/agilex/jiaan/project/vla-platform`，本轮尚未部署。
- 当前阶段：入口与仓库初始化；旧业务代码、环境、模型和数据尚未迁移，现有服务入口未切换。

## 负责什么

模型与配置接入、训练和推理服务、模型资产登记、归一化与动作语义、RTC／EMA 等可复用组件、评测协议与结果追溯。Franka replay 作为机器人适配的小工具；ZR-0、LiLaWAM、Harness／LIBERO-Pro 等作为方法或评测专题。

以固定版本接口供 DAgger、RL 和网页调用；Cobot 运动控制交 cobot-control。历史方法先以可验证适配器纳入，再决定是否原生重构；不强行混合所有依赖环境，不把接入登记当作复现完成。

## 机器与资产

A6000 负责主代码、Git、维护文档、主要开发验证环境、数据处理和离线评测；训练按资源需要在 A6000／已授权训练机进行。Cobot 只部署本项目现场实际需要的硬件、采集、推理、网页或维护组件，不复制仿真资产和完整训练环境。

Cobot 采集及评测数据统一规划在 `/home/agilex/jiaan/data/`。模型放所属项目的 `models/`（上游已有 `checkpoints/` 等目录时保留其源码布局，由配置明确实际权重位置）；同一资产跨项目引用，避免重复复制。现场服务日志、PID 和状态交由 `cobot-ops/runtime/` 管理；训练 checkpoint、配置和指标保留在所属项目 `outputs/<实验>/`。环境、模型、大数据与 runtime 不入 Git。

## 项目协作

模型加载、RTC、归一化、动作解释与评测由本项目负责；记录问题交 cobot-dagger；RL 学习逻辑交 rl-platform；硬件执行问题交 cobot-control。

先读本次任务涉及的依赖项目入口和接口说明，再修改相关边界；接口变更要记录受影响调用方与验证方式。常用项目：`cobot-control`、`cobot-dagger`、`vla-platform`、`rl-platform`、`cobot-web`、`cobot-ops`，主工作区均在 `/data/LFT-W02_data/jiaan/jiaan/projects/`。需要专题对话时仍共享所属项目，不因此重复建立业务仓库。

## 下一步

先接入现有 FluxVLA π0.5 的一份固定配置和离线输入／输出校验，确认旧模型语义；再分批适配 Cobot、Franka、其他模型与仿真。

旧位置、验收条件和切换／清理规则见迁移记录。

来源：2026-09-27 用户确认的项目划分、机器职责与逐批迁移方案；本轮范围仅初始化。

## 保留事项

本项目采用 clone 上游后推送到自有独立仓库，不使用 GitHub fork、不以向上游提 PR 为流程。保留 LICENSE、上游提交历史与 upstream 远端。Harness 具体上游及 LIBERO-Pro 资产仍待核定；不能把 LIBERO-Plus 当作 LIBERO-Pro。

## FluxVLA 来源

- 上游：`https://github.com/FluxVLA/FluxVLA.git`。
- 本次 clone 固定提交：`6c94e73139d51fca9650fa76265c468378020558`。
- `upstream` 保留作者地址；`origin` 指向自有独立仓库，GitHub fork 属性应为 false。
- 本次只建立源码与维护入口，未安装环境、下载模型或验证上游运行能力；旧 FluxVLA 实验仍以原固定提交及记录为准。
- 初始化期间自有仓库 GitHub Actions 关闭，避免复制的上游自动流程在首次 push 时发布或运行任务；启用前按实际用途核对工作流。
