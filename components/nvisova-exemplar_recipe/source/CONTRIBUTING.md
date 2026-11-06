# Contributing

All changes go through a merge request. Read [the factory contract](docs/factory.md) and [AGENTS.md](AGENTS.md) before editing.

Keep this kit generic and reproducible: use deployment placeholders, immutable upstream provenance, secure credential references and supported hardware/scale boundaries. Update README navigation and agent/runbook instructions together when their contracts change.

Use a feature branch. Validate locally:

```bash
python3 -m unittest discover -s tests -v
python3 tools/check_repository.py
python3 -m compileall -q tools tests
```

Inspect changed Markdown links/diagrams and effective GitLab CI configuration. Publish the MR with exact commit identity, validation evidence, supported scope and remaining live-cluster limitations. Humans review and merge; agents do not approve or merge. Do not weaken publication checks, add production credentials to branch pipelines, or describe CPU-only CI as cluster acceptance.
