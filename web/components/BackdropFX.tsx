"use client";

import { useEffect, useRef, useState } from "react";
import { asset } from "@/lib/asset";

/**
 * BackdropFX — the one backdrop the whole site sits on.
 *
 * The same plate the hero dives through, fixed behind every section and running
 * at its own steady pace, so scrolling past the hero lands on the same surface
 * rather than cutting to a different one. Every content section below is
 * transparent on top of this.
 *
 * The video is decorative, so it is muted, looping and inert; the scrim and
 * vignette below it are what keep body copy readable over moving footage.
 */

export default function BackdropFX() {
  // The hero card covers almost all of this layer while it is on screen, so the
  // plate does not need to compete with the hero's own download during first
  // paint. It starts once the page has loaded, or after a beat if load is slow.
  const videoRef = useRef<HTMLVideoElement>(null);
  const [src, setSrc] = useState<string | undefined>(undefined);
  useEffect(() => {
    let done = false;
    const start = () => {
      if (done) return;
      done = true;
      setSrc(asset("/backdrop-plate.mp4"));
    };
    if (document.readyState === "complete") start();
    else window.addEventListener("load", start, { once: true });
    const t = setTimeout(start, 1200);
    return () => {
      clearTimeout(t);
      window.removeEventListener("load", start);
      clearTimeout(t);
    };
  }, []);

  useEffect(() => {
    if (src) videoRef.current?.play().catch(() => {});
  }, [src]);

  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-50 overflow-hidden">
      {/* deep base */}
      <div className="absolute inset-0 bg-[#070908]" />

      {/* This layer is blurred, upscaled and sitting under a scrim, so it plays a
          540p cut of the plate instead of the 1080p one: a quarter of the pixels
          to decode, every frame, for the whole visit.

          It is also rendered at half size and scaled back up, so the blur costs a
          quarter of the pixels for the same result, since a 1.5px blur on a
          half-size layer reads as 3px once the layer is doubled. The half-size box
          has the same aspect ratio as the full one, so the object-cover crop is
          unchanged. */}
      <div className="absolute inset-0 overflow-hidden" style={{ transform: "scale(1.06)" }}>
        <video
          className="absolute left-0 top-0 h-1/2 w-1/2 object-cover"
          style={{
            filter: "brightness(0.9) saturate(1.15) contrast(1.08) blur(1.5px)",
            transform: "scale(2)",
            transformOrigin: "top left",
            willChange: "transform",
          }}
          ref={videoRef}
          src={src}
          autoPlay
          muted
          loop
          playsInline
          preload="auto"
          disablePictureInPicture
        />
      </div>

      {/* legibility scrim — UNIFORM so there are no top/bottom dark bands as you
          scroll; just an even veil that keeps text readable over the footage */}
      <div className="absolute inset-0 bg-[rgba(7,9,8,0.52)]" />

      {/* gentle edge vignette — feathers the plate in from the corners */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_96%_92%_at_50%_50%,transparent_62%,rgba(7,9,8,0.5)_100%)]" />

      {/* faint emerald life to tie the plate into the theme */}
      <div className="absolute -left-[10%] top-[14%] h-[60vh] w-[55vw] rounded-full bg-[radial-gradient(circle,rgba(52,211,153,0.06),transparent_62%)] blur-[150px]" />
      <div className="absolute right-[-10%] bottom-[8%] h-[60vh] w-[55vw] rounded-full bg-[radial-gradient(circle,rgba(16,185,129,0.05),transparent_62%)] blur-[150px]" />

      {/* fine grain to kill banding */}
      <div
        className="absolute inset-0 opacity-[0.03] mix-blend-screen"
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
        }}
      />
    </div>
  );
}
