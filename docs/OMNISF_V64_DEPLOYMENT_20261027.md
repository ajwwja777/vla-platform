# OmniSF v64_memory 网页部署接入

2026-10-27；来源：用户指定路径与任务指令、现场 qizhou/omnisf_real README／原生脚本、所属 Web 验证回执。状态：网页可部署入口已激活；GPU加载／实际推理／运动验收待用户加载，未作为本次已通过项目。

| 项目 | 实际值 |
|---|---|
| 模型ID | omnisf-v64-memory-cover-blocks-30000 |
| 网页选择 | cover_blocks / OmniSF / 30000 |
| 权重 | /home/agilex/qizhou/omnisf_real/v64_memory_ckpt/30000 |
| 指令 | Cover the three blocks from left to right, then uncover them again in the order of red, green, and blue. |
| 原生来源 | /home/agilex/qizhou/omnisf_real；原文件未修改、未搬迁 |
| 代码身份 | native_manifest.json 的5项SHA；原目录无Git，不虚构上游revision |
| 服务／Python | 原 serve.sh，端口8064；shuqi/06_Spatial_Forcing/env，只读复用 |
| 客户端 | 原 v64_live.py + 已审核生命周期钩子；aloha环境 |
| 实际频率 | 原生30Hz，每段前25步；RTC off／额外滤波off |

模型含记忆输入，不能登记为现有 π0.5 任务模板。沿用原生 cam_high 起始帧+最近8秒+当前帧，两腕当前RGB；双臂16维 xyz/wxyz/夹爪输入输出、原生归一化、IK阻尼及关节／速度限制保持。桥接在执行前校验原文件SHA并要求唯一锚点，原文件变化则明确拒绝加载；不把未经审核的新版本静默运行。AST核对 History、Arm、to_rgb、arm_state、pose_error 与原文件一致。

新增 integrations/cobot/omnisf/{interface.sh,run.py,bridge.py,gate.py,native_manifest.json}。managed_model 提供独立server_port。run.py 持有原生服务与客户端同一网页进程组；默认手动暂停且未arm，必须显式arm验证新鲜观测／发布权后才能resume。暂停与双臂发布持同一锁，暂停／继续代际变化使在途旧计划失效；只在新一代规划重新用反馈起始值。独立CPU心跳覆盖慢推理等待，网页校验当前supervisor PID／模型ID／新鲜度。错误或退出记录fault并取消ready，不借杀进程实现暂停。原生源文件与共享环境不写入。

当前只支持原生30Hz；该入口的自定义Hz/RTC/滤波禁用，后端拒绝不支持的选项，其他模型行为保持。不宣传30→50Hz或RTC已适配。原生夹爪全开0.07m为该脚本原默认值，README注明尚待现场校准；跨机器人 cover_blocks 的成功率也未验收。本任务未改变这些原始假设。capture/HIL/train能力不冒充支持，部署结果首尾帧仍由网页原有评测逻辑负责。

源码VLA020a0390b1e1a88f637940cf63d1fd5af358f04a、Web0b40ff8709cec89946936f53eaf3a2f263daf35e已提交/push再同步；现场12文件逐项旧SHA预核验、备份、原子替换、新SHA核验。只重载Web5111→42904，12采样硬件进程启动身份保持，模型offline／Sessioninactive／录制idle。未使用GPU、加载模型、启停硬件、发动作、录制、编辑Replay或权重。

验证：7门控CPU测试，64相关Web后台通过／1既有跳过／1旧失败夹具剔除，完整前端140通过。旧失败test_real_saved_episode_labels_and_history_summary在未修改main同样复现recorder属性缺失，单独留证，未顺带修改Dagger。现场run.py --check通过；原生离线自检记忆、状态打包、FK／20次IK往返通过（全部位置误差<1mm），未建立ROS节点。正式HTTP登记available=true，生产选择器实际数据DOM显示30000与正确路径/30Hz；首页与选项JS HTTP SHA一致。未运行GPU加载或真实运动。

主证据：/data/LFT-W02_data/jiaan/jiaan/projects/cobot-web/outputs/omnisf-v64-20261027/，含 native-source-snapshot.json、native-contract-verification.json、gate-tests.txt、backend-tests-final.txt、baseline-collection-fixture.txt、frontend-tests-final.txt、field-cpu-checks.json、source-release.json、field-release.json、http-verification.json、picker-verification.json、final-release.json。独立工作树在scratch/{vla-platform,cobot-web}/omnisf-v64-20261027/，一次性同步工具归Web scratch。现场旧文件在cobot-web/runtime/verification/omnisf-v64-20261027/before/；同级保存安装／验收回执。

VLA主目录原有Franka docs/JIAAN.md、docs/MIGRATION.md及交接文档未提交修改逐字保留，本任务未替其提交。guide只同步摘要，不提交/push。
