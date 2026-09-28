# Cobot 模型部署入口

本目录保存现场需要的模型适配代码，A6000 是主工作区，Cobot 同步对应文件；权重不入 Git。

- pi05/baseline：in_the_pot 原 step 2000，权重 /media/agilex/Getea1/jiaan/model/vla-platform/pi05/in_the_pot/baseline_2000。
- pi05/dagger：原 step 2000 初始化，再训练 3000 步，权重 /media/agilex/Getea1/jiaan/model/vla-platform/pi05/in_the_pot/dagger_2000plus3000。
- fluxvla_pi05：固定 FluxVLA 8e22b69 的 5,000 步模型，权重 /media/agilex/Getea1/jiaan/model/vla-platform/fluxvla_pi05/in_the_pot/step_5000；基础模型在同模型族 base/pi05_base。

前两个入口由 cobot-web 的共享模型加载器调用。旧 π0.5 server 环境仍依赖 /home/agilex/junfeng/workspace/pi05_cobot，ROS 客户端使用既有 aloha 环境；此次不升级驱动或环境。

FluxVLA 的现场项目根为 /home/agilex/jiaan/project/vla-platform；envs/fluxvla-cu124-py310、third_party/fluxvla-pinned 是保留的固定运行环境与上游版本。旧部署的安全门控和动作语义不变；本次只做路径迁移与无发布者的离线验证，不能视为真机成功率或完整从零重建验收。

FluxVLA 的 start_local_server.sh 只加载本机推理服务，不启动机器人客户端；offline_replay.py 读取固定 fixture 并验证 baseline/prefix RTC；stop_local_server.sh 通过本服务 RPC 停止。LIVE 入口仍是 interface_task2_teach_rtc_live.sh，须现场满足既有门控，迁移验证不执行它。

旧 manifest 的 source_path/source_sha256 保留来源；deployment.json 的当前字段用于新路径校验，training-run.json 与 offline-validation.json 保留历史结果。数据布局见相邻 cobot-web/docs/STORAGE.md，实际验收见本项目 docs/MIGRATION.md。
