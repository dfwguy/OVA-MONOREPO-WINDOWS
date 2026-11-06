---
description: Multi-rack collective performance starts with rack placement — one whole rack per SU, verified against the leaves — before any NCCL or NIC congestion-control tuning
alwaysApply: true
---

# Multi-rack performance: place the racks before you tune anything

Learned on Nscale NC (GB300 NVL72, Spectrum-X) 2026-10-27 reaching Meta's 1024-GPU all-to-all criterion.
With settings fixed, **the rack set moved 1024-GPU all-to-all 8%**; every NCCL knob together moved it
under 2%, and NIC CC tuning beyond the right profile under 0.5%. A result measured on a bad rack set
measures the rack set. Full write-up:
`docs/explanation/rack-placement-and-collective-performance.md`, procedure
`docs/how-to/place-a-multirack-job.md`, per-size settings
`docs/reference/collective-settings-by-job-size.md`.

## Rules

- **One whole rack per SU.** Two racks in one SU share leaves (128 GPUs: 130 vs 177 GB/s). Partial
  racks scattered over many racks cost ~14% and can hang NVLS/MNNVL init. Every passing run, 128 to
  1024 GPUs, was N racks in N SUs.
- **The SU map is the cluster record's `scalable_units`; the leaves are the ground truth.** Verify with
  `sudo -n lldpctl -f keyvalue | grep chassis.name` on a node per rack. Never infer the SU from the rack
  letter or row (NC's SU35 racks stand in SU20's and SU32's rows) — and the hostname suffix is a hint,
  not proof.
- **Rack choice within each SU still matters** (91.1 to 94.6 at 1024, same settings), and results are not
  monotonic in rack count. A round that collapses on identical nodes (95, 95, 60) is spine flow
  placement, not a node: rerun or change racks, do not retune.
- **Tune per job size, on a placement that is already right**, and record the rack set with the result.
  NIC CC: off at 128/256, on with the MoE profile at 512+ (off halves 512). Restore the site profile
  after.
- **Don't call it a congestion-control problem** unless loosening CC changes the result. At 1024 it
  didn't, and pauses were ~400x lower than at 512. The unexplained remainder is the spine: hand it to
  the network owner with the best and worst rack sets and their job ids.
