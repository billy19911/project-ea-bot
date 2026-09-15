/** @type {import('next').NextConfig} */
const nextConfig = {
  // ESLint 9 flat config (eslint.config.mjs) is run via `npm run lint`.
  // Next.js 14's build-time ESLint uses the legacy eslintrc API which is
  // incompatible with ESLint 9, so skip the duplicate build-time lint.
  eslint: {
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
