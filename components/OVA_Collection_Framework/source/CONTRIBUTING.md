# Contributing

All changes go through a merge request. Follow [factory publication](docs/factory.md), run the local validation commands from [README](README.md), and retain exact-SHA evidence. Humans review, approve and merge. Fix failures without disabling publication policy or tests.

Keep source and examples cluster agnostic. Use synthetic fixtures in temporary directories, never production state. Changes to data capture, scheduler integration, auth, deployment or export require behavior tests at their failure boundaries. Document target-specific source coverage, reboot and performance limits without presenting them as tested universally.
