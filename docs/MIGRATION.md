# 基于 FluxVLA 的模型训练、部署与评测平台：迁移记录

日期：2026-09-27。当前批次：**入口初始化**，尚未开始业务迁移。

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
