// ABOUTME: Component tests for the app shell: the hash picks the screen, and nothing else happens.
// ABOUTME: The API is not running here, so each screen shows its typed unreachable error.
import { flushSync, mount, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App.svelte";
import { freshHost } from "./test-support";

let mounted: ReturnType<typeof mount> | undefined;

afterEach(() => {
  if (mounted) void unmount(mounted);
  mounted = undefined;
  window.location.hash = "";
  document.body.replaceChildren();
});

describe("App", () => {
  it("shows the Analyze screen by default, with a main landmark and navigation", () => {
    mounted = mount(App, { target: freshHost() });
    expect(document.querySelector("main h2")?.textContent).toBe("Analyze a posting");
    expect(document.querySelector('nav[aria-label="Main"] a')?.getAttribute("href")).toBe("#/");
    expect(document.querySelector("h1")?.textContent).toBe("Cypress Creek");
  });

  it("shows a stored report for a report address and goes back when the address changes", async () => {
    window.location.hash = "#/report/rep-1";
    mounted = mount(App, { target: freshHost() });
    expect(document.querySelector("main h2")).toBeNull();
    await vi.waitFor(() => {
      expect(document.querySelector('[role="alert"]')?.textContent).toContain("unreachable");
    });
    window.location.hash = "#/";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    flushSync();
    expect(document.querySelector("main h2")?.textContent).toBe("Analyze a posting");
  });

  it("treats an address that is not a report id as the Analyze screen", () => {
    window.location.hash = "#/report/<script>";
    mounted = mount(App, { target: freshHost() });
    expect(document.querySelector("main h2")?.textContent).toBe("Analyze a posting");
  });
});
