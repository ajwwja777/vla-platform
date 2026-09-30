# 基于 FluxVLA 的模型训练、部署与评测平台

以 FluxVLA 为代码基础，逐步纳入现有模型、Cobot／Franka 适配、数采训练部署范式、RTC、动作处理和真机／仿真评测。

## 入口与位置

- 先读统一框架：`/data/LFT-W02_data/jiaan/jiaan/agent-guide/AGENTS.md`。
- A6000 主工作区：`/data/LFT-W02_data/jiaan/jiaan/projects/vla-platform`。
- 笔记本对话入口：`D:\Code\jiaan_workspace\vla-platform`。
- 自有独立仓库：`https://github.com/ajwwja777/vla-platform`（目标分支 `main`）。
- Cobot 运行副本：`/home/agilex/jiaan/project/vla-platform`；只部署现场推理组件。
- 当前阶段：π0.5 兼容部署入口及 FluxVLA 旧固定版本已迁入；前者 dry-run、后者离线推理/RTC 通过，未做新的真机成功率评测。

## 负责什么

模型与配置接入、训练和推理服务、模型资产登记、归一化与动作语义、RTC／EMA 等可复用组件、评测协议与结果追溯。Franka replay 作为机器人适配的小工具；ZR-0、LiLaWAM、Harness／LIBERO-Pro 等作为方法或评测专题。

以固定版本接口供 DAgger、RL 和网页调用；Cobot 运动控制交 cobot-control。历史方法先以可验证适配器纳入，再决定是否原生重构；不强行混合所有依赖环境，不把接入登记当作复现完成。

## 机器与资产

A6000 负责主代码、Git、维护文档、主要开发验证环境、数据处理和离线评测；训练按资源需要在 A6000／已授权训练机进行。Cobot 只部署本项目现场实际需要的硬件、采集、推理、网页或维护组件，不复制仿真资产和完整训练环境。

Cobot 数据和 checkpoint 均存放 Getea1/jiaan/{data,model}；场景数据共享，模型按项目/模型/场景/版本引用。现场服务日志、PID 和状态归实际负责项目；网页编排任务使用 `cobot-web/runtime/`；A6000 训练中间 checkpoint 与配置、指标按所属项目实验目录管理；Cobot 上的 checkpoint 则必须配置到 Getea1/model。环境、模型、大数据与 runtime 不入 Git。

## 项目协作

模型加载、RTC、归一化、动作解释与评测由本项目负责；记录问题交 cobot-dagger；RL 学习逻辑交 rl-platform；硬件执行问题交 cobot-control。

先读本次任务涉及的依赖项目入口和接口说明，再修改相关边界；接口变更要记录受影响调用方与验证方式。常用项目：`cobot-control`、`cobot-dagger`、`vla-platform`、`rl-platform`、`cobot-web`，主工作区均在 `/data/LFT-W02_data/jiaan/jiaan/projects/`。需要专题对话时仍共享所属项目，不因此重复建立业务仓库。

## 下一步

当前已完成固定旧Flux的离线输入/输出检查和环境恢复导入；下一步是现场动作验收，再分批完善原生Flux、Franka及其他模型适配。

旧位置、验收条件和切换／清理规则见迁移记录。

初始化来源：2026-09-27。当前状态以最新迁移记录和docs/DEPLOYMENT.md为准。

## 保留事项

本项目采用 clone 上游后推送到自有独立仓库，不使用 GitHub fork、不以向上游提 PR 为流程。保留 LICENSE、上游提交历史与 upstream 远端。Harness 具体上游及 LIBERO-Pro 资产仍待核定；不能把 LIBERO-Plus 当作 LIBERO-Pro。

## FluxVLA 来源

- 上游：`https://github.com/FluxVLA/FluxVLA.git`。
- 本次 clone 固定提交：`6c94e73139d51fca9650fa76265c468378020558`。
- `upstream` 保留作者地址；`origin` 指向自有独立仓库，GitHub fork 属性应为 false。
- 本次只建立源码与维护入口，未安装环境、下载模型或验证上游运行能力；旧 FluxVLA 实验仍以原固定提交及记录为准。
- 初始化期间自有仓库 GitHub Actions 关闭，避免复制的上游自动流程在首次 push 时发布或运行任务；启用前按实际用途核对工作流。

2026-09-27 归属更新：独立 ops 项目已取消；本次仅修正协作与 runtime 归属，不代表本项目旧业务资产已迁移。

历史模型位置：models/history/dm0-5/step_4000、models/history/xiaomi-robotics-1-dagger-round001/step_4000。来源与SHA索引见configs/assets/legacy_cobot_models.json，完整保全记录见docs/MIGRATION.md（2026-09-28）。

## 当前现场资产（2026-09-28）

- 权重：/media/agilex/Getea1/jiaan/model/vla-platform/。
- 共享场景数据：/media/agilex/Getea1/jiaan/data/datasets/in_the_pot/。
- π0.5 入口：integrations/cobot/pi05/{baseline,dagger}；对应 pi05/in_the_pot/{baseline_2000,dagger_2000plus3000}。
- FluxVLA 入口：integrations/cobot/fluxvla_pi05；固定代码 third_party/fluxvla-pinned，环境 envs/fluxvla-cu124-py310，日志/PID runtime/fluxvla-pi05。
- FluxVLA 权重：fluxvla_pi05/in_the_pot/step_5000，共享基础模型 fluxvla_pi05/base/pi05_base；环境和安装缓存不放外接盘。
- 固定上游 8e22b69b2ff8c8c333d4095596cde8e1e3b57ade 在自有 Git 历史可取得；额外代码归档及 SHA 见 configs/assets/cobot_fluxvla_runtime.json。不升级成主仓库较新的实现。
- A6000 models/history 的 DM0.5（10.89 GiB）和 Xiaomi DAgger（10.25 GiB）历史权重保留，本轮没有新增权重备份；旧 A6000 XR1 final-transfer 对应历史副本的去重仍属后续范围。Cobot 上 DM0.5 仅元数据，旧 Xiaomi DAgger 缺失链接不冒充可部署权重。

完整目录清单、磁盘空间、迁移回执和 USB 故障限制见相邻 cobot-web/docs/STORAGE.md。新设备环境完整重建任务仍按用户后续授权单独完成；这批迁移保留现场已安装版本。

## 2026-09-29接入导航

先读[结构、模型登记与换机部署](DEPLOYMENT.md)。历史运行时留在integrations，Flux原生代码未为统一页面而改动。RLT/EXPO-FT保留各自算法。源码/环境材料的完整路径与SHA见configs/assets；包清单不代表已验证可重装环境。

## 2026-09-30: reusable execution utilities for RLT

Existing implementation stays in integrations/cobot/pi05/dagger/common/: rtc_overlay/rtc_openpi/sampler.py now accepts an optional prefix_cache; the default computation remains unchanged. runtime_lib/execution_methods/action_processing.py provides pure time-preserving integer-rate interpolation and bounded caller-seeded correlated noise with dimension masks. It imports no ROS or RL algorithm. RLT owns its separate 7D transform bridge and reuses this sampler; FluxVLA native directories and training remain unchanged. Array tests pass; RLT's three recorded-frame RTC run reports ~72 ms baseline / ~114 ms guided after compilation, identical repeated baseline actions/tokens. This is not integrated RLT RTC or robot validation; no live publication/noise settings changed. Full experiment evidence: /data/LFT-W02_data/jiaan/jiaan/projects/rl-platform/docs/EXPERIMENTS_20260930.md. Cobot counterpart root: /home/agilex/jiaan/project/vla-platform/.

## 2026-09-30: shared physical-time execution

runtime_lib/execution_methods/execution_timing.py adds regular rational-rate
publication ticks and causal time-constant joint filtering without ROS/model/RL
imports. rtc/action_queue.py adds a detached remaining-actions snapshot, preserving
existing queue ownership semantics. RLT uses the same shared queue/sampler with its
own 7D adapter; VLA does not import RL and Flux native algorithms remain unchanged.
tau=80ms is an RLT opt-in profile, not a default change to existing pi05 deployment.
6 utility tests passed; full RLT contracts total 76. Cobot GPU and robot acceptance
are separate. Source tree, usage and rollback:
/data/LFT-W02_data/jiaan/jiaan/projects/rl-platform/docs/RUNBOOK.md.
