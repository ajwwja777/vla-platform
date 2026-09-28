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
