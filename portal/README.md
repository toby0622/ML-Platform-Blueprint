# ML Platform Command Center

The Portal is the product-facing surface of ML Platform Blueprint. It combines
model and run discovery, deployment controls, inference playgrounds, audit
context, observability links, and reviewed local GPU evidence.

## Modes

- **Demo** is the safe public portfolio experience. It uses clearly labelled
  illustrative lifecycle data and the reviewed RTX 4080 SUPER evidence.
- **Live** uses server-side BFF routes. The browser never receives the Platform
  API or vLLM base URL.

## Local development

```powershell
Copy-Item .env.example .env.local
npm.cmd ci
npm.cmd run dev
```

Open <http://localhost:3000>.

## Quality checks

```powershell
npm.cmd run lint
npm.cmd run typecheck
npm.cmd test
```

`npm test` performs a production build and then imports the emitted Worker to
verify server-rendered product content and metadata.

See [the repository Portal guide](../docs/portal.md) for Docker Compose, GPU
chat, role-based workflows, API contracts, and honest operating boundaries.
