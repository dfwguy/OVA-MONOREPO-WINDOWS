# NVIS-P2P Console build provenance

- NVIS release: `2.5.1-nvis.1`
- Upstream Console revision: `084b2a8fb6f9432e8998951dfeec50fa5ffd597e`
- Compatible Dragonfly core revision: `5523218a3710b2d5bc8fbdb0b1473d3a4d64916d`
- Builder base: `node@sha256:3e843c608bb5232f39ecb2b25e41214b958b0795914707374c8acc28487dea17`
- Runtime base: `nginx@sha256:72ba65eb42c10344912a84ff42408db7d34f2feb642204570ab8fc5ffd29f1d3`
- Built image: `sha256:5e0adbafba22a4b7c81472c75837310b870ead387da5c6e8a3dc12abac04b5c6`
- Static manifest: `sha256:807025f8520254111727749f3b002a38dd891a9751415a71905086823d068b8d`
- Static archive: `sha256:44602651c9e9987e71b18bf29633201a9c66e5c527018a4f831078fb3fbe5b1f`
- Reproducibility epoch: `1784603018` (the upstream Console commit timestamp)

The source map is disabled for the production artifact. A second build from
the same tree resolved to the same image ID. The runtime includes the upstream
Apache-2.0 license and NVIS attribution notice.

## Runtime boundary

The Console listens only on appserver loopback (`127.0.0.1:4300`) and its
management address (`192.0.2.3:4300`). Same-origin `/api/` and `/oapi/`
requests proxy to the existing Manager listener at `127.0.0.1:12004`.
Authentication, JWT/RBAC, credential storage, and first-login behavior remain
owned by and compatible with Manager.

## Verification record

- Both health endpoints returned HTTP 200.
- Manager `/healthy` returned HTTP 200 through the proxy.
- An unauthenticated `/api/v1/clusters` request returned HTTP 401.
- `/signin`, the versioned JavaScript, favicon, and SPA fallback returned HTTP 200.
- Every emitted file passed the bundled `SHA256SUMS` manifest.
- Emitted visible branding is NVIS-P2P. The two retained `dragonfly` strings
  are non-brand behavior/attribution: the required upstream first-login
  comparison and the upstream client documentation URL.
- The container runs as UID/GID `101:101`, with a read-only root filesystem,
  all Linux capabilities dropped, and `no-new-privileges` enabled.
