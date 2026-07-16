import assert from "node:assert/strict";
import test from "node:test";

import { isPublicMainView, parseSavedMainView, requiresApiConfig } from "./navigation.ts";

test("main navigation separates public home modes from API-required business modes", () => {
  assert.equal(isPublicMainView("landing"), true);
  assert.equal(isPublicMainView("guide"), true);
  assert.equal(isPublicMainView("applications"), true);
  assert.equal(isPublicMainView("questionbank"), true);
  assert.equal(requiresApiConfig("interview"), true);
  assert.equal(requiresApiConfig("resume"), true);
  assert.equal(requiresApiConfig("boss"), true);
});

test("parseSavedMainView falls back to landing for stale values", () => {
  assert.equal(parseSavedMainView("boss"), "boss");
  assert.equal(parseSavedMainView("unknown"), "landing");
  assert.equal(parseSavedMainView(null), "landing");
});
