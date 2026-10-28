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


## 2026-10-28：首次部署时间戳异常及保护保留修复

用户日志与正式状态确认：launcher2130379，model-20261028T182421.log；权重恢复5.12秒、原生归一化载入成功，模型曾ready/paused，显式开始后第一预测2.945秒、IK151ms；commands_sent=0。真正终止原因是Camera/joint timestamps differ by more than100ms，原客户端异常外抛后supervisor关闭服务。ROCm/TPU提示不是本次终止原因；WebSocket InvalidMessage来自接入适配器裸TCP就绪探测，后续原生客户端已连接成功。该探测设计是本接入的问题，改为服务原有HTTP /healthz。

当下只读5秒/492样本偏差中位25.15ms、P95 33.21ms、最大36.65ms，0次超过100ms；不能据此还原先前瞬时越界的唯一来源，也不将首次编译耗时断言为时间戳异常的根因。保留原生100ms跨流对齐、250ms时间/到达新鲜度、控制权/示教/IK/有限值/限速保护；没有放宽阈值。规划与arm阶段最多等待200ms以取得严格有效的快照；每条动作仍使用一次即时严格检查，不在发布中等待后续帧补过期计划。

VLA6865d161ab222dd7047c047c97b1606a90c9b41a：真实两次RPC预热及有限值/shape校验置于ready前；预热未完成不可arm。运行循环异常丢弃该代计划、保护性手动暂停且保留ready/客户端/模型服务，记录原始fault；不自动恢复。显式arm重新验证新鲜观测与控制权后才允许继续。启动/权重/预热失败仍不宣称ready。新增无动作发布器的shadow资格检查参数，和--execute互斥。原生记忆、转换、IK和发布限速保持。

12项CPU测试通过。独立GPU端口18064、原始30000与实际三相机/双臂数据的零发布器测试通过：ready前两次预热，之后5次预测/IK，推理约240–246ms，commands0。另注入100ms故障后ready=true/paused=true/manual_pause=true/原始fault保留，客户端和服务持续存活；无自动resume。全部自有测试server/client退出，生产PID/待收尾轮次不变。第一次注入脚本未命中锚点、断言失败，日志独立保留；修正诊断锚点并断言唯一后重跑通过，不把首轮当作保护验收。不是机器人运动验收。

现场按旧/新SHA同步4个VLA文件，run.py --check通过；不重启Web/模型/硬件，不自动加载正式模型。Web94cb4b6d78964b91e8b3d1b2bf2958be6e36f900补上既有unknown协议的“未知并保留”按钮，已退出模型的轮次可非删除收尾，操作直接走unknown而不走自动归位；RLT保留原专属skip。142完整前端、27相关后台/1既有跳过通过，两静态文件正式HTTP SHA一致。

当前eval-20261028T182447-3c151881仍待用户处理，目录/media/agilex/Getea1/jiaan/data/evaluations/test/；源文件全部SHA保持，未替用户标注成功/失败/未知，未丢弃首帧。13个采样Web/硬件进程启动身份保持。修复在下次模型加载生效，前端刷新生效；未知保留按钮供用户收尾后释放/重载。没有运动、归位、硬件启停、权重/Episode/Replay编辑或残留测试进程。

主证据/data/LFT-W02_data/jiaan/jiaan/projects/cobot-web/outputs/omnisf-first-deploy-20261028/：timestamp-probe.json、cpu-tests.txt、web-backend-tests.txt、frontend-tests.txt、shadow-command.json（首次注入未命中）、shadow-retry-command.json、shadow-qualification.json、source-release.json、web-source-release.json、field-release.json、static-release.json与final-release.json。现场VLA runtime/verification/omnisf-first-deploy-20261028/保存before源码备份和隔离试验，shadow-retry/保留最终通过日志/回执；Web同名runtime/verification保存两静态备份。guide只更新事实摘要，不提交/push。
