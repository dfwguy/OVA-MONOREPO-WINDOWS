# NVIS-P2P release architecture

Read this when adapting a release or diagnosing component boundaries.

Canonical images are read from an operator-defined control-host directory. Native `dfstore import` makes them durable in an object store and creates persistent Dragonfly tasks. Seed peers may fetch origin content; compute peers are configured without back-to-source and exchange pieces under scheduler control. Node-side `dfstore export` stages, validates size/digest, atomically installs, and writes a receipt.

The web console and operations API belong to the management plane. Manager REST and the operations API should remain loopback-only behind the console proxy. Scheduler/Manager gRPC, seeds, and the object API need compute-fabric reachability. Import credentials stay on the control host; compute nodes receive read-only export credentials.

Preserve object-store data, Redis/database state, seed caches, compute storage/cache, receipts, quarantine, and operation records. The intended compute footprint is `dfdaemon`, `dfget`, `dfstore`, peer config, catalog, sync script, read-only environment, state directories, and two systemd units—not Docker, GPU software, Slurm integration, NHC, or an observability agent.

