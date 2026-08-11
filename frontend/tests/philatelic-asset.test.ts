import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(__dirname, "..");
const ASSET_DIR = path.join(ROOT, "public/img/japan/philatelic");
const MANIFEST = path.join(ASSET_DIR, "MANIFEST.md");
const RUNTIME_ASSETS = [
  path.join(ASSET_DIR, "japan-atlas-stamp-01.webp"),
];

const REQUIRED_MANIFEST_FIELDS = [
  "asset_id",
  "output_path",
  "source_item_url",
  "source_creator",
  "source_rights_statement",
  "source_download_date",
  "source_crop_or_transformation",
  "generator_product_and_model",
  "generation_date",
  "exact_prompt",
  "human_selected_revision",
  "vectorizer_or_cleanup_tool",
  "final_format_and_bytes",
  "intended_placements",
] as const;

function bytes(file: string): number {
  return fs.statSync(file).size;
}

function readManifest(): string {
  return fs.readFileSync(MANIFEST, "utf-8");
}

describe("Japan philatelic runtime asset", () => {
  it("ships exactly the reviewed runtime asset and manifest", () => {
    expect(fs.existsSync(MANIFEST), "MANIFEST.md should exist").toBe(true);

    for (const asset of RUNTIME_ASSETS) {
      expect(fs.existsSync(asset), `${path.relative(ROOT, asset)} should exist`).toBe(true);
    }
  });

  it("keeps raster payload inside the approved budget", () => {
    const sizes = RUNTIME_ASSETS.map(bytes);

    for (const size of sizes) {
      expect(size).toBeLessThanOrEqual(160 * 1024);
    }

    const total = sizes.reduce((sum, size) => sum + size, 0);
    expect(total).toBeLessThan(250 * 1024);
  });

  it("records all required manifest fields and points to existing outputs", () => {
    const manifest = readManifest();

    for (const field of REQUIRED_MANIFEST_FIELDS) {
      expect(manifest).toMatch(new RegExp(`^${field}:`, "m"));
    }

    for (const asset of RUNTIME_ASSETS) {
      expect(manifest).toContain(path.relative(ROOT, asset));
    }
  });

  it("documents raster text review instead of relying on byte-level OCR", () => {
    const manifest = readManifest();

    expect(manifest).toMatch(/^manual_visual_review:/m);
    expect(manifest).toContain("ATLAS");
    expect(manifest).toContain("JAPAN");
    expect(manifest).toContain("no route/date/year/denomination");
  });
});
