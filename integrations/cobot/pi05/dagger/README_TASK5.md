# Task5 DAgger Round001 — Cobot in_the_pot

This package deploys the masked DAgger fine-tune initialized from the previous
`step_2000` policy. It keeps the verified five-arm Task2 teach-button + RTC
runtime, so either rear teach button pauses the policy, transfers that side to
the operator, then resumes from a fresh observation.

Run after CAN, five-arm Task2 launch, three cameras, and front homing are ready:

```bash
cd /home/agilex/cobot_magic/task5/jiaan/hil_realworld_rl/deployments/in_the_pot/pi05_dagger_round001
./interface_task5_hil_rtc_live.sh 3000
```

The rollout recorder remains a separate process and can be started before this
script. This deployment package does not change the original Task3 checkpoint
or its launchers.
