/** @type {import('next').NextConfig} */
const nextConfig = {
  // Every route prerenders to static HTML, so the site ships as plain files.
  output: "export",
};

export default nextConfig;
