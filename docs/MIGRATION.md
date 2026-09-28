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
