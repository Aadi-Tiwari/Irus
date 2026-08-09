"use client";

import { useMemo, useRef, useState } from "react";
import { motion, useInView, type Variants } from "motion/react";

import {
  BASELINE_SHA,
  FINAL_STATS,
  FINDINGS,
  type Confidence,
  type Finding,
} from "@/lib/session-fixture";
import { useSession } from "@/lib/useSession";
import SeamMap from "@/components/dashboard/SeamMap";

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
  show: { transition: { staggerChildren: 0.08, delayChildren: 0.1 } },
};

/* ──────────────────────────────────────────────────────────────────────────
 * The findings of the recorded session, arriving in the order `irus watch`
 * streams them. Nothing here is a public total: Irus has never been run against
 * a repository the author did not write, so the section says that out loud
 * instead of showing a number it has not earned.
 * ────────────────────────────────────────────────────────────────────────── */
const KINDS = ["All", ...Array.from(new Set(FINDINGS.map((f) => f.kind)))];

/* confidence tier → tailwind text/bar colours. The bar is an ordinal encoding of
   the tier, never a score: unknown is our limitation, so it leans amber. */
const CONFIDENCE_FILL: Record<Confidence, number> = {
  high: 1,
  medium: 0.6,
  unknown: 0.25,
};

function confidenceTone(c: Confidence) {
  if (c === "high") return { text: "text-emerald-300", bar: "bg-emerald-400/80" };
  if (c === "medium") return { text: "text-emerald-200", bar: "bg-emerald-400/60" };
  return { text: "text-amber-300", bar: "bg-amber-400/70" };
}

/* ── icons ─────────────────────────────────────────────────────────────── */
function SearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.7" />
      <path d="m20 20-3.2-3.2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}
function CopyIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="9" y="9" width="11" height="11" rx="2" stroke="currentColor" strokeWidth="1.7" />
      <path d="M5 15V5a2 2 0 0 1 2-2h8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}
function CheckIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M5 12.5 10 17.5 19 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* ── confidence pill with a tiny fill bar ──────────────────────────────── */
function ConfidenceBadge({ confidence, compact }: { confidence: Confidence; compact?: boolean }) {
  const tone = confidenceTone(confidence);
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`font-mono text-[12px] tabular-nums ${tone.text}`}>
        {confidence}
      </span>
      <span className={`relative ${compact ? "h-1 w-10" : "h-1.5 w-16"} overflow-hidden rounded-full bg-white/10`}>
        <span
          className={`absolute inset-y-0 left-0 rounded-full ${tone.bar}`}
          style={{ width: `${Math.round(CONFIDENCE_FILL[confidence] * 100)}%` }}
        />
      </span>
    </span>
  );
}

/* ── the inspector card (right column) ─────────────────────────────────── */
function Inspector({ finding }: { finding: Finding }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // `claim` is advisory coordination over one piece of work, which is what a
  // finding is. The graph is for humans, this string is for the agent.
  const cmd = `claim("${finding.id}")`;
  const copy = () => {
    navigator.clipboard?.writeText(cmd).catch(() => {});
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1800);
  };

  return (
    <div className="relative">
      <div
        aria-hidden
        className="pointer-events-none absolute -inset-6 -z-10 rounded-[28px] bg-emerald-400/[0.06] blur-3xl"
      />
      <div className="overflow-hidden rounded-2xl border border-white/[0.08] bg-gradient-to-b from-[#0e0f0e] to-[#0a0b0a] shadow-[0_30px_80px_-20px_rgba(0,0,0,0.8),inset_0_1px_0_rgba(255,255,255,0.04)] backdrop-blur-sm">
        {/* title bar */}
        <div className="flex items-center gap-3 border-b border-white/[0.06] bg-white/[0.015] px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-full bg-[#ff5f57]/90" />
            <span className="h-3 w-3 rounded-full bg-[#febc2e]/90" />
            <span className="h-3 w-3 rounded-full bg-[#28c840]/90" />
          </div>
          <div className="flex flex-1 items-center justify-center gap-2">
            <span className="font-mono text-[11px] tracking-wide text-emerald-300/60">irus</span>
            <span className="text-white/15">·</span>
            <span className="font-mono text-[11px] tracking-wide text-white/35">watch</span>
          </div>
          <div className="h-3 w-[52px]" />
        </div>

        <div className="px-5 py-4">
          {/* seam + kind */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[15px] font-medium text-white">{finding.seam}</span>
            <span className="rounded-md border border-emerald-400/20 bg-emerald-400/[0.07] px-1.5 py-px font-mono text-[10px] uppercase tracking-wide text-emerald-200/90">
              {finding.kind}
            </span>
            <span className="rounded-md border border-white/10 bg-white/[0.03] px-1.5 py-px font-mono text-[10px] text-white/45">
              {finding.id}
            </span>
          </div>

          <p className="mt-3 text-[13.5px] leading-relaxed text-white/65">{finding.detail}</p>

          {/* confidence + authority */}
          <div className="mt-4 grid grid-cols-2 gap-3">
            <div className="rounded-xl border border-white/[0.07] bg-white/[0.015] px-3 py-2.5">
              <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-white/35">Confidence</div>
              <div className="mt-1.5">
                <ConfidenceBadge confidence={finding.confidence} />
              </div>
              <div className="mt-1.5 font-mono text-[10.5px] text-white/30">
                {finding.confidence === "high" ? "fails the merge gate" : "reported, never gating"}
              </div>
            </div>
            <div className="rounded-xl border border-white/[0.07] bg-white/[0.015] px-3 py-2.5">
              <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-white/35">Authority</div>
              <div className="mt-1.5 font-mono text-[14px] tabular-nums text-emerald-200/90">
                {finding.authority}
              </div>
              <div className="mt-1.5 font-mono text-[10.5px] text-white/30">
                written into the receipt
              </div>
            </div>
          </div>

          {/* stage 2 verdict */}
          <div className="mt-3">
            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-white/35">proof</div>
            <div className="mt-1.5 flex items-start gap-2 rounded-lg border border-white/[0.06] bg-black/30 px-3 py-2 font-mono text-[12px] text-white/70">
              <span className="select-none text-emerald-400/80">✓</span>
              <span className="text-pretty">
                {finding.proof
                  ? `tier ${finding.proof.tier}: ${finding.proof.verdict}`
                  : "stage 2 has not run for this seam"}
              </span>
            </div>
          </div>

          {/* both sides of the boundary */}
          <div className="mt-3">
            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-white/35">Both sides</div>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {[finding.producer, finding.consumer ?? "no consumer in either worktree"].map((e) => (
                <span
                  key={e}
                  className="rounded-md border border-emerald-400/15 bg-emerald-400/[0.06] px-2 py-0.5 font-mono text-[11px] text-emerald-100/80"
                >
                  {e}
                </span>
              ))}
            </div>
          </div>

          {/* copy the tool call */}
          <button
            type="button"
            onClick={copy}
            className="group mt-4 flex w-full items-center justify-between rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2 text-left transition-colors hover:border-emerald-400/30"
          >
            <span className="font-mono text-[12px] text-white/70">
              <span className="text-emerald-400/70">›</span> {cmd}
            </span>
            <span
              className={`inline-flex items-center gap-1 font-mono text-[10px] tracking-wide ${
                copied ? "text-emerald-300" : "text-white/40 group-hover:text-emerald-200/80"
              }`}
            >
              {copied ? <CheckIcon /> : <CopyIcon />}
              {copied ? "Copied" : "Copy"}
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
export default function SessionLedgerSection() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { amount: 0.25 });

  // The recorded session, replaying. Findings append in the order the event log
  // streams them, so the list fills the way `irus watch` fills.
  const { findings, nodes, edges, pulse } = useSession();

  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("All");
  const [selected, setSelected] = useState(FINDINGS[0].id);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return findings.filter((f) => {
      const inKind = kind === "All" || f.kind === kind;
      const inQ =
        !q ||
        f.seam.toLowerCase().includes(q) ||
        f.detail.toLowerCase().includes(q) ||
        f.kind.toLowerCase().includes(q) ||
        f.producer.toLowerCase().includes(q);
      return inKind && inQ;
    });
  }, [query, kind, findings]);

  // the inspector follows the selection, falling back to the first visible row.
  const selectedFinding =
    findings.find((f) => f.id === selected && filtered.includes(f)) ?? filtered[0] ?? null;

  const highCount = findings.filter((f) => f.confidence === "high").length;

  return (
    <div
      id="dashboard"
      ref={ref}
      className="relative isolate flex w-full items-center justify-center overflow-hidden bg-transparent pb-24 pt-8"
    >
      {/* ambient glow */}
      <motion.div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/2 -z-10 h-[44rem] w-[58rem] -translate-x-1/2 -translate-y-1/2 rounded-full blur-[140px]"
        animate={{ opacity: [0.5, 0.72, 0.5], scale: [1, 1.04, 1] }}
        transition={{ duration: 15, repeat: Infinity, ease: "easeInOut" }}
        style={{ background: "radial-gradient(circle, rgba(52,211,153,0.11), transparent 64%)" }}
      />
      {/* dotted texture */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 opacity-[0.5]"
        style={{
          backgroundImage: "radial-gradient(rgba(52,211,153,0.05) 1px, transparent 1px)",
          backgroundSize: "34px 34px",
          maskImage: "radial-gradient(ellipse 80% 72% at 50% 50%, black, transparent 82%)",
        }}
      />
      <div className="relative z-10 mx-auto w-full max-w-7xl px-6 md:px-14">
        {/* ── TOP: the beat's own heading, then the map it describes ─────── */}
        <motion.div variants={container} initial="hidden" animate={inView ? "show" : "hidden"}>
          <div className="relative isolate mb-8 max-w-3xl">
            {/* soft dark scrim so the heading + copy stay readable over the plate */}
            <div
              aria-hidden
              className="pointer-events-none absolute -inset-x-7 -inset-y-6 -z-10 rounded-[2rem] bg-[radial-gradient(ellipse_at_center,rgba(5,8,7,0.92),rgba(5,8,7,0.45)_62%,transparent_84%)] blur-md"
            />
            <motion.div variants={rise} className="flex items-center gap-4">
              <span className="font-mono text-[11px] uppercase tracking-[0.28em] text-emerald-300/80">
                The live map
              </span>
              <span className="h-px w-16 flex-none bg-gradient-to-r from-emerald-400/50 to-transparent" />
            </motion.div>
            <motion.h2
              variants={rise}
              className="mt-4 text-balance text-3xl font-medium leading-[1.05] tracking-tight text-white sm:text-4xl"
            >
              Every seam this session touched.
            </motion.h2>
            <motion.p variants={rise} className="mt-4 max-w-2xl text-pretty text-[14px] leading-relaxed text-white/55">
              The recorded session, replaying. Irus has never been run against a repository the author did not write, so its real-world false-positive rate is unmeasured. This is what one session looks like, not a public total.
            </motion.p>
            <motion.div variants={rise} className="mt-5 flex flex-wrap gap-2">
              {[
                { k: `${findings.length} findings`, sub: "this session" },
                { k: `${highCount} high`, sub: "confidence" },
                { k: `${FINAL_STATS.baseline_suppressed} suppressed`, sub: `by ${BASELINE_SHA}` },
              ].map((s) => (
                <div key={s.sub} className="rounded-lg border border-emerald-400/10 bg-[#070b09]/85 px-3 py-1.5 backdrop-blur-md">
                  <span className="font-mono text-[13px] font-medium tabular-nums text-emerald-200/90">{s.k}</span>{" "}
                  <span className="font-mono text-[10.5px] uppercase tracking-wide text-white/35">{s.sub}</span>
                </div>
              ))}
            </motion.div>
          </div>
          <motion.div variants={rise} className="w-full">
            <div className="relative h-[52vh] min-h-[380px] w-full overflow-hidden rounded-2xl border border-white/[0.08] bg-gradient-to-b from-[#0c0d0c] to-[#0a0b0a] shadow-[0_30px_80px_-20px_rgba(0,0,0,0.8),inset_0_1px_0_rgba(255,255,255,0.04)]">
              <SeamMap nodes={nodes} edges={edges} pulse={pulse} />
            </div>
            <p className="mt-2.5 max-w-2xl font-mono text-[10.5px] leading-relaxed tracking-wide text-white/35">
              A dashed red arc is a connection that should exist and does not. Node size is blast
              radius, and the dim nodes are the baseline.
            </p>
          </motion.div>
        </motion.div>

        {/* ── BOTTOM: the ledger, under the map ──────────────────────────── */}
        <div className="mt-10 grid grid-cols-1 items-start gap-10 md:grid-cols-[1.2fr_0.8fr] md:gap-12">
        {/* ── LEFT: catalog ──────────────────────────────────────────────── */}
        <motion.div variants={container} initial="hidden" animate={inView ? "show" : "hidden"} className="flex flex-col">
          {/* search */}
          <motion.div variants={rise}>
            <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-[#070b09]/85 px-3 py-2.5 backdrop-blur-md transition-colors focus-within:border-emerald-400/40">
              <span className="text-white/35">
                <SearchIcon />
              </span>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search findings. Try “checkout”, “encoding”, “orphan”…"
                className="w-full bg-transparent font-mono text-[13px] text-white/85 placeholder:text-white/25 focus:outline-none"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => setQuery("")}
                  className="font-mono text-[11px] text-white/30 hover:text-white/60"
                >
                  clear
                </button>
              )}
            </div>

            {/* seam-kind pills */}
            <div className="mt-3 flex flex-wrap gap-1.5">
              {KINDS.map((c) => {
                const active = c === kind;
                return (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setKind(c)}
                    className={`rounded-full border px-3 py-1 font-mono text-[11px] tracking-wide transition-colors ${
                      active
                        ? "border-emerald-400/40 bg-emerald-400/[0.12] text-emerald-200"
                        : "border-emerald-400/10 bg-[#070b09]/85 text-white/55 backdrop-blur-md hover:border-emerald-400/25 hover:text-emerald-200/80"
                    }`}
                  >
                    {c}
                  </button>
                );
              })}
            </div>
          </motion.div>

          {/* findings list, native-scrolls without triggering the page snap */}
          <motion.div
            variants={rise}
            onWheel={(e) => e.stopPropagation()}
            onTouchMove={(e) => e.stopPropagation()}
            className="mt-4 max-h-[38vh] space-y-2 overflow-y-auto pr-1 [scrollbar-width:thin]"
          >
            {filtered.map((s) => {
              const active = selectedFinding?.id === s.id;
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setSelected(s.id)}
                  className={`group flex w-full items-center gap-3 rounded-xl border px-3.5 py-2.5 text-left backdrop-blur-md transition-colors ${
                    active
                      ? "border-emerald-400/40 bg-[#0c1712]/90"
                      : "border-emerald-400/10 bg-[#070b09]/85 hover:border-emerald-400/25 hover:bg-[#0a120e]/90"
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-mono text-[13px] font-medium text-white/90">{s.seam}</span>
                      <span className="flex-none rounded border border-white/10 bg-white/[0.03] px-1 py-px font-mono text-[9.5px] uppercase tracking-wide text-white/40">
                        {s.kind}
                      </span>
                    </div>
                    <div className="mt-1 truncate text-[12px] text-white/45">{s.detail}</div>
                  </div>
                  <div className="flex flex-none flex-col items-end gap-1">
                    <ConfidenceBadge confidence={s.confidence} compact />
                    <span className="font-mono text-[10px] text-white/30">
                      {s.proof ? `tier ${s.proof.tier} proof` : "not proved"}
                    </span>
                  </div>
                </button>
              );
            })}

            {filtered.length === 0 && (
              <div className="rounded-xl border border-dashed border-white/10 px-4 py-6 text-center text-[13px] text-white/40">
                {query
                  ? `No findings match “${query}” in this session.`
                  : "Waiting for the sweep to report."}
              </div>
            )}

            {/* the ledger, which is the honest part */}
            {filtered.length > 0 && (
              <div className="flex items-center gap-2 rounded-xl border border-dashed border-emerald-400/15 bg-emerald-400/[0.015] px-3.5 py-2.5 text-[12px] text-white/40">
                <span className="font-mono text-emerald-300/70">+</span>
                <span>
                  <span className="font-mono text-white/55">irus ledger</span> runs unfiltered and
                  publishes every finding for hand labelling, including the wrong ones. It is not
                  filled in yet.
                </span>
              </div>
            )}
          </motion.div>
        </motion.div>

        {/* ── RIGHT: inspector ───────────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, scale: 0.96, y: 22 }}
          animate={inView ? { opacity: 1, scale: 1, y: 0 } : { opacity: 0, scale: 0.96, y: 22 }}
          transition={{ duration: 0.9, ease, delay: 0.2 }}
          className="w-full md:sticky md:top-24"
        >
          {selectedFinding ? (
            <Inspector finding={selectedFinding} />
          ) : (
            <div className="rounded-2xl border border-dashed border-white/10 px-6 py-16 text-center text-[13px] text-white/40">
              Select a finding to inspect it.
            </div>
          )}
        </motion.div>
        </div>
      </div>
    </div>
  );
}
