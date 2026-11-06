---
diataxis: explanation
description: Why which racks a multi-rack job runs on decides its all-to-all bandwidth more than any NCCL or congestion-control setting, and what that means for tuning on any cluster.
---

# Rack placement and collective performance

On a rack-scale NVLink system with a leaf-spine scale-out fabric, **the first performance setting of a
multi-rack job is which racks it runs on.** Tune NCCL and the NIC first and you are adjusting the last
1-2% of a result whose first 10% was decided by placement. This page says why, and what it means for
every cluster Rack Status runs on. The procedure is in
[how to place a multi-rack job](../how-to/place-a-multirack-job.md); the measured settings per job size
are in [collective settings by job size](../reference/collective-settings-by-job-size.md).

## Three layers, three domains

A job's traffic crosses up to three domains, and each has a different bandwidth and a different owner:

| Domain | What it is | Who carries the traffic |
|---|---|---|
| **Rack** | One NVLink domain (an NVL72 rack, 18 compute trays, 72 GPUs) | NVLink switches, inside the rack |
| **Scalable unit (SU)** | The racks one set of leaf switches serves | Leaf switches: rack to rack inside the SU |
| **Fabric** | Every SU | Spine (and super-spine) switches: SU to SU |

The Rack Status record already models the middle layer: a cluster's
[`scalable_units`](../reference/catalog/projects-and-clusters.md) is the SU-to-rack map. The outer layer
is not in the record; it lives in the switches.

## Why NVLink matters less as the job grows

All-to-all sends an equal share of data from every GPU to every other GPU. With *R* racks in the job,
only 1/*R* of a GPU's traffic stays on NVLink; the rest crosses the scale-out fabric. At 2 racks half of
it is local, at 8 racks one eighth, at 15 racks under 7%. Small jobs are NVLink-bound and forgiving of
placement; large jobs are fabric-bound and are not.

So "keep the rack whole" never stops mattering, but what it protects changes. Spreading the same number
of nodes over many partial racks multiplies the fabric share and fragments the NVLink domains. On
Nscale NC, taking the best 16 nodes per SU from any rack (95 rack fragments) for 1024 GPUs read 79.0 GB/s
against 92.1 on whole racks, and with MNNVL on the job hung at initialisation.

## Why two racks in one SU cost more than two racks in two SUs

Two racks in the same SU exchange their traffic through the same leaf switches, so their flows share
leaf ports and leaf buffers. Two racks in different SUs exchange theirs through the spine, which on a
well-built fabric has more aggregate capacity between leaf groups than one leaf group has inside itself
for this pattern. On Nscale NC at 128 GPUs, two racks in one SU read 130-133 GB/s all-to-all and two
racks in two SUs read 175-180, with the switches pausing the NICs about 200 times more often in the
same-SU case. No NCCL or NIC setting closed that gap; the switches were the limit.

The rule that follows is simple and held at every size tested: **one rack per SU.** The passing 128-GPU
runs used 2 racks in 2 SUs, the 256-GPU runs 4 in 4, the 512-GPU run 8 in 8, and the 1024-GPU run 15 in 15.

## Why the rack *within* each SU still matters

With one rack per SU and identical settings, three different rack sets at 1024 GPUs read 91.1, 93.0 and
94.6 GB/s; one set run twice read 94.51 and 94.61. Adding racks one at a time to a passing 512-GPU job
was not monotonic (102, 71, 82, 95, 83, 92.5 GB/s), and single rounds collapsed on identical nodes. A
node or rack fault would be repeatable; this is not. It is the signature of how ECMP hashing and
adaptive routing place flows on the spine for a given set of endpoints. That is **likely**, not
proven: Rack Status sees the nodes and the leaves, not the spine.

The practical consequence is that a large job's result is a property of its rack set, so the rack set is
part of the configuration and is recorded with the result. Measure a few one-rack-per-SU sets and keep
the best one; the cluster owner should look at the spine so that any set would do.

## Why this is not a congestion-control problem

NIC congestion control (on Spectrum-X, the RTT-based `ztr_rttcc` algorithm) does matter, but as a
setting that has to be right rather than as the limiter. On Nscale NC:

- At 128 and 256 GPUs, CC off measured best and the handover runs used it.
- At 512 and above, CC must be on: off halves 512-GPU all-to-all. The MoE profile beats the site
  profile, which is the deployment guide's recommendation, by about 4% at 1024.
- Once CC is on with the MoE profile, making it less aggressive in four different ways (later reaction,
  a softer first cut, faster recovery, a bigger increase) moved 1024 by under 0.5%. If CC were
  throttling the job, one of those would have helped.
- At 1024 the switches paused the NICs about 400 times less often per second than at 512, with zero ECN
  marks, drops and retransmissions, for a lower result. The job is not losing time to pauses.

The same is true of NCCL settings: once the buffer is right (8 MB, not 16 MB), queue pairs, P2P chunk
size, channel count and adaptive routing together spanned under 2% at 1024. Placement spanned 8%.

## Why the hostname is not the source of truth

Rack letters and hostnames describe where a rack *stands*, not which leaves it is *cabled* to. On Nscale
NC, SU35's racks U26 and X26 stand in the rows of SU20 and SU32, and SU36's T1 in the row of SU33 and SU34, yet every one of
their ports lands on their own SU's leaves. That happened to match the `-suNN` hostname suffix and the
cluster record, but only reading the switch neighbours proved it. The leaves are the ground truth;
LLDP on the node reads them (see the how-to).

## What this means for any cluster

- Treat **placement as the first tuning parameter** and record it with every multi-rack result.
- Keep the `scalable_units` map on the cluster record correct, and verify it against LLDP once per
  cluster. Every placement decision and every handover report is built on it.
- Tune NCCL and congestion control **per job size**, on a placement that is already right. A setting
  measured on a bad rack set measures the rack set.
- A gap that placement and settings cannot close is a switch question (spine capacity, hashing,
  adaptive routing, link state). Hand it to the network owner with the rack sets and job ids that show
  it.
