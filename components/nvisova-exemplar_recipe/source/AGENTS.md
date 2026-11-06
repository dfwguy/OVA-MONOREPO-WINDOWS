# Agent routing and repository rules

This repository is a customer-neutral deployment kit for NVIDIA Exemplar Performance.

## Deployment requests

Read `README.md`, `agent_exemplar_skills.md`, `run_exemplar.md`, `docs/airgap.md` and `docs/acceptance.md`. Follow the handoff phases and continue authorized setup through validation and execution when requested. Obtain missing private inputs from the operator; use secure file references for credentials. Validate upstream support before choosing recipes or scale. Keep deployment inputs and evidence outside Git.

## Repository changes

Read `CONTRIBUTING.md` and `docs/factory.md`. All changes go through a merge request. Use a feature branch, run the local validation contract, publish CI evidence and retain human review/merge. Do not approve or merge your own MR. This kit's CI does not install software on a customer cluster.

Keep documentation and helpers generic. Never add customer identifiers, live inventories, private address literals, historical batch-job snapshots, model images or credentials. Use explicit placeholders in examples and distinguish actual executable helpers from tasks requiring upstream tools or a reviewed platform adapter. Do not claim unsupported hardware or schedulers work universally.

No global HCA count, interface, GID/QoS, GPU scale or telemetry endpoint is a portable default. Preserve official recipe semantics and record diagnostic adaptations. Validate Markdown navigation, image/diagram rendering and cited upstream behavior after documentation changes.

Preparation tools use the Python standard library. Run `python3 -m unittest discover -s tests -v`, `python3 tools/check_repository.py` and `python3 -m compileall -q tools tests` before publication. Never weaken gates simply to pass CI.
