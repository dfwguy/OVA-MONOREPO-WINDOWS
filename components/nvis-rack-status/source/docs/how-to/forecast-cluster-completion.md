---
diataxis: how-to
description: Read when validation will finish from the Cluster Forecast, give it history to measure from, and publish it as a static page.
---

# How to forecast when the cluster finishes validation

Find out when every node, rack and scalable unit will have passed validation, from the pace the
repairs have actually been running at, and publish that answer where the cluster cannot be reached.

## 1. Leave out what is not yours to validate

A scalable unit with a handover date is left out of the forecast, its nodes counted apart. Skip
this step if nothing has been handed over.

1. Open **Platform › Projects & Clusters** and edit the cluster.
2. Under **Scalable Unit translation**, set **Handed over** on each SU the customer now has.
3. Save.

SUs that are placed but where no node has run a stage yet are listed as **not started** and get no
date. Each one joins the forecast when its first node runs a stage.

A node's Stage 2 is a bring-up framework verdict. If the cluster runs that framework, turn on **Runs
the bring-up framework** in the same cluster editor; it lives under the cluster's root
(`<root>/bringup`) unless **Bring-up home** overrides it, and its job is **Stage 2 bring-up job** if
it is not `llm-pretrain-solo`. If the cluster does not run it, leave the switch off: the forecast then
passes a node on Stage 1 alone and says so at the bottom of the page.

The forecast takes the cluster's shape as it finds it. With no SU map it forecasts its racks as one
group and has no SU milestones; on a pool cluster with no racks it forecasts nodes only.

## 2. Give it history to measure the pace from

Rack Status records each scalable unit's progress every hour, from the moment it runs this version.
The forecast needs a sample at least a day old that covers the same nodes as today, so on its own it
starts projecting dates the day after it is installed.

If progress was tracked before that, import it so the forecast works from the first day:

1. Write a CSV with one fleet-level row per sample, counting only the SUs that were validating:

   ```text
   sampled_at,nodes,nodes_passed,racks,racks_passed
   2026-10-16T15:58:00Z,2178,1694,121,31
   ```

2. Check it without writing anything:

   ```bash
   python backend/cli.py import-progress history.csv --dry-run
   ```

3. Import it. On a container deployment, copy the file into the container and run the same command
   there with `docker exec`:

   ```bash
   python backend/cli.py import-progress history.csv
   ```

The rows go to the active cluster unless you pass `--cluster-key PROJECT/CLUSTER`. Importing the
same file again replaces its rows rather than adding to them. Imported history is drawn dashed on
the page.

## 3. Read the forecast

Open **Analytics & Benchmarks › Cluster Forecast**. Two columns of dates sit side by side:

- **Current pace** keeps repairs returning nodes at the measured daily rate until none are left.
- **Slowing tail** lets the backlog shrink by the same fraction each day, so the hardest nodes come
  back last. Treat it as the later bound, and as pessimistic for an SU held by one fabric fault.

Open a scalable unit in the table to see which racks it is waiting on and how many nodes each is
missing. A rack showing **ready** has every node passed and up, and only needs its rack runs.

If the page shows where things stand but no dates, its last paragraph says why: usually that no
sample from one to seven days ago covers today's nodes. The same paragraph shows the sampler's last
check and what came of it, including why it skipped (the cluster unreachable, its snapshot stale,
Stage 2 verdicts still loading).

Rack Status observes one cluster at a time, the active one, and only that cluster is sampled. A
cluster that was not active for a stretch has no samples for it, and its pace needs a sample from
one to seven days ago once it is active again.

## 4. Publish it

1. Choose **Download static page**. You get `cluster-forecast.html`: one file with the page, its
   styles and fonts, and today's data. It opens from disk and never calls back to Rack Status.
2. On Linkify, open the site, choose **Deploy**, and drop the file. Restrict the site to the
   people who should see this customer's fleet.

The same file is served at `GET /api/cluster-forecast/site.html` for scripts, and the data at
`GET /api/cluster-forecast`. Both need the `report.forecast:read` action. On a deployment installed
before this report existed, administrators get that action from
`python backend/cli.py reconcile-admin-policy`.

## Tune it

- `RACK_FORECAST_SAMPLE_INTERVAL_SEC` sets how often progress is sampled (default an hour; `0`
  stops sampling).
- `RACK_FORECAST_WINDOW_DAYS` sets how far back the pace looks for its baseline (default seven days).
