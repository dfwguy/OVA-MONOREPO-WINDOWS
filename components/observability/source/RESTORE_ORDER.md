# Ordered greenfield restore

1. Verify `MANIFEST.sha256` and review every value in
   `site-placeholders.env.example`. Store real passwords/tokens in the
   customer secret provider, never in this tree.
2. Create storage directories for VictoriaMetrics, Prometheus, Loki, Alloy,
   and Grafana. Replace IREN_MKZ-specific `/cluster`, `/cm`, Docker bridge,
   Slurm, validation-log, and lake paths with customer paths.
3. Install node agent binaries from approved vendor builds. Install
   `node-agents/systemd/*.service`, their drop-ins, and
   `node-agents/config/dcgm-counters.csv` into the golden node image. Validate
   on one canary before fleet rollout.
4. Create the least-privilege Redfish and UFM service identities. Install the
   exporter sources and units from `exporters/`; generate the site Redfish
   target CSV with the included generator or customer inventory. Do not add
   credentials unless an approved secret binding exists.
5. Install the Slurm, fleet-DCGM, head-node, single-node, and validation
   exporters. Adjust `SLURM_BIN`, `SLURM_CONF`, validation roots, textfile
   paths, and resource limits. Enable their timers only after a manual run
   succeeds.
6. Install `datalake/` source and compose files. Create empty customer lake
   storage and verify minimum-free-space guards before enabling collectors.
7. Start VictoriaMetrics using `core/victoriametrics.compose.yml`.
8. Copy `core/` to the desired installation root, create a protected
   `core.env` containing `GF_SECURITY_ADMIN_PASSWORD`, validate with
   `docker compose config`, then start Prometheus, Loki, Grafana, and Alloy.
9. Materialize the file-SD target JSON referenced by
   `core/prometheus/prometheus.yml`; do not copy runtime target lists from the
   source cluster. Verify all intended targets before enabling alerting.
10. Restore Grafana. Preferred API path:

    ```bash
    export GRAFANA_API_TOKEN='<read-from-secret-provider>'
    ./restore/import_grafana.py --url http://127.0.0.1:3000 --dry-run
    ./restore/import_grafana.py --url http://127.0.0.1:3000
    ./tools/export_live_grafana.py --url http://127.0.0.1:3000 --output /tmp/post-restore
    ```

    Compare the post-restore dashboard UID set to
    `dashboard-inventory.tsv`. Rerun the import to prove idempotency.
11. Alternatively, mount `grafana-live/dashboards` as
    `/etc/grafana/live-dashboards` and install
    `grafana-live/provisioning/dashboards-live.yaml`.
12. Replace sanitized contact-point placeholders manually, verify notification
    policy routing, and send a test notification. No secret value is included.
13. Validate Prometheus targets, VM ingestion/query, Loki write/query, Alloy
    remote write, exporter cardinality, lake free-space guards, dashboard
    queries, and restore counts before production cutover.
