"use client";

import { useEffect, useRef, useState } from "react";
import { motion, useInView } from "motion/react";

/**
 * The demo. One terminal that installs Irus and runs it against a repository
 * where two agents have just finished, so the whole product is visible in the
 * time it takes to read a screen.
 *
 * Lines are revealed one at a time rather than typed character by character:
 * a terminal reads as running either way, and per-line reveal costs one state
 * update per line instead of one per frame.
 */

type Tone = "cmd" | "dim" | "head" | "pass" | "fail" | "detail" | "sum" | "ok" | "blank";

type Line = { t: Tone; s: string; hold?: number };

// The commands are the real ones. Irus is not published to an index, so the
// install is the editable local install the README documents, and every verdict
// below is the recorded session's own output.
const SCRIPT: Line[] = [
  { t: "cmd", s: "$ pip install -e .", hold: 420 },
  { t: "dim", s: "Obtaining file:///work/checkout-service" },
  { t: "dim", s: "  Installing build dependencies ... done" },
  { t: "ok", s: "Successfully installed irus-0.1.0", hold: 520 },
  { t: "blank", s: "" },

  { t: "cmd", s: "$ irus check", hold: 380 },
  { t: "dim", s: "baseline acab5370f983 · 2 worktrees · no network", hold: 300 },
  { t: "blank", s: "" },

  { t: "head", s: "POST /api/checkout" },
  { t: "pass", s: "  endpoint exists        PASS" },
  { t: "pass", s: "  route mounted          PASS" },
  { t: "pass", s: "  client calls it        PASS" },
  { t: "fail", s: "  encoding matches       FAIL" },
  { t: "detail", s: "      client sends multipart, server expects json" },
  { t: "fail", s: "  payload shape matches  FAIL" },
  { t: "detail", s: "      server requires `amount` (int); `email` (str)", hold: 320 },
  { t: "blank", s: "" },

  { t: "head", s: "GET /api/orders/{id}" },
  { t: "fail", s: "  response shape matches FAIL" },
  { t: "detail", s: "      client reads `customer.name`, handler returns `customer_name`", hold: 300 },
  { t: "blank", s: "" },

  { t: "head", s: "STRIPE_WEBHOOK_SECRET" },
  { t: "fail", s: "  set somewhere          FAIL   medium" },
  { t: "blank", s: "" },

  { t: "head", s: "POST /api/refund" },
  { t: "fail", s: "  has a caller           FAIL   medium", hold: 340 },
  { t: "blank", s: "" },

  { t: "sum", s: "5 finding(s) introduced this session (3 high)" },
  { t: "sum", s: "baseline acab5370f983 suppressed 1 pre-existing" },
  { t: "cmd", s: "$ echo $?" },
  { t: "dim", s: "1", hold: 620 },
  { t: "blank", s: "" },

  { t: "cmd", s: "$ irus check --prove --app main:app", hold: 420 },
  { t: "ok", s: "f-1a2b3c  tier 1  request rejected before send" },
  { t: "ok", s: "f-4d5e6f  tier 2  422 Unprocessable Entity" },
  { t: "ok", s: "f-7a8b9c  tier 3  200 OK, body has no `customer` key", hold: 300 },
  { t: "sum", s: "3 of 3 high-confidence findings proven by execution", hold: 1600 },
];

const TONE: Record<Tone, string> = {
  cmd: "text-emerald-200/95",
  dim: "text-white/40",
  head: "text-white/85",
  pass: "text-emerald-300/70",
  fail: "text-rose-300/90",
  detail: "text-rose-200/50",
  sum: "text-white/55",
  ok: "text-emerald-300/85",
  blank: "",
};

// What the terminal is doing, in plain language, tracked to the line on screen.
const STEPS = [
  { at: 0, label: "Install", note: "Standard library only. No network, no build step, nothing to configure." },
  { at: 5, label: "Detect", note: "Reads both worktrees and compares what each side declares. No model in this path." },
  { at: 30, label: "Gate", note: "Exits non-zero on a high-confidence finding, so it works as a merge gate." },
  { at: 33, label: "Prove", note: "Runs the suspect seams. The verdict comes from the application, not from the checker." },
];

const LINE_MS = 90;

export default function DemoSection() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { margin: "200px" });
  const [shown, setShown] = useState(0);
  const [run, setRun] = useState(0);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!inView) return;
    setShown(0);
    let i = 0;
    let timer: ReturnType<typeof setTimeout>;
    const step = () => {
      i += 1;
      setShown(i);
      if (i >= SCRIPT.length) return;
      timer = setTimeout(step, LINE_MS + (SCRIPT[i - 1].hold ?? 0));
    };
    timer = setTimeout(step, 420);
    return () => clearTimeout(timer);
  }, [inView, run]);

  // Keep the newest line in view without moving the page itself.
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [shown]);

  const done = shown >= SCRIPT.length;
  const stepIndex = STEPS.reduce((acc, s, i) => (shown > s.at ? i : acc), 0);

  return (
    <div
      id="demo"
      ref={ref}
      className="relative isolate flex w-full items-center justify-center overflow-hidden bg-transparent pb-24 pt-8"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/2 -z-10 h-[40rem] w-[54rem] -translate-x-1/2 -translate-y-1/2 rounded-full blur-[140px]"
        style={{ background: "radial-gradient(circle, rgba(52,211,153,0.10), transparent 65%)" }}
      />

      <div className="relative z-10 mx-auto w-full max-w-6xl px-6 md:px-14">
        <motion.div
          initial={{ opacity: 0, y: 22 }}
          animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 22 }}
          transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
          className="relative isolate mb-8 max-w-3xl"
        >
          <div
            aria-hidden
            className="pointer-events-none absolute -inset-x-7 -inset-y-6 -z-10 rounded-[2rem] bg-[radial-gradient(ellipse_at_center,rgba(5,8,7,0.92),rgba(5,8,7,0.45)_62%,transparent_84%)] blur-md"
          />
          <div className="flex items-center gap-4">
            <span className="font-mono text-[11px] uppercase tracking-[0.28em] text-emerald-300/80">
              The demo
            </span>
            <span className="h-px w-16 flex-none bg-gradient-to-r from-emerald-400/50 to-transparent" />
          </div>
          <h2 className="mt-4 text-balance text-3xl font-medium leading-[1.05] tracking-tight text-white sm:text-4xl">
            Install it, run it, watch it fail the merge.
          </h2>
          <p className="mt-4 max-w-2xl text-pretty text-[14px] leading-relaxed text-white/55">
            A recorded run against a repository where two agents just finished their halves. Irus has
            never been run against a repository the author did not write, so its real-world
            false-positive rate is unmeasured. This is one session, not a public total.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 22 }}
          animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 22 }}
          transition={{ duration: 0.8, delay: 0.12, ease: [0.22, 1, 0.36, 1] }}
          className="grid items-start gap-6 md:grid-cols-[1.55fr_0.95fr]"
        >
          <div className="overflow-hidden rounded-2xl border border-white/[0.08] bg-[#070908]/95 shadow-[0_30px_80px_-20px_rgba(0,0,0,0.8),inset_0_1px_0_rgba(255,255,255,0.04)]">
            <div className="flex items-center gap-3 border-b border-white/[0.06] bg-white/[0.015] px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="h-3 w-3 rounded-full bg-[#ff5f57]/90" />
                <span className="h-3 w-3 rounded-full bg-[#febc2e]/90" />
                <span className="h-3 w-3 rounded-full bg-[#28c840]/90" />
              </div>
              <div className="flex flex-1 items-center justify-center gap-2">
                <span className="font-mono text-[11px] tracking-wide text-emerald-300/60">irus</span>
                <span className="text-white/15">·</span>
                <span className="font-mono text-[11px] tracking-wide text-white/35">demo</span>
              </div>
              <button
                type="button"
                onClick={() => setRun((n) => n + 1)}
                className="rounded-md border border-white/10 px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-white/35 transition-colors hover:border-emerald-400/30 hover:text-emerald-200/80"
              >
                replay
              </button>
            </div>

            <div ref={scroller} className="h-[26rem] overflow-y-auto overflow-x-auto px-4 py-4">
              <pre className="font-mono text-[11.5px] leading-[1.75] md:text-[12.5px]">
                {SCRIPT.slice(0, shown).map((l, i) => (
                  <div key={i} className={TONE[l.t]}>
                    {l.s === "" ? " " : l.s}
                  </div>
                ))}
                {!done && (
                  <span className="inline-block h-[1.05em] w-[0.55em] translate-y-[0.18em] animate-pulse bg-emerald-300/70" />
                )}
              </pre>
            </div>
          </div>

          <div className="flex flex-col gap-2.5">
            {STEPS.map((s, i) => {
              const active = i === stepIndex;
              const passed = i < stepIndex;
              return (
                <div
                  key={s.label}
                  className={`rounded-xl border px-4 py-3 transition-colors duration-500 ${
                    active
                      ? "border-emerald-400/30 bg-emerald-400/[0.07]"
                      : "border-emerald-400/10 bg-[#070b09]/85"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`h-1.5 w-1.5 rounded-full transition-colors duration-500 ${
                        active ? "bg-emerald-300" : passed ? "bg-emerald-400/40" : "bg-white/15"
                      }`}
                    />
                    <span
                      className={`font-mono text-[11px] uppercase tracking-[0.14em] transition-colors duration-500 ${
                        active ? "text-emerald-300" : "text-white/35"
                      }`}
                    >
                      {s.label}
                    </span>
                  </div>
                  <div className="mt-1.5 text-[13px] leading-relaxed text-white/45">{s.note}</div>
                </div>
              );
            })}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
