# NVIS-P2P Console

This deployment serves the NVIS-P2P branded build of the official console
compatible with Dragonfly Manager `v2.5.1`. It is available at
`http://192.0.2.3:4300` on the management network and locally at
`http://127.0.0.1:4300`.

Dragonfly core commit `5523218a3710b2d5bc8fbdb0b1473d3a4d64916d`
pins its `manager/console` submodule to console commit
`084b2a8fb6f9432e8998951dfeec50fa5ffd597e`. The static UI is built from that
exact revision with NVIS assets and the CVT black/NVIDIA-green visual system.
The runtime proxies same-origin `/api/v1` and `/oapi/v1` calls to the unchanged
Manager loopback listener.

## Start and verify

```bash
cd /srv/nvis/NVIS-P2P/deploy/console
docker compose build --pull
docker compose up -d
docker compose ps
curl -fsS http://192.0.2.3:4300/nvis-p2p-health
curl -fsS http://192.0.2.3:4300/healthy
```

The listener binds appserver loopback and its management address, but not any
compute-facing `10.41` address. An operator may alternatively use a pinned-host-
key SSH tunnel:

```bash
ssh -N -L 4301:192.0.2.3:4300 appserver
```

Then open `http://localhost:4301`.

## Authentication and bootstrap

Authentication is owned by the Manager, not nginx. The console submits sign-in
to `/api/v1/users/signin`; authenticated API routes use the Manager's JWT/RBAC
middleware and same-origin cookie. No credential, JWT, or session material is
stored in this Compose deployment.

On an empty Manager database, upstream Manager creates a `root` account with a
publicly documented vendor default password. Change it immediately at first
login and store the replacement only in the approved secret manager. This
deployment neither resets nor discovers the current credential. Signup creates
a guest user and does not create another administrator.

Do not expose port 4300 beyond the trusted management network. Manager port
12004 remains loopback-only and is not changed by this deployment.

## Stop

```bash
cd /srv/nvis/NVIS-P2P/deploy/console
docker compose down
```

Stopping the console does not stop or modify Manager, scheduler, seed, Redis, or
PostgreSQL.
