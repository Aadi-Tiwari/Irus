"use client";

import { useEffect, useRef, useState } from "react";
import { motion, useInView, animate, type Variants } from "motion/react";
import { useReducedMotionSafe } from "@/lib/useReducedMotionSafe";

/**
 * ProblemSection: second beat of the page. Two agents each finish one half of a
 * feature, both report success truthfully, and every signal downstream reports
 * green while the application is broken. Four third-party figures count up on
 * scroll-into-view (once). Atmosphere is built from faint emerald radial glows +
 * drifting threads, matching the HeroDive design system (#0a0a0a, Geist,
 * feathered edges, emerald-200 accents).
 */

type Stat = {
  value: number;
  /** Decimal places to render while counting. */
  decimals: number;
  prefix?: string;
  suffix: string;
  label: string;
  source: string;
};

const STATS: Stat[] = [
  { value: 58, decimals: 0, suffix: "%", label: "integration accuracy", source: "with the full spec" },
  { value: 25, decimals: 0, suffix: "%", label: "same task, spec stripped", source: "detail lost between agents" },
  { value: 28.6, decimals: 1, suffix: "%", label: "strict contract pass", source: "GPT-5.5, generated backends" },
  { value: 40, decimals: 0, suffix: "%", label: "no open model above", source: "web API integration" },
];

const container: Variants = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.12, delayChildren: 0.05 },
  },
};

const rise: Variants = {
  hidden: { opacity: 0, y: 28, filter: "blur(8px)" },
  show: {
    opacity: 1,
    y: 0,
    filter: "blur(0px)",
    transition: { duration: 0.9, ease: [0.22, 1, 0.36, 1] },
  },
};

function Counter({
  stat,
  start,
}: {
  stat: Stat;
  start: boolean;
}) {
  const reduce = useReducedMotionSafe();
  // Always mount at 0 so the server and the first client render agree. The
  // reduced-motion jump to the final value happens in the effect below.
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    if (reduce) {
      setDisplay(stat.value);
      return;
    }
    // Reset to zero whenever the section is not in view, so it always counts
    // up fresh (0 -> target) the next time you scroll to it.
    if (!start) {
      setDisplay(0);
      return;
    }
    // Linear + equal duration => every stat ticks evenly (even the small ones
    // like 25 and 40, which a front-loaded ease made look static) and they all
    // reach their target at the same moment.
    const controls = animate(0, stat.value, {
      duration: 2.0,
      ease: "linear",
      onUpdate: (v) => setDisplay(v),
    });
    return () => controls.stop();
  }, [start, stat.value, reduce]);

  const formatted = display.toLocaleString("en-US", {
    minimumFractionDigits: stat.decimals,
    maximumFractionDigits: stat.decimals,
  });

  return (
    <span className="tabular-nums">
      {stat.prefix}
      {formatted}
      {stat.suffix}
    </span>
  );
}

export default function ProblemSection() {
  const ref = useRef<HTMLElement>(null);
  const inView = useInView(ref, { amount: 0.35 });

  const THREADS = [
    "M-40 180 C 220 120, 360 320, 620 240 S 980 360, 1260 260",
    "M-40 520 C 260 600, 420 380, 640 500 S 1000 420, 1260 560",
    "M120 -40 C 200 220, 460 300, 520 560 S 720 760, 760 860",
    "M880 -40 C 820 240, 1040 360, 980 600 S 1120 760, 1080 860",
  ];

  return (
    <section
      ref={ref}
      id="problem"
      className="relative isolate flex min-h-screen w-full flex-col items-center justify-center overflow-hidden bg-transparent px-6 py-28 md:py-36"
    >
      {/* ── Underground atmosphere ───────────────────────────────────── */}
      {/* Deep radial emerald glows, very faint, no hard edges */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(ellipse_70%_50%_at_50%_0%,rgba(52,211,153,0.10),transparent_60%)]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(ellipse_60%_55%_at_18%_85%,rgba(110,231,183,0.07),transparent_60%)]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(ellipse_55%_50%_at_85%_70%,rgba(16,185,129,0.06),transparent_62%)]"
      />

      {/* Drifting threads, decorative texture only, never named in the copy */}
      <svg
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 h-full w-full opacity-[0.4]"
        preserveAspectRatio="xMidYMid slice"
        viewBox="0 0 1200 800"
        fill="none"
      >
        <defs>
          <linearGradient id="thread" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#34d399" stopOpacity="0" />
            <stop offset="50%" stopColor="#6ee7b7" stopOpacity="0.5" />
            <stop offset="100%" stopColor="#34d399" stopOpacity="0" />
          </linearGradient>
          <filter id="nodeGlow" x="-200%" y="-200%" width="500%" height="500%">
            <feGaussianBlur stdDeviation="2.4" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        {THREADS.map((d, i) => (
          <motion.path
            key={d}
            id={`thread-${i}`}
            d={d}
            stroke="url(#thread)"
            strokeWidth="1"
            initial={{ pathLength: 0, opacity: 0 }}
            animate={
              inView
                ? { pathLength: 1, opacity: 1 }
                : { pathLength: 0, opacity: 0 }
            }
            transition={{
              duration: 2.6,
              delay: 0.3 + i * 0.25,
              ease: "easeInOut",
            }}
          />
        ))}

        {/* Data nodes travelling the threads, continuously */}
        {THREADS.map((d, i) =>
          [0, 1, 2].map((k) => (
            <circle key={`node-${i}-${k}`} r="2.6" fill="#a7f3d0" filter="url(#nodeGlow)">
              <animateMotion
                dur={`${9 + i * 1.5}s`}
                begin={`${k * (3 + i * 0.4)}s`}
                repeatCount="indefinite"
                rotate="auto"
                keyPoints="0;1"
                keyTimes="0;1"
                calcMode="linear"
              >
                <mpath href={`#thread-${i}`} />
              </animateMotion>
              <animate
                attributeName="opacity"
                values="0;1;1;0"
                keyTimes="0;0.1;0.9;1"
                dur={`${9 + i * 1.5}s`}
                begin={`${k * (3 + i * 0.4)}s`}
                repeatCount="indefinite"
              />
            </circle>
          )),
        )}
      </svg>


      {/* ── Content ──────────────────────────────────────────────────── */}
      <motion.div
        variants={container}
        initial="hidden"
        animate={inView ? "show" : "hidden"}
        className="relative z-10 mx-auto w-full max-w-5xl text-center"
      >
        {/* Headline */}
        <motion.h2
          variants={rise}
          className="mx-auto max-w-3xl text-balance text-4xl font-medium leading-[1.05] tracking-tight text-white sm:text-5xl md:text-6xl"
        >
          Every signal says green. The app is{" "}
          <span className="relative whitespace-nowrap text-white">
            broken.
            <span
              aria-hidden
              className="absolute -bottom-1 left-0 h-px w-full bg-gradient-to-r from-transparent via-emerald-300/60 to-transparent"
            />
          </span>
        </motion.h2>

        {/* Sub */}
        <motion.p
          variants={rise}
          className="mx-auto mt-7 max-w-2xl text-pretty text-base leading-relaxed text-white/60 md:text-lg"
        >
          Agent A builds the checkout endpoint and expects JSON with email and
          amount. Agent B builds the checkout form and posts FormData with
          user_email and total.{" "}
          <span className="text-white/80">
            Both test suites pass. Both agents report done, truthfully.
          </span>{" "}
          Git merges the two branches without a conflict because they touched
          different files, the typechecker validates each side alone, and CI
          never runs one branch against the other.
        </motion.p>

        {/* Stats */}
        <motion.div
          variants={rise}
          className="relative mx-auto mt-16 grid w-full grid-cols-2 gap-px overflow-hidden rounded-[28px] border border-white/12 bg-[#0a0d0c]/80 shadow-[0_8px_50px_-12px_rgba(0,0,0,0.6),inset_0_1px_0_rgba(255,255,255,0.08)] backdrop-blur-2xl md:mt-20 md:grid-cols-4"
        >
          {/* soft sheen across the glass */}
          <span
            aria-hidden
            className="pointer-events-none absolute inset-0 bg-[linear-gradient(115deg,rgba(255,255,255,0.05),transparent_30%,transparent_70%,rgba(52,211,153,0.04))]"
          />
          {STATS.map((stat) => (
            <div
              key={stat.label}
              className="group relative flex flex-col items-center justify-center gap-3 bg-[#0a0d0c]/70 px-5 py-9 transition-colors duration-500 hover:bg-emerald-400/[0.06] md:px-6 md:py-12"
            >
              {/* Hairline top glow on hover */}
              <span
                aria-hidden
                className="pointer-events-none absolute inset-x-6 top-0 h-px bg-gradient-to-r from-transparent via-emerald-300/40 to-transparent opacity-0 transition-opacity duration-500 group-hover:opacity-100"
              />
              <div className="bg-gradient-to-b from-white to-white/70 bg-clip-text text-4xl font-medium tracking-tight text-transparent md:text-5xl">
                <Counter stat={stat} start={inView} />
              </div>
              <div className="max-w-[14ch] text-[11px] font-medium uppercase leading-snug tracking-[0.14em] text-emerald-200/55">
                {stat.label}
              </div>
              <div className="text-[11px] font-medium tracking-wide text-white/35">
                {stat.source}
              </div>
            </div>
          ))}
        </motion.div>

        {/* Caption */}
        <motion.p
          variants={rise}
          className="mx-auto mt-12 max-w-2xl text-pretty text-sm leading-relaxed text-white/45 md:text-[15px]"
        >
          Integration accuracy collapses as spec detail is lost between one agent
          and the next. Nothing in the merge path checks that the two halves
          agree.
        </motion.p>

        {/* Footnote */}
        <motion.p
          variants={rise}
          className="mx-auto mt-6 max-w-md text-[11px] leading-relaxed tracking-wide text-white/25"
        >
          Third-party measurements, not measurements of Irus. The Specification
          Gap, arXiv 2603.24284. BackendForge, arXiv 2607.11042. WAPIIBench,
          arXiv 2509.20172.
        </motion.p>
      </motion.div>
    </section>
  );
}
