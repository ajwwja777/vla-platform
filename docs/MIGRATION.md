# 基于 FluxVLA 的模型训练、部署与评测平台：迁移记录

日期：2026-09-27。初始化历史保留；2026-09-28开始历史资产归档，实际范围见文末。

## 已有位置与成果

以下是已读项目记录与前序目录核验的入口清单，不表示本轮重新完整验证每项资产。执行某批迁移前须核对实际目录、符号链接、Git 状态和使用者。

| 机器 | 旧位置／已有依赖 | 保留事项 |
|---|---|---|
| A6000 | `/data/LFT-W02_data/jiaan/projects/proj-20260905-fluxvla-cobot-platform` | 已有 FluxVLA 训练、RTC 与部署适配；历史固定提交和新 clone 的提交分别记录。 |
| Cobot | `/media/agilex/Getea1/jiaan/projects/fluxvla-cobot-platform/pi05` | 已有 FluxVLA π0.5 部署资产；先核验模型与配置后再迁移。 |
| A6000 | `/data/LFT-W02_data/jiaan/projects/proj-20260829-cobot-realworld-vla` | 多模型真机训练部署、数据与评测记录。 |
| A6000 | `/data/LFT-W02_data/jiaan/projects/franka` | Franka 记录及 2026-09-19 record/replay 改进；已做离线检查，不能视为现场验收完成。 |
| Franka（历史登记） | `/data2/yjd/workspace/Franka-Teleop` | 既有现场实现，本次未访问、迁移或启动；沿既有桥接，不直接新建 NUC 控制链。 |
| A6000 | `/data/LFT-W02_data/jiaan/projects/proj-20260827-zr-0` | ZR-0 历史方法与实验记录。 |
| A6000 | `/data/LFT-W02_data/jiaan/projects/proj-20260828-lilawam` | LiLaWAM、LIBERO／LIBERO-Plus／RoboTwin 历史结果与资产来源。 |

## 首个候选验收范围

先接入现有 FluxVLA π0.5 的一份固定配置和离线输入／输出校验，确认旧模型语义；再分批适配 Cobot、Franka、其他模型与仿真。

验收要求：代码／模型／预处理版本可追溯，离线输入输出和动作语义通过对照；运行环境按实际需要准备。仿真结果、离线验证和真机成功率分别报告。

## 逐批迁移约定

一次只处理一个明确范围，记录来源、目标、依赖、版本／校验值和回退入口；先复制与验证，再切换，最后清理对应旧文件。未验收不切换，仍被依赖或缺少可靠备份的原件不清理。共有目录按文件实际归属处理，保留其他对话的未提交修改及共享资产。

迁移批次记录至少包括：范围、来源与目标、验证结果、切换状态、可清理清单及实际清理结果。初始化完成仅表示入口与 Git 可接管，不代表运行环境或业务功能已验收。

本轮没有迁移／删除旧文件，没有安装项目运行环境、启动训练、加载模型或控制机器人，也没有变更当前网页服务。

## 初始化发布记录

- 2026-09-27：项目目录与维护入口已建立，基础提交已 push 并核对远端 main 一致。
- 仓库：https://github.com/ajwwja777/vla-platform（独立仓库，非 GitHub fork）。
- 首次发布提交：`0204dd99193966efd34ed7471f29c7c10c0d50e2`。
- 本记录在首次发布验证后追加并单独提交；最新版本以 main 为准。
- 运行状态：源码／文档基础已发布，业务迁移、环境安装及新位置运行验收尚未开展。

## 2026-09-28：承接旧 Cobot 平台的历史资产

旧 /media/agilex/Getea1/jiaan/projects/cobot-platform 已完整归档到 A6000 本项目 outputs/migrations/20260927-platform-retirement/legacy-platform，9,457个普通文件、172个符号链接，共23,166,107,483字节，逐文件SHA-256及原链接文本验证通过。源文件清理前仍需新运行路径与无活跃依赖检查，实际删除另记回执。

模型实体归位：
- models/history/dm0-5/step_4000：11个文件，保留原模型、配置及预处理资产。
- models/history/xiaomi-robotics-1-dagger-round001/step_4000：保留last.ckpt/checkpoint/mp_rank_00_model_states.pt，11,004,735,893字节；与A6000既有XR1训练转移文件SHA完全相同，可复用本地原件减少跨机传输。

配置索引为configs/assets/legacy_cobot_models.json。原归档位置使用相对链接指向上述模型；171个原平台内部／跨RLT归档链接已按新布局重定位。原始manifest、校验和完整映射在迁移目录中，旧命令和实验provenance文本不改写。已有相对外部DM05基础模型链接按原样保存；历史环境依赖不能因归档完成就视为已安装。

这是历史资产保全与位置整理，没有安装FluxVLA环境、改写模型实现或验收FluxVLA推理／RTC适配。当前网页的两个π0.5入口仍使用登记的 /home/agilex/cobot_magic/task3、task5 共享部署资产，另批迁移；不要删除整棵共享工作区。

## 2026-09-28：旧平台原目录清理完成

对应cobot-platform原件已在9,629条目完整核验、归档重定位、无活动引用复核后退休：先改名隔离旧路径，正式网页从新web/control冷启动并通过模型目录、数据历史、相机启停与home帮助检查，再删除原目录。回执见相邻cobot-web/outputs/migrations/20260928-platform-retirement/cobot/retirement.json；归档和模型实体继续保存在本项目，不影响FluxVLA后续适配。

原平台链接到旧RLT历史的条目现在指向rl-platform历史归档；该归档全量传输和校验仍在执行。两个π0.5共享部署和其他旧VLA项目仍保留，不在本次整棵清理范围内。

## 2026-09-28：关联 RLT 归档完成

rl-platform的旧RLT归档现已全量SHA验收（39,001条目、122,208,969,870字节），历史模型和datasets已归其models/history与data/history，原归档相对链接保留访问。旧平台归档中171个重定位链接全部可访问；原DM05基础模型相对链接仍作为既有外部依赖保留，不伪造缺失权重。

RLT在旧路径隔离后从新项目冷加载/释放通过，随后旧RLT目录和其cobot-realworld-rl别名已删除；不改变本项目FluxVLA运行适配尚未验收的状态。网页两个π0.5入口保留共享部署位置，旧平台删除后dry-run预检通过，未重做π0.5真机推理。后续依然按固定模型输入/输出对照逐批迁移；不删除共享cobot_magic或其他旧VLA/Franka资产。


## 2026-09-28：Getea1 统一存储迁移（进行中）

Cobot 数据与模型统一在 /media/agilex/Getea1/jiaan/data/ 和 /media/agilex/Getea1/jiaan/model/。数据按场景分、模型按项目/模型分；本轮不新增 A6000 权重备份。代码、安装环境、运行日志与 PID 留在 /home/agilex/jiaan/project/<项目>/。完整路径与批次状态见相邻 cobot-web/docs/STORAGE.md。

已在 A6000 接入新存储配置及旧路径映射；逐文件复制/校验正在进行，正式网页已在空闲状态正常停止，机械臂/ROS 进程保留。本段不代表旧源目录已经删除。位姿、回放、示范、RLT rollout/Replay、评测和部署权重按 STORAGE.md 归类。最终运行验证及删除回执待本批完成后追加。

## 2026-09-28 20:00：迁移中遇到 Getea1 USB 掉线

已完成主体 12,059 条目、351,844,176,546 字节及 6 个恢复验证资产、117,047,594 字节的迁移、SHA 校验、运行验收和对应源文件清理。Warmup 与在线模型在新路径加载/释放通过；在线状态 5000/2500/2567，正式权重和 Replay 的 SHA 不变，未启动 Episode 或真机运动。历史读取、92 条有效评测和媒体通过；主副本清理后再次读通。系统盘当时剩余约 404 GiB。

剩余 FluxVLA 环境复制到 libcublasLt.so.12 时出现 I/O error。内核在 19:59:53 将 sda 下线，随后 USB 设备枚举失败；20:00 检查已无 Getea1 块设备和挂载。不能把它归因于单个 Python 包或仅网页错误，也不能仅凭这些日志判定是线缆、供电、硬盘盒或盘本体。

所有迁移进程已退出；正式网页 PID 366090 正常停止，无 GPU 模型进程，临时 ROS master 已停止。本轮未做运动。尚未验收的 FluxVLA 旧目录、暂存副本未清理，**Getea1/jiaan 仅保留 data/model 的目标尚未完成**。已验证结果仅代表掉线前状态，恢复连接后仍须核对文件系统并按迁移收据重新校验新资产，不能直接继续删除或开始在线训练。

证据：相邻 rl-platform/outputs/migrations/20260928-getea-storage/cobot/，现场同目录不带 cobot/。包括 retirement.json、validation/retirement.json、cutover-verification.json、extras/copy-status.json、disk-disconnect.json 和 disk-disconnect-kernel.log。源码和证据位于系统盘/A6000，本轮没有新增 A6000 数据/权重备份。

## 2026-09-28 20:56：Getea1 存储迁移完成

本批已完成复制、哈希与运行验收、切换和对应旧文件清理。Getea1/jiaan 只保留 data、model；旧系统盘数据/模型目录移除。数据按场景/用途/方法归类，位姿与动作回放归 data/motion；模型按项目/模型/场景/版本归类。代码/环境/日志/PID 留在 /home/agilex/jiaan/project/<项目>。

USB 掉线重连后已完成已迁移资产的全量收据复核；尚不能据此认定硬件链路根因已消除。RLT 新路径暂停加载、在线状态恢复与历史媒体通过；FluxVLA 固定版本离线 baseline/prefix-RTC 通过；π0.5 两入口只做 dry-run。本批未启动真实 Episode 或机器人动作。

完整路径、占用、各项验证边界及回执见实际 cobot-web/docs/STORAGE.md。证据位于 rl-platform/outputs/migrations/20260928-getea-storage/cobot/（Cobot 去掉末尾 cobot/）。同批源码与项目记录已按各自仓库发布；guide Git 保持由其他会话管理。

## 2026-09-28：复用历史部署脚本与模型身份标注

来源：cobot_rlt 会话；用户要求复用以前直接 .sh 部署的成果，并在权重路径后标明模型、场景、训练步数与状态。

- 历史 Galaxea G0.5（baseline/DAgger）、Xiaomi XR0/XR1/XR1 DAgger、LingBot V2、DM0.5、π0.5 lift_book/put_two_fruits 的脚本、客户端、配置、测试和 XR1 URDF 纳入 vla-platform/integrations/cobot；主代码在 A6000，Cobot 同步运行副本。来源和文件哈希在 configs/assets/legacy_deployment_entries.json。
- configs/cobot_models.json 登记 12 个历史版本/入口；现有 FluxVLA、G05 两版本、XR1 原版复用旧服务、动作映射和 RTC 参数，通过原暂停/arm服务连接网页。加载不 arm、不恢复推理；网页 Start/Resume 才调用原 arm + resume；暂停锁防止示教释放覆盖网页手动暂停。
- XR0、LingBot 两版本、另两场景的 π0.5 三版本保留原终端入口，不将会直接运动的原 live 脚本冒充“仅加载”。列表区分终端可用/网页待接入、缺少文件、基础模型依赖。DM0.5 与 XR1 DAgger 本机缺权重，历史权重仍在 A6000，不擅自复制。
- 旧共享 Python/ROS 与 G05/Xiaomi/LingBot 的已安装 runtime 仍作为显式依赖保留，没有宣称环境整体迁移或跨机器从零重建完成。原部署目录暂保留，未达到完整现场验收的部分不清理。
- 模型选择统一显示真实路径、模型、场景、步数与状态；RLT 分开标 Stage1 checkpoint / learner steps / actor version，π0.5 DAgger 保留 2000+3000 来源。备份目录名字不推断训练步数，没有证据时标待核验。

验证：A6000 web 相关后端 39 passed/1 skipped；前端 37 passed。新网页手动暂停锁 3 passed，原 G05 generation/资产 preflight 6 passed，原 XR1 HIL/旧动作过期处理 26 passed。Cobot 四个 managed 启动计划 --check 通过；G05 两版本的 checkpoint 大小、归一化/配置/processor 哈希 preflight 通过。本批未加载新 GPU 模型、未启动真实 Episode、未发送机器人动作；真实模型加载和现场动作效果仍待逐个验收。

现场发布验收：web 82ced64、vla-platform fd7ee52 已 push 并同步，分别 217 / 280 个运行文件 SHA 一致。模型 offline、采集 idle 时只重启正式 8015，硬件节点未操作。实际目录为 26 项、11 个网页加载入口、6 个保留终端入口、2 个本机缺权重条目，以及历史 RLT/基础依赖；默认 plug_v3-online-latest 未改变。只读回执：cobot-web/outputs/deployments/20260928-legacy-model-entries.json；Cobot 为 cobot-web/runtime/migrations/20260928-legacy-model-entries.json。此数目表示入口与文件预检，新增 4 个网页入口尚未逐个加载 GPU 或验收现场动作。

## 2026-09-29：职责边界与部署材料

按实际源码、只读现场状态整理，代码先在A6000开发。结构、安装、依赖来源及验证界限见docs/DEPLOYMENT.md；跨项目关系见cobot-web/docs/ARCHITECTURE.md。数据/模型实体未迁移或删除；公共厂商工作区未删除、硬件未重启。guide只写事实、不提交其Git。现场切换与版本见后续发布回执。

## 2026-09-29：正式切换、清理及交付验收

统一登记及材料首次发布e78192e。各模型记录family/task/steps、权重/基础模型/归一化、运行环境、I/O、能力与接入程度；外部sh可登记进程启动/日志/停止，没有协议的暂停/HIL明确禁用。原Flux主框架保持，历史运行时保留integrations。

A6000新增保存必要外部源码及补丁证据，不含数据/权重；Flux环境与基础Python归档独立恢复后，Torch/FlashAttention/Diffusers/FluxVLA导入通过。其他历史模型的包清单和源码材料不等于全套GPU环境重建通过；Junfeng π0.5共享环境未升级。新GPU加载和真实推理按模型逐个验收。

主代码位于 /data/LFT-W02_data/jiaan/jiaan/projects/vla-platform；现场副本 /home/agilex/jiaan/project/vla-platform。后续收尾版本以Git main和现场.release.json为准。guide仅更新事实摘要，不提交其Git。

## 2026-09-30: optional RTC cache reuse

Added prefix-cache input to the existing dagger RTC sampler and reusable pure action_processing utilities. Updated its overlay checksum manifest. Committed/pushed on A6000 and SHA256-synced only selected files to Cobot. The 14D bridge is unchanged; RLT provides its own 7D bridge. No FluxVLA core, environment, weight or robot control changes. Tests: interpolation duration/endpoints, bounded correlated noise/masks, and three actual RLT recorded-image RTC inferences. Live RLT asynchronous queue integration and higher-rate publication remain pending. See docs/JIAAN.md and RL EXPERIMENTS_20260930.md.

## 2026-09-30: reusable clock/filter and queue snapshot
Added execution_timing.py and remaining_actions() for optional RLT asynchronous
execution. Updated dagger RTC checksum manifest; no Flux/14D bridge/algorithm or
default model changes. A6000 utility and RLT contracts passed, robot not exercised.
Selective deployment to /home/agilex/jiaan/project/vla-platform follows release;
RLT owns its corresponding execution profile and Replay integration.

Selective21-file cross-project SHA deployment completed from published commits.
Cobot real Stage1+Actor synthetic-I/O7-variant audit passed, GPU returned idle.
No hardware node restart or motion; this does not constitute Flux/robot acceptance.

## 2026-09-30：领域对话与并行开发交接

用户指定后续任务由各领域项目对话负责，可并行调研、分析、现场部署和基础设施工作。
A6000 AGENTS.md 新增本领域范围、当前待办、独立worktree/任务说明和现场单一负责人的约定；
笔记本对应目录 AGENTS.md 已从旧“初始化”说明更新为正式接管入口。
本批该项目仅改文档，无业务代码/环境/资产变更或现场动作。guide仅追加项目事实，不提交Git。

## 2026-10-01：模型无关的 Hz/滤波/可选 RTC 执行模块

integrations/cobot/execution_options.py 提供纯配置校验与默认说明；execution_runtime.py 提供动作发布、物理时间滤波、前缀为空的顺序 chunk、可选异步 chunk。web/RLT 复用此配置合同。π0.5 baseline/DAgger、FluxVLA π0.5、XR1/DAgger、G05 baseline/DAgger 的暂停客户端接入，未改变权重、归一化、动作映射或默认执行路径。发布 Hz 与原逻辑步频分开，20→30/40/50 不缩短轨迹时间、不提高原 step limiter 的每秒限制；每个子 tick 校验暂停 epoch，接管重置滤波及缓存。

π0.5、Flux、XR1 保留已有原生 prefix RTC；关闭 RTC 不做 prefix 重规划。G05 官方单步 RPC 由共用 queue 聚合 chunk，开启 RTC 时异步重规划并丢弃延迟前缀，未声称 G05 支持原生 diffusion prefix guidance。未有暂停协议/缺权重的 CLI 条目仍不可网页启动；公共模块可供其适配器接入，不能以选项展示代替接入或实际模型验收。

离线 CPU：共用执行/时钟 27 passed，G05 generation/合同 15 passed，XR1 暂停/过期结果 26 passed；更新两份 RTC checksum 清单。未新加载 GPU、未机器人动作，不能将合成 I/O 视为上述各模型真机验收。发布文件 SHA 与版本见 web outputs/execution-compact-20261001/ 回执。

## 2026-10-08：π0.5 部署导入冲突已修复；DAgger 3000 权重异常待恢复

来源：用户报告及现场日志。本轮所查两次启动失败 model-20261008T145833.log、model-20261008T150342.log 为相同导入根因：网页 standalone wrapper 的 cobot_console 目录位于 sys.path 前部；VLA 共享目录已在 PYTHONPATH，旧条件没有把它前移，裸 execution_options 导入命中网页同名文件，触发 attempted relative import with no known parent package。不能据此认定更早的所有 50 Hz 故障都相同。

VLA 共用运行模块及 π0.5 baseline／DAgger、Flux、G05、XR1 客户端改用 integrations.cobot 明确包名；保留旧辅助模块路径，更新两份 RTC overlay checksum。代码提交 83a49c9c059da661df34f152c617b7d54d3424a5 已 push、同步；12 个运行文件 SHA 与完整两份 overlay 清单核验通过。算法、默认频率／滤波常数、权重、归一化和动作映射未修改。

真实网页 wrapper／RTC 模块加合成硬件／策略依赖的测试在修复前复现，修复后 baseline／DAgger 各自默认、20 Hz 无 RTC／滤波、50 Hz＋RTC＋滤波、50 Hz 无 RTC＋滤波共 8 个组合到达 ready and PAUSED。CPU 回归共 144 项通过：共用执行／导入／时钟 37、G05 30、XR1 52、web 暂停／执行配置合同 25；Flux 导入冒烟通过。工控机真实 client Python／ROS／OpenPI 环境的 8 个导入／选项解析组合通过。这些不是实际权重推理或持续 50 Hz 发布验收。

现场仅提交一次 DAgger 3000 的 50 Hz＋RTC＋滤波显式加载，保持 manual_pause，不请求 start／resume／home。权重恢复完成，真实相机／关节 observation 同步完成；首个 prefix 为空的普通 baseline 预热请求返回非有限动作，RTCProtocolError: actions_robot must contain finite values。故障发生在 guided RTC 重规划和发布端滤波之前；模型没有 ready。启动器已退出并收尾自己启动的 policy server。未继续提交已知坏权重的原 20 Hz 加载，不声称原配置恢复或两配置真机通过。

只读 CPU 参数恢复扫描（原 float32，不做 GPU／bf16 转换）确认 51 个参数叶、3,353,433,872 个参数中，4 个张量共 96 个非有限值：input_embedding 9、mlp/gating_einsum 27、mlp/linear 58、mlp_1/gating_einsum 2。与 2026-09-28 Getea 迁移 copied-files.jsonl 的 19 文件 SHA 对账，15 个一致，4 个参数数据文件不一致：1bf70e1ab729c2317a20f411e3169a69、29a49413c8812dd549aeeeea3c2debb1、7434943d4187ec08f841850611be2528、a37ff27b36ec269fd140299c14eba633。可确认内容与迁移记录不同，具体改变原因尚未确定。归一化文件 SHA 与登记原始结果一致。

已登记 Cobot 旧 step_3000 是当前 Getea 权重的符号链接，不是独立备份；A6000 2026-09-08 审计记载当时完整权重备份未完成。训练原始产物来源为 trainer 的 task5_hil_realworld_rl/checkpoints/task5_pi05_masked_in_the_pot_round_001/dagger_round001_step2000_3000/2999（旧 Task5 已归档到 legacy-assets/cobot-platform-pre-framework-202608）。本轮按已登记 124.174.13.117 的 25791、65279 两入口尝试，均连接超时。等待同版本可信原件／备份入口，核对资产身份及有限性后才能恢复；未改坏权重、未将 NaN 清零、未切换其他模型冒充恢复。

最终网页 PID 63917 与 12 个采样硬件／模型身份保持；部署 phase=error、model_ready=false、process_started=false，日志所记录 launcher PID 3402035 已不运行，active／operation／writer_token 均为空。页面仍显示本次 50 Hz＋RTC＋滤波选择。没有网页／硬件重启、没有运动、没有生产 Episode 或 Replay 修改。现场拥有权已释放，后续加载前重新核对现场所有权与权重健康。

完整证据：cobot-web/outputs/pi05-import-20261008/ 的 source-release.json、field-imports.json、checkpoint-finite-scan.json、checkpoint-migration-hashes.json、after-failure.json 与 final-release.json；现场 runtime/verification/pi05-import-20261008/。客户端失败日志 runtime/deployment/model-20261008T152221.log；policy server 日志 runtime/deployment/pi05/logs/rtc_policy_server_20261008_152222.log。本批 VLA 旧源文件备份在 vla-platform/runtime/incidents/pi05-import-20261008/before/。部署修复尚未完成，剩余阻碍为同版本健康权重。
