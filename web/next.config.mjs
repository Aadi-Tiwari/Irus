/** @type {import('next').NextConfig} */

// GitHub Pages serves a project site from /<repo>, not from the domain root, so
// the build needs to know its prefix. BASE_PATH is set by the Pages workflow and
// is empty everywhere else, which keeps local dev and any root-served host
// working unchanged.
const basePath = process.env.BASE_PATH ?? "";

const nextConfig = {
  // Every route prerenders to static HTML, so the site ships as plain files.
  output: "export",
  basePath,
  assetPrefix: basePath || undefined,
  // assetPrefix only rewrites Next's own bundles. Files served straight out of
  // public/ are referenced by hand, so they read this instead.
  env: { NEXT_PUBLIC_BASE_PATH: basePath },
};

export default nextConfig;
