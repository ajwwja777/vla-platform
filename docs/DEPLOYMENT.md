# Cobot模型接入与换机部署

```text
vla-platform/
├── fluxvla/                    # FluxVLA原生实现
├── integrations/cobot/        # 历史部署、薄适配
├── configs/cobot_models.json  # 模型登记
├── configs/pi05_models.json
├── configs/external_models.example.json
├── configs/assets/           # 来源、外部材料、SHA256
├── configs/environments/     # 包版本与direct_url
└── docs/
```

主仓库 /data/LFT-W02_data/jiaan/jiaan/projects/vla-platform；现场 /home/agilex/jiaan/project/vla-platform；GitHub https://github.com/ajwwja777/vla-platform。新增同类模型优先登记配置，不改页面。

字段包含family/task/step/checkpoint/base_model/normalization/io_contract/code_revision/runtime_python/command/capabilities。同架构、归一化、相机、动作维度与单位一致才可只换权重；不同模型需要实现输入输出、就绪和真实暂停协议。

managed登记调用integrations/cobot/managed_model.py，沿用原shell/环境，加载后保持暂停。会直接运动的历史脚本仍CLI-only。旧Flux固定版本是preserved_runtime，不宣称已成为当前Flux主干的原生适配。

```bash
cd /home/agilex/jiaan/project/vla-platform
/usr/bin/python3 integrations/cobot/managed_model.py fluxvla-pi05-in-the-pot-5000 --check
cd /home/agilex/jiaan/project/cobot-web
.venv/bin/python scripts/models.py list
.venv/bin/python scripts/models.py check fluxvla-pi05-in-the-pot-5000
```

外部脚本：参考external_models.example.json建立external_models.json。填绝对argv/cwd/required；确认load_behavior=paused或server_only、process_group=foreground。第一阶段仅启动/状态/输出/完整停止；无就绪协议显示process_running，start/pause/resume/HIL/evaluate禁用。脚本不能setsid或daemon逃离登记进程组；若需要独立server须先提供专属停止适配。

材料：Git + configs/assets登记源码/环境 + 用户指定权重。A6000本项目outputs/environments/cobot-external-source-20260929.tar.gz保留Junfeng OpenPI、Galaxea、XR1、transformers vendor、LingBot、prismatic、dlimp源码，不含数据/权重，SHA见configs/assets/cobot_external_sources.json。Galaxea版本89f2322b4ad016e192437adc1a2c253b05bab246；LingBot版本a1c6c014c212d0e85729ba3b7d911ee674dd6299及现场补丁在快照保留。无Git部分标精确快照，不猜原厂版本。

Flux环境快照位置/哈希见configs/assets/fluxvla_environment.json，base Python与主要库导入已按下节验证；GPU加载与真实推理仍须单独验收。pip清单不是完整lock；diffusers dev、flash-attn和本地Flux wheel旧来源已不存在，使用保存材料或固定源码重建，不能静默换最新版。Junfeng π0.5环境归VLA，未迁入control、未升级现场共享环境。

换机替换ROS setup、Python、模型根和相机约定；不同硬件增加adapter，不改训练循环。原生Flux与历史适配分别验收。RTC/EMA保持既有配置，不为其他方法默认启用。数据/权重继续Getea1/jiaan/{data,model}，不复制大型资产。

## 已验证的Flux环境恢复

环境3,590,539,408字节及基础Python归档的完整路径/SHA在configs/assets/fluxvla_environment.json。A6000隔离目录恢复后，用-I导入torch2.6.0+cu124、flash-attn2.8.3.post1、diffusers0.37.0.dev0、fluxvla成功；修复了旧Python解释器依赖原路径的问题。未运行新的GPU推理或机器人动作。

从A6000取上述两个归档至新机器的项目outputs/environments，执行：

```bash
cd /home/agilex/jiaan/project/vla-platform
python3 scripts/restore_flux_environment.py --materials outputs/environments --destination envs/restored-flux
```

脚本核对SHA、拒绝覆盖非空目录、修正pyvenv.cfg与解释器，输出可配置的FLUXVLA_PI05_SERVER_PYTHON。CUDA驱动仍由新机提供，不能以import成功替代GPU推理测试。

机器配置configs/local.json支持environment与path_aliases；后者按最长前缀替换登记路径，命令/依赖检查也使用同一解析结果。使用{project}表示本项目根。原shell仍使用其已支持的环境变量；不支持环境覆盖的CLI-only历史入口应继续单独适配，不声称只改别名就已支持新硬件。
