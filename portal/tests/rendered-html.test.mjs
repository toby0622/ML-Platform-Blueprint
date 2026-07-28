import assert from "node:assert/strict";
import { access, readFile, stat } from "node:fs/promises";
import test from "node:test";

async function render(path = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}-${path}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request(`http://localhost${path}`, {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the ML Platform Command Center", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>ML Platform Command Center<\/title>/i);
  assert.match(html, /Model delivery/);
  assert.match(html, /Command Center/);
  assert.match(html, /RTX 4080 SUPER/);
  assert.match(html, /Reviewed demo data/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape|react-loading-skeleton/i);
});

test("ships finished metadata, BFF routes, and a bespoke social card", async () => {
  const [page, layout, dashboard, packageJson, socialCard] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/portal-dashboard.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
    stat(new URL("../public/og.png", import.meta.url)),
  ]);

  assert.match(page, /PortalDashboard/);
  assert.match(layout, /ML Platform Command Center/);
  assert.match(layout, /new URL\("\/og\.png", metadataBase\)/);
  assert.match(dashboard, /Demo/);
  assert.match(dashboard, /Live/);
  assert.match(dashboard, /\/api\/platform\//);
  assert.match(dashboard, /\/api\/llm\/chat/);
  assert.match(dashboard, /900/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  assert.ok(socialCard.size > 100_000);

  await Promise.all([
    access(new URL("../app/api/platform/[...path]/route.ts", import.meta.url)),
    access(new URL("../app/api/llm/chat/route.ts", import.meta.url)),
    assert.rejects(access(new URL("../app/_sites-preview", import.meta.url))),
  ]);
});
