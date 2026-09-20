/** @type {import('next').NextConfig} */
const nextConfig = {
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
