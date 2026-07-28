import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync, existsSync } from "fs";
import { resolve } from "path";

const CHUNKS_DIR = resolve(__dirname, "../.next/static/chunks");

const HEAVY_LIBS = ["gsap", "maplibre-gl", "maplibregl"];

function jsChunks(): string[] {
  if (!existsSync(CHUNKS_DIR)) return [];
  return readdirSync(CHUNKS_DIR).filter((f) => f.endsWith(".js"));
}

function chunkContent(name: string): string {
  return readFileSync(resolve(CHUNKS_DIR, name), "utf-8");
}

describe("bundle check — heavy deps absent from initial JS", () => {
  const allChunks = jsChunks();

  it("production build exists at .next/static/chunks", () => {
    expect(allChunks.length).toBeGreaterThan(0);
  });

  for (const lib of HEAVY_LIBS) {
    it(`${lib} not in any chunk file`, () => {
      const offending: string[] = [];
      for (const chunk of allChunks) {
        const content = chunkContent(chunk);
        if (
          content.includes(`"${lib}"`) ||
          content.includes(`'${lib}'`) ||
          content.includes(`/${lib}/`) ||
          content.includes(`node_modules/${lib}`)
        ) {
          offending.push(chunk);
        }
      }
      expect(offending).toEqual([]);
    });
  }
});
