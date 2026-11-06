---
diataxis: how-to
description: Read before any multi-rack NCCL or training run you will tune or hand over, to choose racks that let the fabric reach its best all-to-all.
---

# How to place a multi-rack job for best collective performance

Choose the racks for a multi-rack job so that its result measures the fabric and the settings, not an
unlucky rack set. Do this before tuning anything. Why each step matters is in
[rack placement and collective performance](../explanation/rack-placement-and-collective-performance.md).

## 1. Read the cluster's SU map

The cluster record's `scalable_units` says which racks share leaf switches. Open
**Platform › Projects & Clusters**, or read it from the API:

```bash
nvrs -o json api GET /api/catalog/projects/<project> \
  | jq -r '(.item // .project // .).clusters[] | select(.id=="<cluster>") | .scalable_units[] | "\(.label) \(.racks|join(" "))"'
```

An empty list means the map is derived by chunking racks in inventory order, which is only right if the
floor was built in that order. Check it in the next step either way.

## 2. Verify the map against the leaves

Hostnames and rack letters say where a rack stands, not where it is cabled. Read the leaf behind each
plane port with LLDP on one or two nodes per rack, fanned out from the cluster's execution host:

```bash
clush -w <node-in-each-rack> \
  'sudo -n lldpctl -f keyvalue | grep -E "^lldp\.eth_p[0-9]+_r[0-9]+\.chassis\.name="' \
  | awk -F'[:=]' '{print $1, $NF}' | sort -u
```

Every node of a rack must land on the same leaf set, no leaf may serve two SUs, and each rack's leaf
set must match its SU on the record. Fix the record when it disagrees. On Nscale NC, leaves are named
`<site>-swi-bel<rail>-su<NN>-pl<plane>-nc...`, 16 per SU. If `lldpctl` is absent, the switch team's
cabling map is the fallback, not the hostname.

## 3. Choose the racks

1. Work out the racks: GPUs / (GPUs per node x nodes used per rack). Use whole racks, 16-18 nodes of an
   NVL72, never a few nodes from many racks.
2. Take **one rack per SU**. Never two racks of one SU in the same job while another SU has a usable
   rack.
3. In each SU, pick the rack with the most healthy idle nodes; break ties with the per-node NCCL
   results under **Analytics & Benchmarks › Analytics** or the bring-up NCCL scores.
4. Leave out SUs with links flapping or ports down: a run that touches one stalls or reads low on that
   SU's rail.
5. Spread the node count evenly across racks; a rack gives fewer nodes only when it has fewer healthy.

## 4. Set the configuration for the job size

1. Put the job size's NCCL variables from
   [collective settings by job size](../reference/collective-settings-by-job-size.md) on the cluster
   record's `nccl_env`: the span list `multirack` for all collectives, and
   `collectives.alltoall.multirack` for the all-to-all run only.
2. Set NIC congestion control for the job size on every node in the job (it is a NIC register, not a
   Rack Status setting) and read it back. Restore the site profile when the run is done.

## 5. Run, and judge the result by its rounds

Launch from **Compute › Multirack operations** (or `nvrs run`) so the run, its racks and its environment
are recorded. Then read the per-round bus bandwidth in the job log:

- Rounds within about 0.5% of each other: the result belongs to this rack set and these settings.
- One round collapsed on the same nodes (for example 95, 95, 60): flow placement on the spine, not a
  node. Do not change settings; rerun or change racks.
- Below target with steady rounds: keep the settings and try another one-rack-per-SU set, varying the
  rack within each SU. Keep the best set and its job id.

## 6. Record the placement with the result

The rack set is part of the configuration. **Analytics & Benchmarks › Handover Reports** lists the racks
and SUs of every run; name the set in any report that quotes the number. If no one-rack-per-SU set
reaches the target, hand the network owner the best and worst sets with their job ids: the remaining
gap is in the spine, which Rack Status cannot see.
