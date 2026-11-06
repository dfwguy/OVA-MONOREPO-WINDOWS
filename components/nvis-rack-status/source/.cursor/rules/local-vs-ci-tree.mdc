---
description: Why "it passes locally" says nothing about CI — untracked files, missing tools, and the unbuilt frontend
alwaysApply: true
---

# Your working tree is a superset of the commit, and of any CI checkout

A local pass proves the code works **with whatever else is lying around your tree**. CI starts from
a fresh clone of tracked files only, in a slim image. Three different versions of this gap turned
the pipeline red on 2026-08-21 alone, each with a green local suite — and a fourth on 2026-08-24,
where the difference was not pass/fail at all but a *coverage percentage* (§3).

## 1. The frontend is not built in CI — this is the one that bites tests

`static/spa/` is a gitignored **build artifact**: present in every developer's tree, absent from
every CI checkout. So four routes behave differently:

| Route | Local (built) | CI (not built) |
|---|---|---|
| `/`, `/index.html`, `/spa/`, `/spa/index.html` | `200` | **`503`, `text/html`** |

That 503 is deliberate, not a bug: `api/_common.serve_spa_asset` answers a missing bundle with a
human-readable *HTML* page ("Frontend not built") because the audience is somebody in a browser,
and 503 because an unbuilt frontend is unavailability rather than a server fault. Its contract is
pinned by `test_app_api.py::test_missing_shell_503s_instead_of_raising`.

**It is the only deliberate non-JSON 5xx in the product.** Every other error path returns JSON — a
JSON body carrying status 500 is in fact the dominant convention here (100 sites against 14 using
502). So a test that walks the URL map and asserts "any 5xx must be JSON" passes locally and fails
in CI on exactly these four routes. That happened; eight tests.

Any test that iterates `app.url_map` must tolerate both states — see `_assert_did_not_crash` in
`backend/tests/test_endpoint_smoke.py`, which accepts a 503 whose body contains `Frontend not
built`. `test_web_auth_gate.py`'s `spa_index` fixture exists for the same reason.

Do **not** "fix" this by building the frontend in the python-test job. That hides the divergence
instead of removing it, and the SPA-missing path is real behaviour on any backend-only deployment.

## 2. A committed import can name an untracked module

`app.py` did `from audit import request_hook` while `request_hook.py` had never been `git add`ed.
Locally: 1686 tests green. In CI: `ImportError` and 34 collection errors. `git status` showed the
untracked file next to twenty other lines nobody reads twice.

## 3. Coverage is not the same number in both trees

`backend/universal_parser.py` measures **52.8% in a working tree and 48.1% from a clean checkout** —
a test opportunistically picks up untracked sample data that happens to be lying around. That is
below the 50% floor `bin/check-coverage-floor.py` enforces, so the gate's exception list was seeded
from a local run, passed locally, and failed on the first push.

Comparing the two trees moved **13 files, by up to 3.0 points**. Only that one crossed the floor, but
the lesson generalises: **any per-file coverage number you write down must come from a tracked-only
run**, because that is the tree the gate runs in.

```bash
# reproduce CI's tree, then measure in it
git ls-tree --name-only HEAD | grep -v -e '^\.' -e '^frontend$' \
  | xargs git archive HEAD -- | tar -x -C /tmp/citree
cp .coveragerc /tmp/citree/ && cd /tmp/citree
python -m pytest backend/tests -q --cov --cov-config=.coveragerc --cov-report=json:cov.json
```

The gate reports a listed file clearing the floor as information, not as an instruction — it tells
you to confirm in a tracked-only tree first, because "remove this entry" is wrong advice when the
number came from your own working tree.

## 4. The job image is not your shell — and it cuts both ways

`python:3.12-slim` has **no `git`**: the runner clones in a separate helper container, so a script
that shelled out to `git archive` died with `git: command not found`. Check `command -v <tool>`
before depending on anything that is not Python or the stdlib.

**It happened again on 2026-09-09, and the second time taught the more important half.** The
`sources-of-truth` gate ran `git diff --exit-code` to show a contributor *which* action had
changed. It never passed once — six pipelines — and because it sits in `lint`, every downstream job
was skipped, so the whole pipeline was red on a gate that could not run.

The real damage was not the failure but the **diagnosis**. The call was inside `if ! git diff …`,
so the missing binary's non-zero exit took the same branch as a real difference: every run printed
*"a generated source of truth is stale — an API route was added, removed or renamed"* and blamed
the documents. The documents were never stale. **An absent tool and a genuine failure must not be
indistinguishable** — that is what turns a five-minute fix into a hunt for a route nobody changed.

So: prefer the stdlib over the binary. The repair was to teach the generators' own `--check` mode
to print a `difflib` unified diff, which was the only thing git was there for, and drop git
entirely. `backend/tests/test_ci_job_tooling.py` now fails the build if any job on a slim image
invokes `git`, `curl` or `make` — the check a developer's shell can never perform, because git is
always on *their* PATH.

The reverse also happens. macOS ships **bash 3.2** as `/bin/bash`, while CI images carry bash 5, so
`mapfile`, `declare -A` and `${var,,}` are all fine on a runner and fail on the workstation. For
anything under `bin/` that a developer runs, prefer constructs both shells have — `tar --exclude`
over building an array, for instance. `bin/scripts/*` is the deliberate exception: those execute on
the cluster head node (Linux, bash 4+), which is why ~28 of them use `mapfile` and why
`run-validation-preset.sh` guards with an explicit "brew install bash" message instead.

**The same gap is why the suites do not run on the Mac.** The tests drive those `bin/scripts/*` with
whatever `bash` and `stat` are on the PATH, so on macOS they fail on bash 3.2 and BSD `stat` where
no node, app server or runner would. Run them in the CI images, which is what `bin/ci-local.sh`
exists for, and treat a Mac-only failure as unanswered rather than as noise.

## 5. Two unit tiers cannot see what happens where they meet — that is the `integration` stage

`backend/tests/` is backend-only and never has a built frontend. `frontend/src/**/*.test.tsx` is
frontend-only and never has a backend. **A defect that exists only in the seam between them is
invisible to both**, and this product has shipped three:

- assets served `Transfer-Encoding: chunked`, because `send_file` streams and Flask-Compress's
 streaming branch pops `Content-Length` — over TLS Chrome retries and the dashboard renders
 unstyled. Fixed three times, recurred twice;
- an `index.html` referencing content-hashed chunks absent from `assets/` — a blank page with
 `GET /login` returning 200 throughout (the 2026-08-12 hour-long outage);
- the SPA-missing 503 contract, which only means something if the *built* case is tested too.

So there is a third tier: **`backend/tests/integration/`**, run by the `integration-test` job against
the real bundle `frontend-test` already builds for its offline check and publishes as an artifact, so
it runs only after that job's tests pass. `python-test` passes `--ignore=backend/tests/integration`.

Three rules for it, each from a mistake already made here:

- **Never let an integration case be skippable in its own job.** Every test in that directory is
 guarded on `static/spa/index.html`, so a missing artifact would turn the whole job green without
 running anything. `integration-test` therefore `test -f`s the artifact and exits 1 if it is absent.
 The first version of the chunking test lived in the unit tier and skipped in CI for exactly this
 reason — a gate that never ran, which is how the bug survived two "fixes".
- **Assert headers, not browser symptoms.** The chunked-body failure is a race between the terminal
 chunk and `close_notify`; switching Werkzeug→gunicorn narrowed the race without changing the
 chunking at all (20 assets measured chunked *under gunicorn*). `Content-Length` is deterministic.
- **Send `Accept-Encoding: br` explicitly.** curl sends none by default, so it never requests brotli,
 never reaches the streaming branch, and tolerates the EOF pattern Chrome rejects. Every curl check
 passed while the browser was broken. A verification tool that cannot observe the defect is not
 verification.

Add a test to the integration tier when it needs the built bundle; add it to `backend/tests/` when it
does not, because that job is far faster and gates every push.

## Before pushing anything that touches routes, imports, or scripts

The reference run is every test job in the CI images, on the commit's tracked files only:

```bash
t=$(mktemp -d) && git archive HEAD | tar -x -C "$t" && bin/ci-local.sh all "$t"
```

That is this file's whole argument in one command: CI's images, CI's tree. For a faster check
first:

```bash
bin/check-tracked-tree.sh              # tracked files only, imports all 134 modules (~3s)
bin/check-tracked-tree.sh --with-tests # ...then the suite, in a tree with NO build artifacts (host shell)
```

`--with-tests` runs pytest in your shell, so on a Mac it inherits bash 3.2 and BSD `stat`. It
proves the tree is complete, not that the scripts pass. The `ci-local.sh` run above proves both.

The export contains only tracked files, so it reproduces the runner's tree — including the absent
`static/spa/` — without needing a runner. To reproduce just the frontend case by hand:

```bash
mv static/spa/index.html /tmp/ && python -m pytest backend/tests -q; mv /tmp/index.html static/spa/
```
