# pi05 multi-checkpoint deployment

Shadow (does not publish arm commands):

```bash
./run_checkpoint.sh 2000 shadow
```

Live (moves the robot after the policy server is ready):

```bash
./run_checkpoint.sh 2000 live
# equivalent: ./interface_live.sh 2000
```
