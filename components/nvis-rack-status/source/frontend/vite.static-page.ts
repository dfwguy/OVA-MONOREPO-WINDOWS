/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */
/**
 * A report's static page: a separate build of the same sources, emitted as **one self-contained
 * HTML file**. The deployment tracker and the cluster forecast each have one
 * (`vite.tracker.config.ts`, `vite.forecast.config.ts`); the backend writes a dataset into the page
 * (`backend/static_page.py`) and hands it out as a download.
 *
 * Separate from the SPA build because the two have opposite needs: the SPA is served at `/` by
 * Flask and shares chunks across routes, while a report page is handed to people as a file.
 *
 * One file, with the script, the stylesheet and the fonts inlined, because a page with sibling
 * assets renders **white** when opened from disk: Chrome refuses module scripts and fonts from
 * `file://` (origin `null`, "blocked by CORS policy"). That is how the first tracker export was
 * opened, and how most people will open an attachment. A single file also uploads to Linkify as-is.
 */
import { defineConfig, type Plugin, type Rollup, type UserConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/** `</script` / `</style` inside inlined code would end the element early; `<\/` is equivalent. */
function guard(code: string, tag: "script" | "style"): string {
  return code.replace(new RegExp(`</${tag}`, "gi"), `<\\/${tag}`);
}

/**
 * Move every emitted script and stylesheet into index.html, and refuse to finish if anything
 * else is left: a stray asset would be a file the page silently depends on and the export drops.
 */
function inlineIntoHtml(name: string): Plugin {
  return {
    name: `${name}-inline-into-html`,
    enforce: "post",
    generateBundle(_options, bundle) {
      const page = bundle["index.html"] as Rollup.OutputAsset | undefined;
      if (!page) this.error(`${name} build produced no index.html`);
      let html = String(page.source);
      for (const [fileName, item] of Object.entries(bundle)) {
        if (fileName === "index.html") continue;
        const ref = fileName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        if (item.type === "chunk") {
          const tag = new RegExp(`<script type="module"[^>]*src="[^"]*${ref}"[^>]*></script>`);
          if (!tag.test(html)) this.error(`no <script> for ${fileName} in index.html`);
          html = html.replace(tag, () => `<script type="module">${guard((item as Rollup.OutputChunk).code, "script")}</script>`);
        } else if (fileName.endsWith(".css")) {
          const tag = new RegExp(`<link rel="stylesheet"[^>]*href="[^"]*${ref}"[^>]*>`);
          if (!tag.test(html)) this.error(`no <link> for ${fileName} in index.html`);
          html = html.replace(tag, () => `<style>${guard(String(item.source), "style")}</style>`);
        } else {
          this.error(`${fileName} was not inlined; the ${name} page must be a single file`);
        }
        delete bundle[fileName];
      }
      page.source = html;
    },
  };
}

/** The build of one report page: `frontend/<name>/index.html` -> `static/<name>/index.html`. */
export function staticPageConfig(name: string): UserConfig {
  return defineConfig({
    plugins: [react(), tailwindcss(), inlineIntoHtml(name)],
    root: name,
    base: "./",
    publicDir: false,
    build: {
      outDir: `../../static/${name}`,
      emptyOutDir: true,
      // Fonts and images become data: URIs inside the stylesheet, so nothing is fetched.
      assetsInlineLimit: () => true,
      cssCodeSplit: false,
      modulePreload: false,
      rollupOptions: { output: { inlineDynamicImports: true } },
      // One page, loaded once; the number that matters is the file, a few MB with fonts and data.
      chunkSizeWarningLimit: 4000,
    },
  });
}
