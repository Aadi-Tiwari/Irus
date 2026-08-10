"use client";

import { useEffect, useRef } from "react";
import { motion, useScroll, useTransform, useMotionTemplate } from "motion/react";
import { asset } from "@/lib/asset";

// Measured on this machine against a synthetic 500-file project. The two zeros are
// structural rather than measured: the engine has no required dependencies and no
// model sits anywhere in the verification path.
const BUBBLES = [
  { value: "0.28s", label: "500-file sweep" },
  { value: "83ms", label: "incremental re-check" },
  { value: "0", label: "required dependencies" },
  { value: "0", label: "models in the check" },
];

/**
 * Hero — Mercury-style inset media card. The aerial plate autoplays softly; on
 * scroll the card zooms straight down (the dive), the content lifts away, and it
 * blurs/darkens through into the surface below. Card edges are feathered so they
 * melt into the dark page like Mercury's hero.
 */
export default function HeroDive() {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start start", "end start"],
  });

  const scale = useTransform(scrollYProgress, [0, 0.5, 1], [1, 3, 14]);
  const blurPx = useTransform(scrollYProgress, [0.6, 1], [0, 24]);
  const videoFilter = useMotionTemplate`blur(${blurPx}px)`;
  const darken = useTransform(scrollYProgress, [0.72, 0.92], [0, 1]);
  const contentOpacity = useTransform(scrollYProgress, [0, 0.25], [1, 0]);
  const contentY = useTransform(scrollYProgress, [0, 0.25], [0, -40]);

  // Two full-resolution decoders running at once is the page's largest fixed
  // cost, and this one is invisible past the dive. Stop it when it leaves the
  // viewport and restart it on the way back up.
  const videoRef = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const el = videoRef.current;
    const host = ref.current;
    if (!el || !host) return;
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) void el.play().catch(() => {});
        else el.pause();
      },
      { rootMargin: "100px" },
    );
    io.observe(host);
    return () => io.disconnect();
  }, []);

  // 200vh, not 320: the dive is keyed to scroll progress, so a shorter section
  // plays the same arc over less travel. At 320vh a wheel notch moved the plate
  // so little that the zoom read as stuck rather than deliberate.
  return (
    <section ref={ref} className="relative h-[200vh] bg-[#0a0a0a]">
      <div className="sticky top-0 h-screen w-full p-3 md:p-4">
        <div className="relative h-full w-full overflow-hidden rounded-[28px] md:rounded-[36px]">
          {/* Backdrop plate — zooms on scroll */}
          <motion.video
            ref={videoRef}
            style={{ scale, filter: videoFilter }}
            className="absolute inset-0 h-full w-full object-cover"
            src={asset("/hero-plate.mp4")}
            autoPlay
            muted
            loop
            playsInline
            preload="auto"
            disablePictureInPicture
          />

          {/* Soft atmospheric grade */}
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/45 via-black/10 to-black/65" />
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_50%_36%,rgba(220,255,235,0.12),transparent_62%)]" />

          {/* Feathered edges — melt the card into the dark page (Mercury look) */}
          <div className="pointer-events-none absolute inset-0 rounded-[28px] shadow-[inset_0_0_100px_36px_rgba(10,10,10,0.92)] md:rounded-[36px]" />

          {/* Punch-through to the page color at the end of the dive (blends into next section) */}
          <motion.div style={{ opacity: darken }} className="pointer-events-none absolute inset-0 bg-[#0a0a0a]" />

          {/* Bottom blend so the card melts into the page / next section */}
          <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[6] h-40 bg-gradient-to-b from-transparent to-[#0a0a0a]" />

          {/* Nav */}
          <motion.nav
            style={{ opacity: contentOpacity }}
            className="absolute inset-x-0 top-0 z-20 grid grid-cols-3 items-center px-6 py-5 md:px-10"
          >
            <div className="flex items-center gap-2 justify-self-start text-white">
              <span className="text-lg leading-none">⋈</span>
              <span className="text-sm font-semibold tracking-[0.22em]">IRUS</span>
            </div>
            <div className="hidden items-center gap-9 justify-self-center text-sm text-white/75 md:flex">
              <a href="#how" className="transition hover:text-white">How it works</a>
              <a href="#install" className="transition hover:text-white">Install</a>
            </div>
            <a
              href="https://github.com/Aadi-Tiwari/irus"
              target="_blank"
              rel="noopener noreferrer"
              className="justify-self-end rounded-full bg-white/15 px-4 py-2 text-sm font-medium text-white backdrop-blur-md transition hover:bg-white/25"
            >
              GitHub
            </a>
          </motion.nav>

          {/* Center content */}
          <motion.div
            style={{ opacity: contentOpacity, y: contentY }}
            className="absolute inset-0 z-10 flex flex-col items-center justify-center px-6 text-center"
          >
            <h1 className="text-5xl font-medium tracking-tight text-white drop-shadow-[0_2px_30px_rgba(0,0,0,0.55)] md:text-7xl">
              Irus
            </h1>
            <p className="mt-5 max-w-xl text-lg text-white/85 md:text-2xl">
              Catches the bug between two AI agents, before the merge.
            </p>

            <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
              {BUBBLES.map((b) => (
                <div
                  key={b.label}
                  className="rounded-2xl border border-white/15 bg-white/10 px-5 py-3 text-center backdrop-blur-md"
                >
                  <div className="text-lg font-semibold text-white md:text-xl">{b.value}</div>
                  <div className="mt-0.5 text-[11px] uppercase tracking-wider text-emerald-200/80">
                    {b.label}
                  </div>
                </div>
              ))}
            </div>
          </motion.div>

        </div>
      </div>
    </section>
  );
}
