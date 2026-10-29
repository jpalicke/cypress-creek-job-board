// ABOUTME: Reads the ids of the stored reports that scripts/seed_ui_fixtures.py wrote for the tests.
// ABOUTME: Also holds the hostile strings the seed script stores, so tests can look for them on screen.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

export const SCRIPT_PAYLOAD = "<script>window.__xss = 1; alert(1)</script>";
export const IMAGE_PAYLOAD = '<img src=x onerror="window.__xss = 2; alert(2)">';

export interface Fixtures {
  benign: string;
  hostile: string;
  incomplete: string;
}

export function loadFixtures(): Fixtures {
  const file = resolve(import.meta.dirname, "..", "..", ".e2e-data", "fixtures.json");
  return JSON.parse(readFileSync(file, "utf-8")) as Fixtures;
}
