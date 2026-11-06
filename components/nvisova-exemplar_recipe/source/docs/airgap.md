# Air-gapped preparation and software delivery

Return to [README](../README.md) or continue with [the execution runbook](../run_exemplar.md). This procedure prepares a complete selected-workload closure on an authorized connected system and installs it inside the target boundary. It does not grant redistribution rights for containers/models or supply a universal offline switch to the upstream installer.

## 1. Establish the transfer contract

Record target CPU architecture, Linux distribution/version, kernel, GPU type/driver compatibility, Python ABI, container runtime/version and install paths. Select the pinned upstream release and exact workload tuples first. Use a staging system matching these requirements or explicitly build/download the target artifacts in a compatible environment.

The operator supplies the authorized NGC account, Hugging Face token/gated access, package sources, allowed artifact transfer mechanism, target internal registry/store if used and retention policy. Credentials remain in secure provisioning systems; they do not enter the software payload. Confirm that the deployment agent can execute within the restricted target through an approved local runtime or management path.

| Network condition | Delivery plan |
| --- | --- |
| Controller connected; compute isolated | Download/install on controller, then share or stage all required runtime content to compute |
| Target accesses an internal registry/mirror only | Mirror exact pinned artifacts and use reviewed internal references; verify identity after mirroring |
| Entire target isolated | Acquire on connected staging; transfer versioned file payload through approved boundary; install/test offline |

An image store does not replace Python/model/source dependency closure. Identify every network dependency of installation **and launch**.

## 2. Resolve and materialize sources

Clone the official repository and checkout the full approved commit. Materialize LFS objects, submodules, install-time workload helper repositories and recipe-specific source assets. Record each revision. Inspect the selected setup scripts for network fetches and source builds.

Export a working tree without `.git` credential/configuration metadata. A source bundle for transfer must contain file contents, not LFS pointers. Preserve required executable flags. Keep source/license/provenance records alongside distributable content. Generated configuration must use the target paths, account/partition and architecture.

If the upstream installer assumes internet access and has no supported offline path, use its documented manual/local installation components in a reviewed adapter or pre-materialize the dependencies it expects. Do not invent a `--offline` flag or claim a copied source checkout alone completes installation.

## 3. Download the exact containers

Resolve the container reference from selected workload metadata, including GPU-dependent image selection and target architecture. Authenticate through the approved runtime credential file. Record the immutable registry digest, source URI, platform and license/entitlement status.

For the Enroot/Pyxis path, use a compatible connected Enroot host to import the image into the format the workload expects:

```bash
enroot import --output "$IMAGE_OUTPUT" "$ENROOT_IMAGE_URI"
sha256sum "$IMAGE_OUTPUT"
```

Set the URI using the pinned recipe and installed Enroot registry syntax. A typical URI shape is `docker://nvcr.io#<organization>/<image>:<pinned-tag>`; use supported digest syntax where available or verify tag resolution before/after import. Keep the final artifact filename consistent with upstream expectations. The local SquashFS file's SHA-256 differs from the registry digest and must be recorded separately.

Allow scratch capacity for layer extraction/conversion. Match the compute architecture even if staging hardware differs; do not assume an import tool selected the target architecture. Verify image metadata and a runtime startup on a compatible system. Transferring a Docker tar and changing its extension is not an Enroot conversion.

An internal OCI registry is an alternative when the target can reach it and the reviewed runtime path supports it. Preserve the platform manifest/digest and adapt references without changing container contents or recipe semantics. Verify trust/authentication within the target; do not embed registry credentials in the image catalog.

## 4. Materialize model metadata and required data

For each selected workload identify every model repository/revision and whether it needs config/tokenizer only, pretrained weights, datasets or checkpoints. Obtain gated access before download. Most standard pretraining metadata can be staged without downloading all pretrained weight tensors; validate this against the exact recipe.

Use a compatible installed Hugging Face client on staging with secure local authentication. Pin revisions and explicitly choose required files when supported. Record repository ID/revision, file set and artifact hashes. Validate tokenizer/config loading using the workload's actual library versions.

Hugging Face caches commonly have `snapshots/` links into `blobs/`. Preserve the complete required cache structure and internal relative symlinks, or export self-contained files through a supported client method and adapt the lookup under review. Do not copy only snapshot links or copy HF token/stored-token files. Keep the model cache separate from credential directories.

Set the target's intended `HF_HOME`/hub cache path and mount it inside the workload container. Validate these settings in the generated execution environment rather than only the controller shell. For an offline verification process, set supported offline controls such as `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` where the installed libraries honor them. These controls prevent supported library network attempts; they do not fix missing cache entries or arbitrary network fetches in setup scripts.

See the [official cache layout documentation](https://huggingface.co/docs/huggingface_hub/guides/manage-cache). Test every selected workload's metadata path with outbound connectivity unavailable.

## 5. Build Python and operating-system closure

Prepare the controller interpreter/tooling and every workload-specific Python environment required outside containers. Resolve lockfiles/requirements from the pinned source. Retain hashes/version provenance. Download compatible wheels, build native extensions in a compatible environment where needed and include build prerequisites for any unavoidable source installation.

For an ordinary pip-compatible locked requirements file, a connected staging flow may use:

```bash
python3 -m pip download --dest "$WHEELHOUSE" -r "$LOCKED_REQUIREMENTS"
```

Then, on the matching target environment:

```bash
python3 -m pip install --no-index --find-links "$WHEELHOUSE" -r "$LOCKED_REQUIREMENTS"
```

These commands are a pattern for compatible requirements, not a replacement for release-specific `uv`/project installation steps. A staging interpreter can resolve wheels for its own ABI/platform; select the target explicitly or use a matching staging environment. Include dependencies requested dynamically by build backends. When a lockfile supports hash enforcement, retain and enforce it.

Do not assume Python virtual environments are relocatable. Interpreter links, entry-point shebangs, native libraries and absolute paths must work at the final target location. Prefer reproducible offline creation from the approved closure; if transferring an environment, preserve its required path and verify imports/entry points on target.

Prepare the complete OS/runtime package dependency closure for the target distro/kernel: Slurm/PMIx where in scope, Enroot/Pyxis, required hooks and shared libraries, GPU/RDMA/libfabric integration and approved platform dependencies. Use the platform's package mirror/repository process. Secure authentication material is provisioned independently. Do not ship another cluster's system configuration or boot bundle.

## 6. Assemble the delivery directory

Use a reviewed layout such as:

```text
payload/
├── source/           Exported pinned repositories and source provenance
├── images/           Target-architecture runtime images and image catalog
├── hf-cache/         Required metadata/blobs with internal file links
├── wheels/           Locked compatible Python dependency closure
├── packages/         Approved target OS/runtime package closure
└── configuration/    Non-secret target configuration and installation notes
payload-manifest.json # Stored outside payload/
```

Record source image URI/digest/platform and local artifact filename/hash in a non-secret catalog. Record source commits, release identifiers, package versions and license notes. Do not place tokens, `.credentials`, `.netrc`, secret environment files, private keys, scheduler keys or credential-bearing Git metadata here.

Run the preparation helper and the factory's additional scans:

```bash
python3 tools/prepare.py manifest "$PAYLOAD_ROOT" "$PAYLOAD_MANIFEST"
python3 tools/prepare.py verify "$PAYLOAD_ROOT" "$PAYLOAD_MANIFEST"
```

The manifest helper rejects credential-like paths, external links, directory links and common credential patterns in small files. It hashes every file and records executable flags and internal symlink targets. It is not a complete secret/malware or license scanner; run those checks separately, especially on generated configuration, large packages and images. Obtain transfer/classification attestation through the established factory/operator workflow rather than inventing it.

## 7. Transfer and install inside the boundary

Use the approved transfer path and preserve bytes, modes and internal relative links. Protect the manifest's origin independently: if an attacker can replace both payload and manifest, hashes alone do not establish authenticity. Use the organization's approved signing/trusted-transfer process when applicable.

Verify the destination before using artifacts. Install packages with networking unavailable and from the approved local closure. Create interpreter/workload environments, configure runtime/scheduler integration and run supported local installation/setup components. Reconcile target paths with the generated upstream config.

For shared storage, prove compute-side visibility; for node-local storage, verify every intended recipient and retain its receipt. The same local pathname on two nodes does not establish shared storage. If an approved distribution system adopts pre-existing matching images, keep fresh verification receipts rather than retransferring them.

Optional NVIS P2P delivery requires an approved release, platform-specific deployment configuration and authorization. Verify origin objects, destination images and per-node receipts. Neither server health nor a catalog entry proves compute readiness. This kit does not install or require a particular P2P release.

## 8. Rehearse with downloads unavailable

Use an approved no-egress test environment or an already isolated target; do not mutate production firewall policy just to test the guide.

1. Verify the entire delivered manifest.
2. Run CLI help/list and workload environment imports from target paths.
3. Start the expected container through the actual Slurm/Pyxis path.
4. Check GPU/RDMA/provider visibility, mounts and model config/tokenizer load.
5. Inspect installer/setup/launch output for missing Git, package, registry or HF fetches.
6. Run the permitted small communication/recipe canary, then full readiness gates.
7. Archive required logs with no dependency on external services.

A dry-run often does not execute dependency loading. Do not treat it as complete offline acceptance. Any late fetch is a missing closure item: acquire it on staging, rebuild the manifest and repeat affected checks. Keep failure evidence instead of bypassing authentication or disabling verification.

## 9. Update and rollback

Use versioned payloads and installations; retain a previously verified version and its manifest. A new image/source/package/configuration changes identity and requires affected readiness checks again. Do not update files underneath an active benchmark. Roll back through the approved version-selection/install procedure and verify services, paths and artifacts afterward. Preserve old attempt/results directories and record which version each run used.
