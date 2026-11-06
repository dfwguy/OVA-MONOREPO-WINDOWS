---
diataxis: reference
description: The placement, NCCL variables and NIC congestion-control state that passed each multi-rack job size on a GB300 NVL72 Spectrum-X cluster, and where each signal is read.
---

# Collective settings by job size

The configurations that met Meta's acceptance criteria on Nscale NC, by job size, and the signals used to
tune them. Placement comes first; see
[rack placement and collective performance](../explanation/rack-placement-and-collective-performance.md)
for why and [how to place a multi-rack job](../how-to/place-a-multirack-job.md) for the procedure.

Measured 2026-10-24 to 2026-10-27 on GB300 NVL72 (4 GPUs per node), one ConnectX-8 per GPU split into 4
planes of 200 Gb/s, NVIDIA SN5610 leaves (Cumulus Linux 5.16.6), HPC-X 2.25.1, nccl-tests at 2 GB,
100 iterations after 50 warm-up, three rounds. On another platform or fabric these are starting points
to re-measure, not answers.

## Placement

| GPUs | Racks x nodes per rack | SUs | All-to-all share on NVLink |
|---|---|---|---|
| 128 | 2 x 16 | 2 | 1/2 |
| 256 | 4 x 16 | 4 | 1/4 |
| 512 | 8 x 16 | 8 | 1/8 |
| 1024 | 15 x 15-18 | 15 | 1/15 |

Every passing run used whole racks and one rack per SU.

## All-to-all

Set on the cluster record as `nccl_env.collectives.alltoall.multirack`, which applies to the
all-to-all run of a multi-rack NCCL test only.

| Setting | 128 | 256 | 512 | 1024 |
|---|---|---|---|---|
| NCCL | 2.32.3 | 2.32.3 | 2.30.7 | 2.30.7 |
| `NCCL_NET_PLUGIN` | RDMA (1) | RDMA (1) | RDMA (1) | RDMA (1) |
| `NCCL_NET` | `IB` | `IB` | `IB` | `IB` |
| `NCCL_NVLS_ENABLE` | `0` | `0` | `0` | `0` |
| `NCCL_IB_QPS_PER_CONNECTION` | `4` | `4` | `4` | `3` |
| `NCCL_IB_SPLIT_DATA_ON_QPS` | `1` | `1` | `1` | `1` |
| `NCCL_IB_ADAPTIVE_ROUTING` | `1` | `1` | `1` | `1` |
| `NCCL_MAX_NCHANNELS` | `16` | `24` | `24` | `24` |
| `NCCL_BUFFSIZE` | `8388608` (8 MB) | `4194304` (4 MB) | `8388608` (8 MB) | `8388608` (8 MB) |
| `NCCL_P2P_NET_CHUNKSIZE` | default | `262144` (256 KB) | `524288` (512 KB) | `1048576` (1 MB) |
| NIC congestion control | off | off | on, MoE profile | on, MoE profile |
| Result, GB/s at 2 GB | 175.98-176.42 | 117.13-117.70 | 102.11 | 94.61 |
| Meta criterion | 178.84 | 117.08 | 104.19 | 98.98 |
| Jobs | 222901 and SU27/SU35 sets | 224069, 224073 | 224312 | 224728 |

(1) `<HPC-X>/nccl_rdma_sharp_plugin/lib/libnccl-net.so`, named per collective because the cluster's
`fabric.net_plugin` points every other run at the Spectrum-X plugin, which measured faster for the
collectives below.

NCCL on GB300 doubles the P2P chunk it is given; the values above are what the variable is set to.
Meta's criterion allows 5% below the figure shown.

## All-reduce, all-gather, reduce-scatter

Meta sets these only at 128 and 256 GPUs. They ran on the cluster's span list
`nccl_env.multirack`, with no per-collective list:

| Variable | Value |
|---|---|
| Network plugin | Spectrum-X (`libnccl-net-spcx.so`, from the cluster's `fabric.net_plugin`) |
| `NCCL_NET` | `SPCX` |
| `NCCL_BUFFSIZE` | `1048576` (1 MB) |
| `NCCL_IB_QPS_PER_CONNECTION` | `1` |

128 GPUs, job 222901: all-reduce 681, all-gather 618, reduce-scatter 631 GB/s at 2 GB.

## What each setting moved at 1024 GPUs

Spread between the best and worst value tried, everything else fixed, all-to-all at 2 GB.

| Lever | Values tried | Spread |
|---|---|---|
| NIC CC parameters beyond the MoE profile | delay threshold, first-congestion rate, recovery period, increase | < 0.5% |
| NCCL version | 2.30.7, 2.32.3 | < 0.5% |
| QPs, P2P chunk, channels, adaptive routing | QP 1-6, chunk 128 KB-1 MB, 16-32 ch, AR on/off | 1.7% |
| NIC CC profile | site, MoE | 4.3% |
| `NCCL_BUFFSIZE` | 8 MB, 16 MB | 5.4% |
| Racks, one per SU | three rack sets, plus two-racks-in-one-SU sets | 8.1% |
| NIC CC | off, on (MoE) | 13% |
| Nodes per rack | whole racks, 16 nodes per SU from any rack | 14% |

## NIC congestion-control profiles

Spectrum-X `ztr_rttcc` parameters, register `PPCC`, written per ConnectX-8 (one PF per rail) with
`mlxreg -d <pci> -y --set cmd_type=8,value=<V> --reg_name PPCC --indexes
local_port=1,pnat=0,lp_msb=0,algo_slot=0,algo_param_index=<idx>` and read back with
`--get --op cmd_type=0x6`. `cmd_type=2` turns CC off. Never `cmd_type=0x7`: it zeroed a parameter on
one NIC.

| Index | Parameter | Site profile | MoE profile |
|---|---|---|---|
| 4 | Additive increase | 36 | 96 |
| 5 | Hyper additive increase | 1200 | 1700 |
| 6 | Hyper additive increase period | 7,000,000 ns | 200,000 ns |
| 7 | Congestion delay threshold | 15,000 ns | 13,000 ns |
| 9 | Rate on first congestion | 524288 (50%) | 524288 (50%) |
| 12 | TX_DEC | 0 | 1 |

The site profile is the Spectrum-X Compute Network Deployment Guide v2.1.5 recommendation. The MoE values
are the firmware defaults for these parameters. A NIC register change is not stored by Rack Status and
does not survive a reset; restore the site profile after a run.

## Signals and where to read them

| Signal | Where |
|---|---|
| SU of each rack | Cluster record `scalable_units` (**Platform › Projects & Clusters**) |
| Leaf behind each plane port | `lldpctl -f keyvalue`, key `lldp.<port>.chassis.name`, on the node |
| Per-round bus bandwidth | Job log, `# Avg bus bandwidth` lines, one per round |
| NCCL variables a run used | Job log, `<collective>: its own NCCL settings:` and `env:` lines |
| Racks and SUs of a recorded run | **Analytics & Benchmarks › Handover Reports** |
| Switch-to-NIC pause frames | `ethtool -S eth_p<plane>_r<rail>`, `rx_prio3_pause` (lossless priority 3) |
| ECN marks, buffer drops | `ethtool -S`, `rx_ecn_mark`, `rx_prio3_discards`, `rx_out_of_buffer` |
| NIC CC parameters in force | `mlxreg ... --get --op cmd_type=0x6`, per index above |
