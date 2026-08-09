"use client";

import { motion, useAnimationFrame } from "motion/react";
import { useMemo, useRef, useState } from "react";

import { MEASURED, SCALES, derived } from "@/lib/scale";
import type { Stats } from "@/lib/useSession";

/* ------------------------------------------------------------------ *
 *  ScaledLatency: the memorable closer.                                *
 *                                                                     *
 *  Takes the two measured latencies and says what they mean at repo   *
 *  sizes people actually work at. The sweep is linear in source       *
 *  files, so every row here is arithmetic on one measurement rather   *
 *  than a second measurement, and each row says so.                   *
 *                                                                     *
 *  Then a full-width "MEASURED" crescendo shows the two numbers       *
 *  themselves against the budgets they were written to hold. Nothing  *
 *  here is projected past what was run.                               *
 *                                                                     *
 *  Aesthetic: near-black, emerald-only accents at low opacity, mono   *
 *  tabular numerals, ambient blur blobs, dotted texture, hairline     *
 *  "frame as glow". No external libraries: every visual is inline     *
 *  SVG drawn with hand-authored emerald strokes.                      *
 * ------------------------------------------------------------------ */

const EMERALD = "#34d399";
const EMERALD_LIGHT = "#6ee7b7";
const EMERALD_PALE = "#a7f3d0";

const EASE = [0.22, 1, 0.36, 1] as const;

/* ----------------------------- icons ------------------------------- *
 *  Simple hand-drawn emerald strokes on a 24x24 grid. currentColor so *
 *  the parent controls the glow tint.                                 */

type IconProps = { size?: number };

function HomeIcon({ size = 22 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M4 11.2 12 4l8 7.2"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M6 10v9h12v-9"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="currentColor"
        fillOpacity={0.08}
      />
      <path
        d="M10 19v-4.2h4V19"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CarIcon({ size = 22 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M3.5 15.5v-2.2l1.8-4.1A2 2 0 0 1 7.1 8h9.8a2 2 0 0 1 1.8 1.2l1.8 4.1v2.2"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="currentColor"
        fillOpacity={0.07}
      />
      <path
        d="M3.5 15.5h17"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
      />
      <circle cx={7.2} cy={16} r={1.7} stroke="currentColor" strokeWidth={1.5} />
      <circle cx={16.8} cy={16} r={1.7} stroke="currentColor" strokeWidth={1.5} />
      <path
        d="M5.6 12.6h12.8"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        opacity={0.55}
      />
    </svg>
  );
}

function TreeIcon({ size = 22 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 3.5 6.5 11h3L6 16h5v4h2v-4h5l-3.5-5h3L12 3.5Z"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        fill="currentColor"
        fillOpacity={0.1}
      />
    </svg>
  );
}

function DropIcon({ size = 22 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 3.5c3.4 4 6 7 6 10a6 6 0 1 1-12 0c0-3 2.6-6 6-10Z"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinejoin="round"
        fill="currentColor"
        fillOpacity={0.1}
      />
      <path
        d="M9.4 14.6a2.6 2.6 0 0 0 2.1 2.1"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
      />
    </svg>
  );
}

function PhoneIcon({ size = 22 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect
        x={7}
        y={3}
        width={10}
        height={18}
        rx={2.2}
        stroke="currentColor"
        strokeWidth={1.5}
        fill="currentColor"
        fillOpacity={0.06}
      />
      <path
        d="M10.5 18.4h3"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
      />
      <path
        d="M12.7 8.2 10.4 12h2.4l-1.5 3.4"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

/* --------------------------- count-up ------------------------------ *
 *  A single animated number. It eases from its previous displayed     *
 *  value toward `target` whenever target changes, driven off one      *
 *  shared rAF loop in the parent. On the frame a value reaches a new  *
 *  target we briefly flash, which the parent reads to pulse the glow. */

type Format = (n: number) => string;

function useCountUp(target: number, duration = 1400) {
  const fromRef = useRef(0);
  const toRef = useRef(target);
  const startRef = useRef<number | null>(null);
  const valueRef = useRef(0);
  const pulseRef = useRef(0);
  const [value, setValue] = useState(0);
  const [pulse, setPulse] = useState(0); // 0..1, decays after a retarget

  useAnimationFrame((now) => {
    // Re-anchor when the target changes, done HERE (not during render), so it's
    // StrictMode-safe and never mutates refs / setState mid-render.
    if (toRef.current !== target) {
      fromRef.current = valueRef.current;
      toRef.current = target;
      startRef.current = null;
      pulseRef.current = 1;
    }
    if (startRef.current === null) startRef.current = now;
    const p = Math.min(1, (now - startRef.current) / duration);
    // easeOutExpo: fast out the gate, soft settle.
    const eased = p === 1 ? 1 : 1 - Math.pow(2, -10 * p);
    const next = fromRef.current + (toRef.current - fromRef.current) * eased;
    if (Math.abs(next - valueRef.current) > 1e-4) {
      valueRef.current = next;
      setValue(next);
    }
    // Decay the glow pulse; only commit while it's actually moving, then settle once,
    // so the component stops re-rendering at rest instead of churning every frame.
    if (pulseRef.current > 0) {
      pulseRef.current = Math.max(0, pulseRef.current - 0.045);
      setPulse(pulseRef.current);
    } else if (pulse !== 0) {
      setPulse(0);
    }
  });

  return { value, pulse };
}

/* ----------------------------- formats ----------------------------- */

const fmtInt: Format = (n) =>
  Math.round(Math.max(0, n)).toLocaleString("en-US");

const fmtSmart: Format = (n) => {
  const v = Math.max(0, n);
  if (v >= 1000) return Math.round(v).toLocaleString("en-US");
  if (v >= 100) return v.toFixed(0);
  if (v >= 10) return v.toFixed(1);
  return v.toFixed(2);
};

/* --------------------------- equivalent ---------------------------- *
 *  One glowing stat: icon, count-up number, uppercase mono label.     *
 *  The number's drop-shadow + scale "pop" intensify on each retick.   */

function Equivalent({
  icon,
  target,
  format,
  label,
  unit,
  index,
}: {
  icon: React.ReactNode;
  target: number;
  format: Format;
  label: string;
  unit: string;
  index: number;
}) {
  const { value, pulse } = useCountUp(target, 1400 + index * 90);

  return (
    <motion.div
      className="relative flex flex-col items-center px-3 py-5 text-center"
      initial={{ opacity: 0, y: 16, filter: "blur(8px)" }}
      whileInView={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.7, ease: EASE, delay: 0.12 + index * 0.09 }}
    >
      {/* per-stat ambient halo, brightens on retick */}
      <div
        className="pointer-events-none absolute left-1/2 top-3 h-16 w-16 -translate-x-1/2 rounded-full"
        style={{
          background:
            "radial-gradient(circle, rgba(52,211,153,0.18), transparent 70%)",
          opacity: 0.35 + pulse * 0.5,
          filter: "blur(8px)",
        }}
      />

      <span
        className="relative mb-3"
        style={{
          color: EMERALD_LIGHT,
          filter: `drop-shadow(0 0 ${5 + pulse * 9}px rgba(52,211,153,${
            0.3 + pulse * 0.45
          }))`,
        }}
      >
        {icon}
      </span>

      <motion.span
        className="relative font-mono text-[26px] font-semibold leading-none tabular-nums sm:text-[30px]"
        animate={{ scale: 1 + pulse * 0.07 }}
        transition={{ type: "spring", stiffness: 140, damping: 18 }}
        style={{
          color: EMERALD_PALE,
          textShadow: `0 0 ${12 + pulse * 16}px rgba(110,231,183,${
            0.55 + pulse * 0.35
          })`,
        }}
      >
        {format(value)}
      </motion.span>

      <span className="relative mt-2.5 max-w-[12ch] font-mono text-[9px] uppercase leading-[1.5] tracking-[0.24em] text-emerald-300/55">
        {label}
      </span>
      <span className="relative mt-0.5 font-mono text-[8.5px] uppercase tracking-[0.28em] text-emerald-200/35">
        {unit}
      </span>
    </motion.div>
  );
}

/* --------------------- MEASURED crescendo number ------------------- *
 *  The numbers that were actually run. These count up once on         *
 *  scroll-in.                                                         */

function ScaleStat({
  target,
  format,
  big,
  unit,
  label,
  index,
}: {
  target: number;
  format: Format;
  big: string;
  unit: string;
  label: string;
  index: number;
}) {
  const [run, setRun] = useState(false);
  const { value } = useCountUp(run ? target : 0, 1700);

  return (
    <motion.div
      className="flex flex-col items-center text-center"
      initial={{ opacity: 0, y: 18, filter: "blur(8px)" }}
      whileInView={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      viewport={{ once: true, margin: "-40px" }}
      transition={{ duration: 0.75, ease: EASE, delay: 0.15 + index * 0.12 }}
      onViewportEnter={() => setRun(true)}
    >
      <span className="flex items-baseline gap-1.5">
        <span
          className="font-mono text-[40px] font-bold leading-none tabular-nums sm:text-[52px]"
          style={{
            color: EMERALD_PALE,
            textShadow:
              "0 0 22px rgba(110,231,183,0.5), 0 0 44px rgba(52,211,153,0.18)",
          }}
        >
          {format(value)}
        </span>
        <span
          className="font-mono text-[16px] font-semibold sm:text-[20px]"
          style={{ color: EMERALD_LIGHT }}
        >
          {big}
        </span>
      </span>
      <span className="mt-2 font-mono text-[10px] uppercase tracking-[0.26em] text-emerald-300/60">
        {unit}
      </span>
      <span className="mt-1 max-w-[18ch] font-mono text-[10px] leading-relaxed tracking-[0.06em] text-white/40">
        {label}
      </span>
    </motion.div>
  );
}

/* ------------------------------- main ------------------------------ */

export default function ScaledLatency({ stats }: { stats: Stats | null }) {
  // One row per repo size, scaled off the median sweep. Arithmetic on a
  // measurement, not a second measurement, and every row is labelled as derived.
  const rows = useMemo(() => SCALES.map((files) => derived(files)), []);

  // The re-check is the one cell that is measured rather than derived: it touches
  // only the seams whose code changed, so it does not scale with repo size.
  const incrementalMs = stats?.incremental_ms ?? MEASURED.incrementalBestMs;

  const sweepHeadroom = MEASURED.sweepBudgetMs / MEASURED.sweepMedianMs;
  const incrementalHeadroom =
    MEASURED.incrementalBudgetMs / MEASURED.incrementalMedianMs;

  return (
    <section className="relative w-full overflow-hidden">
      {/* ---- ambient glow blobs behind everything ---- */}
      <div
        aria-hidden
        className="pointer-events-none absolute -left-24 top-0 h-[420px] w-[420px] rounded-full"
        style={{
          background: "rgba(52,211,153,0.09)",
          filter: "blur(120px)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -right-20 bottom-[-80px] h-[460px] w-[460px] rounded-full"
        style={{
          background: "rgba(52,211,153,0.07)",
          filter: "blur(120px)",
        }}
      />

      <div className="relative mx-auto w-full max-w-5xl px-4 py-2">
        {/* ============== EQUIVALENTS CARD ============== */}
        <motion.div
          className="relative overflow-hidden rounded-2xl border border-white/[0.08] bg-gradient-to-b from-[#0e0f0e] to-[#0a0b0a] shadow-[0_30px_80px_-20px_rgba(0,0,0,0.8),inset_0_1px_0_rgba(255,255,255,0.04)] backdrop-blur-sm"
          initial={{ opacity: 0, y: 22, filter: "blur(8px)" }}
          whileInView={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.8, ease: EASE }}
        >
          {/* dotted texture, radially masked so it fades at the edges */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0"
            style={{
              backgroundImage:
                "radial-gradient(rgba(52,211,153,0.05) 1px, transparent 1px)",
              backgroundSize: "34px 34px",
              maskImage:
                "radial-gradient(ellipse 80% 70% at 50% 30%, #000 30%, transparent 100%)",
              WebkitMaskImage:
                "radial-gradient(ellipse 80% 70% at 50% 30%, #000 30%, transparent 100%)",
            }}
          />
          {/* hairline "frame as glow": soft inset ring, masked, not a hard border */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 rounded-2xl"
            style={{
              boxShadow: "inset 0 0 0 1px rgba(110,231,183,0.1)",
              maskImage:
                "radial-gradient(120% 120% at 50% 0%, #000 50%, transparent 100%)",
              WebkitMaskImage:
                "radial-gradient(120% 120% at 50% 0%, #000 50%, transparent 100%)",
            }}
          />

          <div className="relative px-6 pb-7 pt-7 sm:px-9">
            {/* header */}
            <div className="mb-7 flex items-center gap-2.5">
              <motion.span
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: EMERALD, boxShadow: `0 0 8px ${EMERALD}` }}
                animate={{ opacity: [1, 0.3, 1] }}
                transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }}
              />
              <span className="font-mono text-[10px] uppercase tracking-[0.32em] text-emerald-300/55">
                What this costs at repo scale
              </span>
            </div>

            {/* one cell per repo size, plus the re-check that does not scale */}
            <div className="grid grid-cols-2 divide-x divide-y divide-white/[0.05] sm:grid-cols-5 sm:divide-y-0">
              <Equivalent
                index={0}
                icon={<HomeIcon />}
                target={rows[0].sweepSeconds}
                format={fmtSmart}
                label={`${rows[0].files.toLocaleString("en-US")} files`}
                unit="sec, derived"
              />
              <Equivalent
                index={1}
                icon={<CarIcon />}
                target={rows[1].sweepSeconds}
                format={fmtSmart}
                label={`${rows[1].files.toLocaleString("en-US")} files`}
                unit="sec, derived"
              />
              <Equivalent
                index={2}
                icon={<TreeIcon />}
                target={rows[2].sweepSeconds}
                format={fmtSmart}
                label={`${rows[2].files.toLocaleString("en-US")} files`}
                unit="sec, derived"
              />
              <Equivalent
                index={3}
                icon={<DropIcon />}
                target={rows[3].sweepSeconds}
                format={fmtSmart}
                label={`${rows[3].files.toLocaleString("en-US")} files`}
                unit="sec, derived"
              />
              <Equivalent
                index={4}
                icon={<PhoneIcon />}
                target={incrementalMs}
                format={fmtInt}
                label="One edit"
                unit="ms, measured"
              />
            </div>

            <p className="mt-6 text-center font-mono text-[8.5px] uppercase tracking-[0.28em] text-emerald-300/30">
              derived from one measured sweep · linear in source files
            </p>
          </div>
        </motion.div>

        {/* ============== MEASURED: THE CRESCENDO ============== */}
        <motion.div
          className="relative mt-6 overflow-hidden rounded-2xl border border-emerald-400/[0.12] bg-gradient-to-b from-[#0e120f] to-[#080b09] shadow-[0_40px_100px_-24px_rgba(0,0,0,0.85),inset_0_1px_0_rgba(110,231,183,0.06)] backdrop-blur-sm"
          initial={{ opacity: 0, y: 28, filter: "blur(8px)" }}
          whileInView={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          viewport={{ once: true, margin: "-60px" }}
          transition={{ duration: 0.85, ease: EASE, delay: 0.1 }}
        >
          {/* stronger ambient bloom inside the crescendo */}
          <div
            aria-hidden
            className="pointer-events-none absolute left-1/2 top-[-120px] h-[360px] w-[560px] -translate-x-1/2 rounded-full"
            style={{
              background: "rgba(52,211,153,0.11)",
              filter: "blur(120px)",
            }}
          />
          {/* dotted texture */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0"
            style={{
              backgroundImage:
                "radial-gradient(rgba(52,211,153,0.05) 1px, transparent 1px)",
              backgroundSize: "34px 34px",
              maskImage:
                "radial-gradient(ellipse 90% 80% at 50% 40%, #000 20%, transparent 100%)",
              WebkitMaskImage:
                "radial-gradient(ellipse 90% 80% at 50% 40%, #000 20%, transparent 100%)",
            }}
          />
          {/* hairline frame-as-glow */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 rounded-2xl"
            style={{
              boxShadow: "inset 0 0 0 1px rgba(110,231,183,0.12)",
              maskImage:
                "radial-gradient(130% 130% at 50% 0%, #000 45%, transparent 100%)",
              WebkitMaskImage:
                "radial-gradient(130% 130% at 50% 0%, #000 45%, transparent 100%)",
            }}
          />

          <div className="relative px-6 py-10 text-center sm:px-12 sm:py-12">
            {/* eyebrow */}
            <motion.span
              className="inline-block font-mono text-[10px] uppercase tracking-[0.4em] text-emerald-300/60"
              initial={{ opacity: 0, letterSpacing: "0.2em" }}
              whileInView={{ opacity: 1, letterSpacing: "0.4em" }}
              viewport={{ once: true }}
              transition={{ duration: 0.9, ease: EASE }}
            >
              Measured
            </motion.span>

            {/* the framing line: the punchline */}
            <motion.h3
              className="mx-auto mt-4 max-w-2xl text-balance text-[22px] font-semibold leading-[1.25] tracking-tight text-[#e8efe9] sm:text-[30px]"
              initial={{ opacity: 0, y: 14, filter: "blur(8px)" }}
              whileInView={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              viewport={{ once: true, margin: "-40px" }}
              transition={{ duration: 0.8, ease: EASE, delay: 0.1 }}
            >
              A full sweep of 500 source files costs{" "}
              <span
                style={{
                  color: EMERALD_PALE,
                  textShadow: "0 0 18px rgba(110,231,183,0.45)",
                }}
              >
                0.51s
              </span>{" "}
              at the median&nbsp;…
            </motion.h3>

            {/* the two measured numbers, stated outright */}
            <motion.p
              className="mx-auto mt-5 max-w-2xl font-mono text-[11px] leading-relaxed tracking-[0.04em] text-white/45 sm:text-[12px]"
              initial={{ opacity: 0, y: 10 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.7, ease: EASE, delay: 0.25 }}
            >
              Best run{" "}
              <span className="text-emerald-200/70">0.28s</span>, against a 2.0s
              budget. An incremental re-check after one edit is{" "}
              <span className="text-emerald-200/80">83ms</span> best and{" "}
              <span className="text-emerald-200/80">105ms</span> median, against a{" "}
              <span className="text-emerald-200/80">200ms</span> budget.
            </motion.p>

            {/* the headroom and the test count: three giant emerald numbers */}
            <div className="mt-9 grid grid-cols-1 gap-8 sm:grid-cols-3 sm:gap-4">
              <ScaleStat
                index={0}
                target={sweepHeadroom}
                format={fmtSmart}
                big="×"
                unit="sweep headroom"
                label="0.51s median, 2.0s budget"
              />
              <ScaleStat
                index={1}
                target={incrementalHeadroom}
                format={fmtSmart}
                big="×"
                unit="re-check headroom"
                label="105ms median, 200ms budget"
              />
              <ScaleStat
                index={2}
                target={MEASURED.testsPassing}
                format={fmtInt}
                big=""
                unit="tests passing"
                label="zero required dependencies"
              />
            </div>

            {/* footnote: keep it honest */}
            <motion.p
              className="mt-9 font-mono text-[8.5px] uppercase tracking-[0.28em] text-emerald-300/30"
              initial={{ opacity: 0 }}
              whileInView={{ opacity: 1 }}
              viewport={{ once: true }}
              transition={{ duration: 0.8, delay: 0.5 }}
            >
              one machine · 500-file project · 96 tests green
            </motion.p>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
