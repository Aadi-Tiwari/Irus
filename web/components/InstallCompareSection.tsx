"use client";

import { useRef, useState } from "react";
import { motion, useInView, type Variants } from "motion/react";

const ease = [0.22, 1, 0.36, 1] as const;

const rise: Variants = {
  hidden: { opacity: 0, y: 22, filter: "blur(8px)" },
  show: {
    opacity: 1,
    y: 0,
    filter: "blur(0px)",
    transition: { duration: 0.8, ease },
  },
};

const container: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.1, delayChildren: 0.15 } },
};

const GITHUB_URL = "https://github.com/Aadi-Tiwari/irus";

/* ──────────────────────────────────────────────────────────────────────────
 * Tiny inline icons (no extra deps): copy / check / github / arrow.
 * ────────────────────────────────────────────────────────────────────────── */
function CopyIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="9" y="9" width="11" height="11" rx="2" stroke="currentColor" strokeWidth="1.7" />
      <path
        d="M5 15V5a2 2 0 0 1 2-2h8"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M5 12.5 10 17.5 19 7"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function GithubIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M12 1.5C6.2 1.5 1.5 6.2 1.5 12c0 4.64 3.01 8.57 7.18 9.96.53.1.72-.23.72-.51 0-.25-.01-.92-.01-1.8-2.92.63-3.54-1.41-3.54-1.41-.48-1.22-1.17-1.54-1.17-1.54-.95-.65.07-.64.07-.64 1.06.07 1.61 1.09 1.61 1.09.94 1.6 2.46 1.14 3.06.87.1-.68.37-1.14.67-1.4-2.33-.27-4.78-1.17-4.78-5.19 0-1.15.41-2.08 1.09-2.82-.11-.27-.47-1.34.1-2.79 0 0 .89-.28 2.91 1.08a10.1 10.1 0 0 1 2.65-.36c.9 0 1.8.12 2.65.36 2.02-1.36 2.9-1.08 2.9-1.08.58 1.45.22 2.52.11 2.79.68.74 1.09 1.67 1.09 2.82 0 4.03-2.46 4.92-4.8 5.18.38.33.71.97.71 1.96 0 1.41-.01 2.55-.01 2.9 0 .28.19.62.73.51A10.52 10.52 0 0 0 22.5 12c0-5.8-4.7-10.5-10.5-10.5Z" />
    </svg>
  );
}

/* ──────────────────────────────────────────────────────────────────────────
 * Copyable command card. Click the row (or the button) to copy.
 * ────────────────────────────────────────────────────────────────────────── */
function CommandCard({
  label,
  command,
  copied,
  onCopy,
}: {
  label: string;
  command: string;
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onCopy}
      aria-label={`Copy the ${label} command`}
      className="group relative w-full overflow-hidden rounded-xl border border-white/[0.08] bg-gradient-to-b from-[#0e0f0e] to-[#0a0b0a] px-4 py-3 text-left transition-colors duration-300 hover:border-emerald-400/30"
    >
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-emerald-300/80">
          {label}
        </span>
        <span
          className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-[10px] tracking-wide transition-colors ${
            copied
              ? "border-emerald-400/40 bg-emerald-400/15 text-emerald-200"
              : "border-white/10 bg-white/[0.03] text-white/45 group-hover:border-emerald-400/30 group-hover:text-emerald-200/80"
          }`}
        >
          {copied ? <CheckIcon /> : <CopyIcon />}
          {copied ? "Copied" : "Copy"}
        </span>
      </div>
      <div className="mt-2 flex items-baseline gap-2 font-mono text-[13px] leading-relaxed text-white/85">
        <span className="select-none text-emerald-400/70">$</span>
        <span className="break-all text-pretty">{command}</span>
      </div>
    </button>
  );
}

/* ──────────────────────────────────────────────────────────────────────────
 * Comparison table: Irus against the tools that already exist for this bug.
 * Source of truth: the positioning section of the adaptation brief. Honest,
 * not a clean sweep. Pact genuinely catches this bug once the tests are
 * written, Schemathesis genuinely sends real requests, and tRPC genuinely
 * derives the client from the server. Irus wins on reading both sides of
 * unmerged code with no spec and no hand-written tests.
 * ────────────────────────────────────────────────────────────────────────── */
type Mark = "yes" | "no" | "part";

const COLS = ["Irus", "Pact", "Schemathesis", "tRPC"] as const;

const ROWS: { label: string; marks: [Mark, Mark, Mark, Mark] }[] = [
  { label: "Catches JSON versus multipart", marks: ["yes", "yes", "no", "part"] },
  { label: "Reads both sides of the code", marks: ["yes", "no", "no", "yes"] },
  { label: "No spec and no hand-written tests", marks: ["yes", "no", "no", "yes"] },
  { label: "Works when either side is not TypeScript", marks: ["yes", "yes", "yes", "no"] },
  { label: "No broker or CI wiring on both sides", marks: ["yes", "no", "yes", "yes"] },
  { label: "Runs on unmerged branches, before merge", marks: ["yes", "no", "no", "no"] },
  { label: "A hand-written fetch() cannot bypass it", marks: ["yes", "part", "no", "no"] },
  { label: "Proves it by running the request", marks: ["yes", "yes", "yes", "no"] },
];

function MarkCell({ mark, hero }: { mark: Mark; hero?: boolean }) {
  if (mark === "yes") {
    return (
      <span
        className={`inline-flex h-5 w-5 items-center justify-center rounded-full ${
          hero
            ? "bg-emerald-400/20 text-emerald-300"
            : "bg-emerald-400/10 text-emerald-300/80"
        }`}
      >
        <CheckIcon />
      </span>
    );
  }
  if (mark === "part") {
    return (
      <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-amber-300/10 font-mono text-[13px] leading-none text-amber-300/70">
        ~
      </span>
    );
  }
  return (
    <span className="inline-flex h-5 w-5 items-center justify-center font-mono text-[15px] leading-none text-white/20">
      ✕
    </span>
  );
}

function ComparisonTable({ inView }: { inView: boolean }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.96, y: 22 }}
      animate={inView ? { opacity: 1, scale: 1, y: 0 } : { opacity: 0, scale: 0.96, y: 22 }}
      transition={{ duration: 0.9, ease, delay: 0.25 }}
      className="relative w-full"
    >
      {/* soft emerald aura behind the card */}
      <div
        aria-hidden
        className="pointer-events-none absolute -inset-6 -z-10 rounded-[28px] bg-emerald-400/[0.05] blur-3xl"
      />
      <div className="overflow-hidden rounded-2xl border border-white/[0.08] bg-gradient-to-b from-[#0e0f0e] to-[#0a0b0a] shadow-[0_30px_80px_-20px_rgba(0,0,0,0.8),inset_0_1px_0_rgba(255,255,255,0.04)] backdrop-blur-sm">
        {/* grid: capability label + 4 product columns */}
        <div className="grid grid-cols-[1.55fr_repeat(4,minmax(0,1fr))]">
          {/* ── Header row ─────────────────────────────────────────────── */}
          <div className="border-b border-white/[0.07] px-4 py-3 text-[10px] font-medium uppercase tracking-[0.16em] text-white/35">
            Capability
          </div>
          {COLS.map((c, i) => (
            <div
              key={c}
              className={`relative border-b px-1.5 py-3 text-center text-[10.5px] font-semibold leading-tight ${
                i === 0
                  ? "border-emerald-400/30 bg-emerald-400/[0.07] text-emerald-200"
                  : "border-white/[0.07] text-white/45"
              }`}
            >
              {i === 0 && (
                <span
                  aria-hidden
                  className="pointer-events-none absolute inset-x-0 -top-px h-[2px] bg-gradient-to-r from-transparent via-emerald-400/70 to-transparent"
                />
              )}
              {c}
            </div>
          ))}

          {/* ── Capability rows ────────────────────────────────────────── */}
          {ROWS.map((row, ri) => (
            <Row key={row.label} row={row} last={ri === ROWS.length - 1} />
          ))}
        </div>
      </div>

      <p className="mt-4 text-center text-[11.5px] leading-relaxed text-white/35">
        Contract tests catch this once every interaction has a hand-written test
        and a broker. Irus reads both sides as they already are, then proves the
        mismatch by running it.
      </p>
    </motion.div>
  );
}

function Row({
  row,
  last,
}: {
  row: { label: string; marks: [Mark, Mark, Mark, Mark] };
  last: boolean;
}) {
  const border = last ? "" : "border-b border-white/[0.05]";
  return (
    <>
      <div className={`px-4 py-2.5 text-[12px] leading-snug text-white/65 ${border}`}>
        {row.label}
      </div>
      {row.marks.map((m, i) => (
        <div
          key={i}
          className={`flex items-center justify-center px-1.5 py-2.5 ${border} ${
            i === 0 ? "bg-emerald-400/[0.05]" : ""
          }`}
        >
          <MarkCell mark={m} hero={i === 0} />
        </div>
      ))}
    </>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
export default function InstallCompareSection() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { amount: 0.3 });

  // which command card was most recently copied (-1 = none)
  const [copied, setCopied] = useState(-1);
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const COMMANDS = [
    { label: "Install", command: "pip install -e ." },
    { label: "Terminal · check", command: "irus check" },
  ];

  const copy = (i: number) => {
    const text = COMMANDS[i].command;
    navigator.clipboard?.writeText(text).catch(() => {});
    setCopied(i);
    if (resetTimer.current) clearTimeout(resetTimer.current);
    resetTimer.current = setTimeout(() => setCopied(-1), 1800);
  };

  return (
    <section
      id="install"
      data-snap
      ref={ref}
      className="relative isolate flex min-h-screen w-full items-center justify-center overflow-hidden bg-transparent py-20"
    >
      {/* ── Ambient emerald glow, matching sibling sections ─────────────── */}
      <motion.div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/2 -z-10 h-[44rem] w-[56rem] -translate-x-1/2 -translate-y-1/2 rounded-full blur-[140px]"
        animate={{ opacity: [0.5, 0.75, 0.5], scale: [1, 1.04, 1] }}
        transition={{ duration: 14, repeat: Infinity, ease: "easeInOut" }}
        style={{
          background: "radial-gradient(circle, rgba(52,211,153,0.12), transparent 64%)",
        }}
      />
      {/* faint dotted texture */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 opacity-[0.5]"
        style={{
          backgroundImage: "radial-gradient(rgba(52,211,153,0.05) 1px, transparent 1px)",
          backgroundSize: "34px 34px",
          maskImage: "radial-gradient(ellipse 75% 70% at 50% 50%, black, transparent 82%)",
        }}
      />
      <div className="relative z-10 mx-auto grid w-full max-w-6xl grid-cols-1 items-center gap-12 px-6 md:grid-cols-2 md:gap-14 lg:gap-20">
        {/* ── LEFT: install ──────────────────────────────────────────────── */}
        <motion.div
          variants={container}
          initial="hidden"
          animate={inView ? "show" : "hidden"}
          className="relative flex flex-col"
        >
          {/* soft dark scrim so the heading + copy stay readable over the canopy */}
          <div
            aria-hidden
            className="pointer-events-none absolute -inset-x-7 -inset-y-6 -z-10 rounded-[2rem] bg-[radial-gradient(ellipse_at_center,rgba(5,8,7,0.92),rgba(5,8,7,0.45)_62%,transparent_84%)] blur-md"
          />
          <motion.h2
            variants={rise}
            className="text-balance text-3xl font-medium leading-[1.05] tracking-tight text-white sm:text-4xl lg:text-[2.9rem]"
          >
            Install in one line.{" "}
            <span className="text-emerald-300/90">Then one command.</span>
          </motion.h2>

          <motion.p
            variants={rise}
            className="mt-5 max-w-md text-pretty text-[14.5px] leading-relaxed text-white/60 md:text-[15px]"
          >
            The engine has no required dependencies. Standard library only, no
            network, no build step, nothing to install on a fresh machine. Two
            optional extras exist: &quot;.[config]&quot; adds PyYAML, and
            &quot;.[prove]&quot; adds starlette and httpx for execution proof.
          </motion.p>

          <motion.div variants={rise} className="mt-7 flex flex-col gap-3">
            {COMMANDS.map((c, i) => (
              <CommandCard
                key={c.label}
                label={c.label}
                command={c.command}
                copied={copied === i}
                onCopy={() => copy(i)}
              />
            ))}
          </motion.div>

          <motion.div variants={rise} className="mt-6 flex flex-wrap items-center gap-3">
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-xl border border-white/12 bg-white/[0.04] px-4 py-2.5 text-sm font-medium text-white/85 transition-colors duration-300 hover:border-emerald-400/30 hover:bg-emerald-400/[0.06] hover:text-white"
            >
              <GithubIcon />
              View on GitHub
            </a>
            <span className="inline-flex items-center gap-2 text-[12.5px] text-white/40">
              or
              <code className="rounded-md border border-emerald-400/20 bg-emerald-400/[0.07] px-1.5 py-0.5 font-mono text-[12px] text-emerald-200/90">
                irus check --prove
              </code>
              to run the suspect seams
            </span>
          </motion.div>
        </motion.div>

        {/* ── RIGHT: comparison ──────────────────────────────────────────── */}
        <div className="w-full">
          <motion.span
            initial={{ opacity: 0, y: 12 }}
            animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 12 }}
            transition={{ duration: 0.7, ease, delay: 0.15 }}
            className="mb-4 ml-1 inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.22em] text-white/35"
          >
            <span className="h-px w-6 bg-gradient-to-r from-emerald-400/60 to-transparent" />
            What this costs today
          </motion.span>
          <ComparisonTable inView={inView} />
        </div>
      </div>
    </section>
  );
}
