/**
 * Next.js config for the Winnow marketing + demo site.
 *
 * The demo API origin is configurable so the same build works against:
 *  - local dev: http://localhost:8000
 *  - Railway/Fly.io/etc: whatever the demo API is deployed to
 *
 * NEXT_PUBLIC_API_ORIGIN is baked in at build time. Change it via
 * `NEXT_PUBLIC_API_ORIGIN=https://... vercel deploy` or the Vercel
 * project env vars. Rewrites make /api/* first-party so cookies stay
 * SameSite=Lax in both environments.
 */
const API_ORIGIN = process.env.NEXT_PUBLIC_API_ORIGIN ?? 'http://localhost:8000';

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${API_ORIGIN}/:path*` }];
  },
};

export default nextConfig;
