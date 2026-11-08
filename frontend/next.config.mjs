// The browser talks to /api on this same address; Next forwards it to the Python backend.
const BACKEND = process.env.BACKEND_URL || "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  // Only for `npm run dev`; the production build is plain files served by the backend itself.
  ...(process.env.NODE_ENV !== "production" ? { async rewrites() { return [{ source: "/api/:path*", destination: `${BACKEND}/api/:path*` }]; } } : {}),
};

export default nextConfig;
