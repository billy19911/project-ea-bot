/** @type {import('next').NextConfig} */
const cliArgs = process.argv.slice(2);
let cliPort;
for (let i = 0; i < cliArgs.length; i += 1) {
  const arg = cliArgs[i];
  if (/^--port=/.test(arg) || /^-p=/.test(arg)) {
    cliPort = arg.slice(arg.indexOf('=') + 1);
    break;
  }
  if (arg === '--port' || arg === '-p') {
    cliPort = cliArgs[i + 1];
    break;
  }
}
const selectedPort = cliPort ?? process.env.PORT ?? '4321';
const port = /^\d+$/.test(selectedPort) ? Number(selectedPort) : 4321;
const validPort = Number.isInteger(port) && port > 0 && port <= 65535 ? port : 4321;
// `next dev` gets its own per-port distDir so a running dev server can never
// collide with `next build`/`next start` (both use `.next-<port>`). Mixing dev
// and production chunks in one dir corrupts the webpack runtime
// ("__webpack_modules__[moduleId] is not a function" / 500s).
// Detect dev via NODE_ENV, not argv: `next dev` evaluates this config twice —
// once in the CLI process (argv[2] === 'dev') and again in the forked
// start-server child (argv[2] === undefined) — so argv-based detection makes
// the two processes disagree on distDir. `bin/next` sets NODE_ENV to
// 'development' for dev and 'production' for build/start in both processes.
const isDevServer = process.env.NODE_ENV === 'development';
const distDir = isDevServer ? `.next-dev-${validPort}` : `.next-${validPort}`;
const nextConfig = {
  distDir,
  // ESLint 9 flat config (eslint.config.mjs) is run via `npm run lint`.
  // Next.js 14's build-time ESLint uses the legacy eslintrc API which is
  // incompatible with ESLint 9, so skip the duplicate build-time lint.
  eslint: {
    ignoreDuringBuilds: true,
  },
  // Proxy the Node control-plane API through the web origin so the browser
  // only ever talks to the Web port — no CORS, and the Node API port can be
  // changed via .env.runtime WITHOUT rebuilding the web bundle.
  //
  // The client calls `/ea-api/<path>`; Next rewrites to `${EA_API_URL}/<path>`.
  async rewrites() {
    const apiUrl = process.env.EA_API_URL || 'http://127.0.0.1:3789';
    return [
      {
        source: '/ea-api/:path*',
        destination: `${apiUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
