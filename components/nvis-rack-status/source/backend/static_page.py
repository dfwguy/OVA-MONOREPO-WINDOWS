# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""A report published as one HTML file, with its dataset written into it.

The deployment tracker and the cluster forecast each have a second frontend build that emits a
single self-contained page (``frontend/vite.static-page.ts``): script, styles and fonts inlined,
because a page with sibling assets renders white when opened from disk -- browsers refuse module
scripts and fonts from ``file://``. The page reads its dataset from one element that the bundle
ships holding ``null``; this module writes the dataset into it. Nothing on the page calls back, so
the file can be mailed, opened locally, or uploaded to Linkify as it is.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class SiteBundleMissing(RuntimeError):
    """The report's static bundle was not built into this deployment."""


def data_element(element_id: str, body: str = "null") -> str:
    """The data element exactly as the bundle ships it (``body`` ``null``) or as it is filled."""
    return f'<script id="{element_id}" type="application/json">{body}</script>'


def embed(index_html: str, dataset: Mapping[str, Any], element_id: str, *, name: str = "report") -> str:
    """``index.html`` with the dataset written into its data element.

    ``</`` is escaped so nothing in a node name or a failure reason can close the script element
    early -- the JSON stays data, never markup.
    """
    empty = data_element(element_id)
    if empty not in index_html:
        raise SiteBundleMissing(f"{name} index.html has no data element; rebuild the frontend")
    body = json.dumps(dataset, separators=(",", ":"), sort_keys=True).replace("</", "<\\/")
    return index_html.replace(empty, data_element(element_id, body), 1)


def render(site_dir: Path, dataset: Mapping[str, Any], element_id: str, *, name: str = "report") -> str:
    """The built page in ``site_dir`` with this dataset embedded, as one HTML document."""
    index = site_dir / "index.html"
    if not index.is_file():
        raise SiteBundleMissing(f"{name} page not built: {index} is missing")
    return embed(index.read_text(encoding="utf-8"), dataset, element_id, name=name)
