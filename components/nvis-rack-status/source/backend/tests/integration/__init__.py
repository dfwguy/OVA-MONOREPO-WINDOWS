# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Integration tests: the backend serving a **really built** frontend.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Everything else in ``backend/tests/`` is a unit tier — backend only, no ``npm run build`` — and
``frontend/src/**/*.test.tsx`` is the other unit tier, frontend only. Neither can see a defect that
only exists where the two meet, and this product has shipped several of those:

* assets served ``Transfer-Encoding: chunked`` because ``send_file`` streams and Flask-Compress pops
  the length — invisible unless a real bundle is served and the client asks for brotli;
* an ``index.html`` referencing content-hashed chunks that are not in ``assets/`` — a blank page with
  every check green, which is what `verify-deploy.sh` exists to catch *after* a deploy;
* the SPA-missing 503 contract, which only means anything if the built case is also tested.

**These do not run in the unit job.** They need `static/spa/`, which is a gitignored build artifact,
so the CI pipeline builds the frontend, publishes it as an artifact, and runs this directory against
it in a separate `integration` stage that is ordered after the frontend's own tests pass. Locally
they run whenever you have built.

Add a test here when it needs the built bundle. Add it to `backend/tests/` when it does not — that
job is much faster and gates every push.
"""
