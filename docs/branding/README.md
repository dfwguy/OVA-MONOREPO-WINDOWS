# NVIDIA OVA branding assets

The banner extends the existing Exemplar repository's NVIDIA green (`#76b900`) and black layout. The NVIDIA eye and wordmark paths are reused unchanged from Rack Status's existing `static/nvidia-brand.svg`. The current NVIS P2P console mark was inspected as a visual reference; there was no assumed P2P root README. These assets do not redraw the NVIDIA logo or create a replacement corporate mark.

- `ova-monorepo-banner.svg`: landing-page hero.
- `ova-monorepo-mark.svg`: compact NVIDIA and project-title lockup.
- `ova-monorepo-avatar.png`: 512×512 GitLab project avatar (22 KB), rendered from `ova-monorepo-avatar.svg` with the same unchanged NVIDIA vector.
- `architecture.gif`: looping control-flow illustration, 40 frames, 4.8 seconds.
- `architecture.svg`: static, accessible diagram fallback.
- `architecture-status.json`: editable measured placement/status text.
- `ASSET_PROVENANCE.json`: source paths/hashes, rendering metadata and output hashes.

Edit the status JSON after reconciling runtime evidence, then run `python tools/render_branding.py` from an environment with Playwright, Chromium and Pillow. Set `OVA_CHROMIUM_EXECUTABLE` if using an approved preinstalled Chromium. The animation indicates traffic flow only, not validation success. Status text must retain unresolved placement exceptions until acceptance evidence closes them.

No landing page is published by this renderer. Review the final README only after build and validation results are reconciled.
