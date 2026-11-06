# Portable Slurm evidence collector

Read ../README.md, ../IMPLEMENTATION_HANDOFF.md and ../AGENT_HANDOFF.md before deployment.
Configuration is selected by SLURM_HISTORY_CONFIG; SQLite and raw payloads persist in the configured root.
This is an adapted implementation, separately tested with fixtures. It has not been commissioned on another customer cluster.
The original deployed implementation remains under ../reference/deployed-app/.
