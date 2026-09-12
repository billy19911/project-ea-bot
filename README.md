<!-- SPDX-License-Identifier: CC0-1.0 -->
<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>project-ea-bot</title>
<style>
  :root {
    --bg: #0f1117;
    --fg: #e4e4e7;
    --accent: #60a5fa;
    --muted: #71717a;
  }
  body {
    background: var(--bg);
    color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin: 0;
    padding: 2rem 1rem;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .card {
    max-width: 640px;
    text-align: center;
  }
  h1 {
    font-size: 2rem;
    margin: 0 0 0.25rem;
    color: var(--accent);
  }
  .tag {
    display: inline-block;
    background: #1e293b;
    color: var(--accent);
    font-size: 0.8rem;
    padding: 0.2rem 0.6rem;
    border-radius: 999px;
    margin-bottom: 1.5rem;
  }
  p {
    color: var(--muted);
    margin: 0.5rem 0;
    line-height: 1.6;
  }
  code {
    background: #1e293b;
    padding: 0.1rem 0.3rem;
    border-radius: 4px;
    font-family: "JetBrains Mono", Consolas, monospace;
  }
  ul {
    text-align: left;
    color: var(--muted);
    line-height: 1.8;
    margin: 1rem 0;
  }
  li::marker {
    color: var(--accent);
  }
  .links {
    margin-top: 2rem;
    display: flex;
    gap: 1rem;
    justify-content: center;
  }
  .links a {
    color: var(--accent);
    text-decoration: none;
  }
  .links a:hover {
    text-decoration: underline;
  }
</style>
</head>
<body>
  <div class="card">
    <span class="tag">Project EA Bot</span>
    <h1>project-ea-bot</h1>
    <p>Monorepo untuk EA Bot — <strong>Node.js API</strong>, <strong>Python service</strong>, dan <strong>Web frontend</strong>.</p>
    <ul>
      <li><code>apps/api</code> — Node.js API (Express/Fastify)</li>
      <li><code>services/python</code> — Python microservice</li>
      <li><code>packages/shared/config</code> — Shared config types &amp; validation</li>
      <li><code>docs/logging.md</code> — Panduan structured logging</li>
    </ul>
    <div class="links">
      <a href="docs/logging.md">Logging Guide</a>
      <a href=".env.example">Environment Variables</a>
    </div>
  </div>
</body>
</html>
