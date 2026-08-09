"use client";

import { useRef } from "react";
import { motion, useInView } from "motion/react";

/**
 * How it works, in one screen.
 *
 * Three moves in the order the tool runs them, then the guarantees that hold
 * across all three. This replaces the six full-screen feature beats: the page
 * argues once and moves on.
 */

const MOVES = [
  {
    step: "01",
    title: "Detect",
    lead: "It reads both sides and compares what each one declares.",
    body:
      "Python through the standard library ast, TypeScript through a dependency-free scanner that masks strings and comments first, so a brace inside a string cannot fool it. No model sits anywhere in the verification path: same code in, same answer out, offline, in milliseconds.",
    lines: [
      "route path · method · request shape",
      "response payload shape",
      "env var read but never set",
      "zero-caller endpoint",
    ],
  },
  {
    step: "02",
    title: "Prove",
    lead: "The verdict comes from the application, not from our checker.",
    body:
      "Three tiers, cheapest first. Build the request and validate it against the handler's declared schema without sending anything. Then drive the real handler in-process through the framework's own test client, inside a transaction that rolls back. Real HTTP is the last resort and only for safe methods.",
    lines: [
      "tier 1 · built, not sent",
      "tier 2 · the app's own test client",
      "tier 3 · GET, HEAD, OPTIONS only",
      "producer is authoritative by default",
    ],
  },
  {
    step: "03",
    title: "Ratchet",
    lead: "A round that does not strictly reduce failures is reverted.",
    body:
      "One owner is dispatched per failing seam, the full receipt set runs again from the top, and the round is accepted only if the total failing seams strictly decreased. The loop cannot report progress while getting worse. It is a plain loop with a stopping condition, not an agent.",
    lines: [
      "one owner per failing seam, per round",
      "full receipt set re-runs every round",
      "cached against a hash of both sides",
      "roughly thirty lines, no model",
    ],
  },
];

// What holds across all three moves, stated once rather than as its own beat.
const GUARANTEES = [
  "no model in the verification path",
  "nothing leaves localhost",
  "unknown is never high confidence",
  "baseline anchored to the merge-base",
  "status · next · claim · release",
  "96 tests, zero required dependencies",
];

export default function HowItWorksSection() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { amount: 0.25 });

  return (
    <div
      id="how"
      ref={ref}
      className="relative isolate flex w-full items-center overflow-hidden bg-transparent pb-16 pt-24"
    >
      {/* ambient dot grid */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-20 opacity-[0.5]"
        style={{
          backgroundImage: "radial-gradient(rgba(52,211,153,0.06) 1px, transparent 1px)",
          backgroundSize: "34px 34px",
          maskImage: "radial-gradient(ellipse 70% 70% at 50% 50%, black, transparent 80%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/2 -z-20 h-[42rem] w-[42rem] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(circle,rgba(52,211,153,0.08),transparent_60%)] blur-[120px]"
      />

      <div className="relative z-[5] mx-auto flex w-full max-w-7xl flex-col gap-12 px-8 md:px-14">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 24 }}
          transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
          className="relative flex max-w-3xl flex-col gap-4"
        >
          {/* scrim so the heading stays readable over the moving plate */}
          <div
            aria-hidden
            className="pointer-events-none absolute -inset-x-7 -inset-y-6 -z-10 rounded-[2rem] bg-[radial-gradient(ellipse_at_center,rgba(5,8,7,0.92),rgba(5,8,7,0.45)_62%,transparent_84%)] blur-md"
          />
          <div className="flex items-center gap-4">
            <span className="font-mono text-[11px] uppercase tracking-[0.28em] text-emerald-300/80">
              How it works
            </span>
            <span className="h-px w-16 flex-none bg-gradient-to-r from-emerald-400/50 to-transparent" />
          </div>
          <h2 className="text-3xl font-medium leading-[1.1] tracking-tight text-white md:text-[3rem]">
            One command. Three moves.
          </h2>
          <p className="max-w-2xl text-base leading-relaxed text-white/60 md:text-lg">
            <code className="rounded bg-emerald-400/[0.09] px-1.5 py-0.5 font-mono text-[13px] text-emerald-200/90">
              irus check
            </code>{" "}
            runs all three against the union of your unmerged branches and exits non-zero on a
            high-confidence finding, so it works as a merge gate and a CI step.
          </p>
        </motion.div>

        <div className="grid gap-5 md:grid-cols-3">
          {MOVES.map((m, i) => (
            <motion.div
              key={m.step}
              initial={{ opacity: 0, y: 26 }}
              animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 26 }}
              transition={{ duration: 0.7, delay: 0.12 + i * 0.1, ease: [0.22, 1, 0.36, 1] }}
              className="group flex flex-col gap-4 rounded-2xl border border-emerald-400/10 bg-[#070b09]/85 p-6 shadow-[0_18px_50px_rgba(0,0,0,0.5)] backdrop-blur-md transition-colors duration-300 hover:border-emerald-400/30"
            >
              <div className="flex items-baseline gap-3">
                <span className="font-mono text-2xl font-medium leading-none text-emerald-300">
                  {m.step}
                </span>
                <span className="text-xl font-medium tracking-tight text-white">{m.title}</span>
              </div>
              <p className="text-[15px] font-medium leading-snug text-white/85">{m.lead}</p>
              <p className="text-sm leading-relaxed text-white/45">{m.body}</p>
              <div className="mt-auto flex flex-col gap-1.5 border-t border-white/[0.06] pt-4">
                {m.lines.map((l) => (
                  <div
                    key={l}
                    className="font-mono text-[11.5px] leading-relaxed text-emerald-200/55"
                  >
                    {l}
                  </div>
                ))}
              </div>
            </motion.div>
          ))}
        </div>

        <motion.div
          initial={{ opacity: 0, y: 18 }}
          animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 18 }}
          transition={{ duration: 0.7, delay: 0.45, ease: [0.22, 1, 0.36, 1] }}
          className="flex flex-wrap items-center gap-2.5"
        >
          {GUARANTEES.map((g) => (
            <span
              key={g}
              className="rounded-full border border-emerald-400/15 bg-emerald-400/[0.06] px-3.5 py-1.5 font-mono text-[11.5px] tracking-[0.02em] text-emerald-200/70"
            >
              {g}
            </span>
          ))}
        </motion.div>
      </div>
    </div>
  );
}
