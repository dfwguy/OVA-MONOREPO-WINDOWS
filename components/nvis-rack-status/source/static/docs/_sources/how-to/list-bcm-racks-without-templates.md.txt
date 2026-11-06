---
diataxis: how-to
description: Show saved BCM racks and their real nodes in translate mode, without rack or hostname naming templates.
---

# How to list saved BCM racks without naming templates

Use this procedure for a BCM cluster whose compute hostnames do not contain their
rack names, such as racks `F41` and `F42` containing `dgx-b300-*` nodes. It applies
whichever scheduler the cluster runs: placement is the cluster manager's answer, read
in **Translate** mode. The app's configured connection must reach the BCM head.

## 1. Configure the cluster

1. Open **Projects** and edit the cluster in your project.
2. Set **Cluster manager** to **BCM** and **Scheduler** to the one the cluster runs.
   Select the platform that matches the hardware, such as **DGX B300**.
3. Set **Rack mapping** to **Translate (provider rack/slot)**.
4. Leave **Rack id template** empty to use BCM's saved rack names. With a template
   set, the template decides which saved racks are dashboard racks, and a rack it does
   not match is not shown. Node/CT and NVSwitch naming templates are not used in this mode.
5. Leave **Scalable Unit translation** empty unless you have an explicit SU map. It
   groups racks for the floor view and does not control rack discovery.
6. Check the SSH connection, **Remote base path**, and **Log directory** for this
   cluster, then click **Save**. Use **Set active** to select it.

## 2. Verify the racks and nodes

Open **Compute → Racks** and wait for inventory to load. Compare the rack names
with this read-only command on the BCM head:

```bash
cmsh --tty --nocolor -c 'rack; list -f name'
```

Open each rack and compare its node list with BCM placement and the Slurm roster:

```bash
cmsh -c 'device; foreach -t physicalnode (get hostname; get rack)'
sinfo -N -h -o %N
```

If BCM assigns `dgx-b300-01` and `dgx-b300-02` to `F41`, and `dgx-b300-03` and
`dgx-b300-04` to `F42`, each rack should show two nodes. A saved empty rack should
show no nodes. Rack capacity and physical unit positions do not create additional
node entries.

If a rack is missing, check the active cluster, the selections above (BCM and
Translate), and that **Rack id template** is empty. If its nodes are missing, correct
their BCM rack assignments. Nodes without placement
remain visible as **Unassigned** in **Compute → Nodes**.

## 3. Verify a multi-rack launch

Select the racks for an NCCL launch and enable **Dry run**. Review the command's
`--nodelist`: it should contain the real compute hostnames, including all four
nodes in the example above. A rack with no placed node is refused
(`no inventory nodes placed in rack …`) rather than expanded from a template.

The launch automatically passes its resolved log directory as `RACK_JOB_LOG_DIR`
to the remote script. Check the dry-run's `sbatch --output` path against the launch
log directory. An explicit `RACK_JOB_LOG_DIR` in the launch's extra environment
overrides this default.

For the difference between saved placement and hostname parsing, see
[Geometry and hostnames](../explanation/geometry-and-hostnames.md). For a cluster
without rack placement, use **Pool** and select explicit node hostnames; see
[Projects and clusters](../reference/catalog/projects-and-clusters.md).
