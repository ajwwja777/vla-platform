# Cobot in_the_pot local π0.5 + RTC profile

This directory is a checkpoint-free source profile. The assembler merges its
launchers and the shared RTC runtime into the existing Cobot `pi05`
deployment. It must never contain model parameters, norm stats, Python
environments, or a checkpoint copy.

After deployment:

```bash
./interface_rtc.sh 2000
./interface_live_rtc.sh 2000
```

The first command is shadow-only. The second publishes robot commands and is
reserved for an operator physically present at the Cobot.
