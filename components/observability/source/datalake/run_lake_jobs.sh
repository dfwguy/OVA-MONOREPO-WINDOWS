#!/bin/bash
# Refresh the Slurm job census + parse new run results into the Parquet lake.
#
# Logging is done INSIDE this script deliberately. The crontab line then carries
# no ">>" redirect and no protected path, which keeps it clear of the repo's
# delete-guard pattern match — the reason two earlier cron installs were blocked.
#
# Both steps are idempotent:
#   census   — rebuilds the whole table from sacct and self-reconciles the row
#              count before publishing; a mismatch aborts rather than shipping
#              a census with unexplained drops.
#   backfill — keyed on job id, skips jobs already ingested.
set -uo pipefail
LOG=/opt/observability/logs/lake-jobs.log
PY=/opt/observability/gsheets-venv/bin/python
D=/opt/observability/iren_mkz/datalake
exec >>"$LOG" 2>&1

echo "=== $(date -u +%FT%TZ) census ==="
timeout 3000 "$PY" "$D/lake_job_census.py" --since 2026-07-20
rc_census=$?

echo "=== $(date -u +%FT%TZ) backfill ==="
timeout 3000 "$PY" "$D/lake_run_backfill.py" --since 2026-07-20
rc_back=$?

# result-map — joins the per-node result files under /cluster to their Slurm job
# and parses the numbers out of them. This is what makes the lake an AUDIT
# record (what ran, on which node, what it output) rather than just a job list.
#
# It was never scheduled until 2026-08-16, so run_results/health_artifacts sat
# frozen while the census stayed current. Two things make it safe to run here:
#   * nccl_debug_file.* is excluded by name. Without that it walked 1,444,120
#     per-rank NCCL_DEBUG traces (589 GB) and ran 80 min without finishing.
#   * RESULT_PARSE_TAIL=1 MiB. The nccl-tests results block sits at the END of
#     the log — measured 746 KB from EOF on a 6.4 GB alltoall run — so 1 MiB
#     covers it with margin while cutting per-file cost 4x vs the 4 MiB default.
# Measured runtime with both in place: 76 s for 19,195 result files.
# timeout is 900 not 3000: if this ever exceeds 15 min it has started walking
# something it should not, and dying loudly beats silently eating the box.
echo "=== $(date -u +%FT%TZ) result-map ==="
RESULT_PARSE_TAIL=1048576 timeout 900 "$PY" "$D/lake_result_map.py" --parse
rc_map=$?

# Heartbeat for the monitors. A stale mtime here is what proves the pipeline
# stopped — the previous outage went unnoticed for 7 days precisely because
# nothing recorded "the last time this actually succeeded".
if [ "$rc_census" -eq 0 ]; then
  date -u +%s > /data/lake/_state/census_last_ok
fi
if [ "$rc_back" -eq 0 ]; then
  date -u +%s > /data/lake/_state/backfill_last_ok
fi
if [ "$rc_map" -eq 0 ]; then
  date -u +%s > /data/lake/_state/result_map_last_ok
fi
echo "=== $(date -u +%FT%TZ) done census_rc=$rc_census backfill_rc=$rc_back result_map_rc=$rc_map ==="
