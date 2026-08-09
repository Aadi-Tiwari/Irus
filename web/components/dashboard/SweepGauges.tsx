"use client";

import { motion, useAnimationFrame } from "motion/react";
import { useMemo, useRef, useState } from "react";

import type { Stats } from "@/lib/useSession";

/**
 * SweepGauges: the dashboard hero. Four big radial gauges ("wheels that fill
 * in") showing the four live numbers of a sweep. The FINDINGS ring is the
 * headline, largest and centered; seams checked, high confidence and proofs run
 * flank it.
 *
 * Each gauge sweeps an emerald arc toward the next round-number milestone, with a
 * count-up number in the center. On mount everything counts up from 0 and the arc
 * sweeps in (staggered, ease [0.22,1,0.36,1]). When a value bumps up live (the
 * replayed log advancing), that gauge re-tweens and flashes its glow brighter for
 * ~600ms.
 *
 * Aesthetic: near-black #0a0a0a, emerald-only accent at low opacity, mono numbers,
 * "frame as glow" hairlines, ambient blurred blobs, dotted masked texture.
 * No chart/icon libraries: everything is inline SVG plus a manual rAF tween.
 */

const EMERALD = "#34d399";
const EMERALD_LIGHT = "#6ee7b7";
const EMERALD_PALE = "#a7f3d0";

const EASE = [0.22, 1, 0.36, 1] as const;

type GaugeSpec = {
  key: string;
  label: string;
  unit: string;
  value: number;
  /** index used to stagger the intro sweep */
  order: number;
  hero?: boolean;
};

/* ── number helpers ─────────────────────────────────────────────────────── */

/** Commas for readability: 8169600 → "8,169,600". */
function withCommas(n: number, decimals = 0): string {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/**
 * Gentle abbreviation for the ring center so a large count still fits and
 * keeps a "precision feel": 8_169_600 → "8.17M", 14_300 → "14.3K".
 * Below 100k we keep full commas (the numbers are still legible there).
 */
function abbreviate(n: number, decimals: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 100_000) return `${(n / 1000).toFixed(1)}K`;
  return withCommas(n, decimals);
}

/**
 * The "next nice round number above the current value." This is what the arc
 * sweeps toward, so progress = value / milestone. We snap up to 1, 2, 5 × 10^k,
 * which gives human-feeling targets (10M, 20M, 50M…) instead of arbitrary ones.
 *
 * Edge: a value sitting exactly on a milestone would read as a full ring with no
 * headroom, so we bump to the *next* tier, so the wheel always shows "more to go."
 */
function nextMilestone(value: number): number {
  if (value <= 0) return 1;
  const exp = Math.floor(Math.log10(value));
  const base = Math.pow(10, exp); // largest power of 10 ≤ value
  for (const m of [1, 2, 5, 10]) {
    const candidate = m * base;
    if (candidate > value) return candidate;
  }
  return 10 * base;
}

/* ── the tween engine ───────────────────────────────────────────────────────
 * Rather than a spring per gauge, we drive all four with ONE useAnimationFrame
 * loop and a small per-gauge tween record. Each gauge interpolates from a "from"
 * value to a "to" value over a duration with our shared ease. This keeps the
 * intro stagger and the realtime "tick" identical in feel, and avoids spawning
 * four independent animation controllers that can drift out of sync.
 * ──────────────────────────────────────────────────────────────────────────── */

type Tween = {
  from: number; // value at tween start
  to: number; // target value
  start: number; // performance.now() when it began
  duration: number; // ms
};

function easeCubic(t: number): number {
  // Matches the spirit of [0.22,1,0.36,1]: a fast-out, soft-settle curve.
  return 1 - Math.pow(1 - t, 3);
}

function sampleTween(tw: Tween, now: number): { value: number; done: boolean } {
  const raw = (now - tw.start) / tw.duration;
  if (raw >= 1) return { value: tw.to, done: true };
  if (raw <= 0) return { value: tw.from, done: false };
  return { value: tw.from + (tw.to - tw.from) * easeCubic(raw), done: false };
}

/* ── one radial gauge ───────────────────────────────────────────────────── */

function Gauge({
  spec,
  displayValue,
  progress,
  flash,
}: {
  spec: GaugeSpec;
  displayValue: number;
  progress: number; // 0..1 sweep toward milestone
  flash: number; // 0..1 brightness boost on a tick
}) {
  // Hero ring is physically larger so the eye lands there first.
  const size = spec.hero ? 232 : 168;
  const stroke = spec.hero ? 11 : 8;
  const r = (size - stroke) / 2 - 6;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  const dashOffset = circumference * (1 - Math.max(0, Math.min(1, progress)));

  // Every ring counts whole things, so no fractional digits on any of them.
  const center = abbreviate(displayValue, 0);

  const milestone = useMemo(() => nextMilestone(spec.value), [spec.value]);

  // Flash intensifies the arc glow and lightens its colour for the "tick."
  const arcGlow = (spec.hero ? 7 : 5) + flash * 12;
  const arcColor = flash > 0.04 ? EMERALD_LIGHT : EMERALD;
  const numShadow = `0 0 ${10 + flash * 16}px rgba(110,231,183,${0.5 + flash * 0.4})`;

  // Dimmed treatment when the sweep has not reported yet (stats === null → 0).
  const empty = spec.value <= 0;

  return (
    <div
      className="relative flex flex-col items-center"
      style={{ opacity: empty ? 0.55 : 1 }}
    >
      {/* per-gauge ambient bloom behind the ring */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/2 -z-10 -translate-x-1/2 -translate-y-1/2 rounded-full blur-[60px]"
        style={{
          width: size * 0.9,
          height: size * 0.9,
          background: `radial-gradient(circle, rgba(52,211,153,${
            0.05 + flash * 0.12
          }), transparent 70%)`,
        }}
      />

      <div className="relative" style={{ width: size, height: size }}>
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          className="block"
        >
          <defs>
            <linearGradient id={`arc-${spec.key}`} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor={EMERALD} />
              <stop offset="55%" stopColor={EMERALD_LIGHT} />
              <stop offset="100%" stopColor={EMERALD_PALE} />
            </linearGradient>
            <filter id={`glow-${spec.key}`} x="-60%" y="-60%" width="220%" height="220%">
              <feGaussianBlur stdDeviation={arcGlow} result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* faint full-circle track */}
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke="rgba(255,255,255,0.06)"
            strokeWidth={stroke}
          />

          {/* glowing emerald progress arc, rotated so 0% starts at top (12 o'clock) */}
          <g transform={`rotate(-90 ${cx} ${cy})`}>
            <circle
              cx={cx}
              cy={cy}
              r={r}
              fill="none"
              stroke={`url(#arc-${spec.key})`}
              strokeWidth={stroke}
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={dashOffset}
              filter={`url(#glow-${spec.key})`}
              style={{ color: arcColor }}
            />
            {/* a brighter cap dot riding the arc head when flashing, for the "tick" */}
            {flash > 0.04 && progress > 0.001 && progress < 0.999 && (
              <circle
                cx={cx + r * Math.cos(2 * Math.PI * progress)}
                cy={cy + r * Math.sin(2 * Math.PI * progress)}
                r={stroke * 0.5}
                fill="#ecfdf5"
                opacity={flash}
              />
            )}
          </g>
        </svg>

        {/* center stack: big glowing number + unit + label */}
        <div className="absolute inset-0 flex flex-col items-center justify-center px-2 text-center">
          <span
            className={`font-mono tabular-nums font-semibold leading-none ${
              spec.hero ? "text-[34px]" : "text-[22px]"
            }`}
            style={{ color: EMERALD_PALE, textShadow: numShadow }}
          >
            {center}
          </span>
          {spec.unit && (
            <span
              className={`mt-1 font-mono uppercase tracking-[0.2em] text-emerald-200/55 ${
                spec.hero ? "text-[11px]" : "text-[9px]"
              }`}
            >
              {spec.unit}
            </span>
          )}
          <span
            className={`mt-1.5 font-mono uppercase text-emerald-300/55 ${
              spec.hero
                ? "text-[10px] tracking-[0.32em]"
                : "text-[8.5px] tracking-[0.24em]"
            }`}
          >
            {spec.label}
          </span>
        </div>
      </div>

      {/* milestone caption under the ring, showing what the wheel is filling toward */}
      <div className="mt-3 font-mono text-[9px] uppercase tracking-[0.22em] text-white/30">
        {empty ? "awaiting sweep" : `→ ${abbreviate(milestone, 0)} ${spec.unit}`.trim()}
      </div>
    </div>
  );
}

/* ── the panel ──────────────────────────────────────────────────────────── */

export default function SweepGauges({ stats }: { stats: Stats | null }) {
  // The four live numbers of a sweep. Every one is counted off the session, and
  // nothing already in the baseline is counted at all.
  const specs: GaugeSpec[] = useMemo(() => {
    const s = stats;
    return [
      {
        key: "findings",
        label: "This session",
        unit: "findings",
        value: s ? s.findings_session : 0,
        order: 1, // hero sweeps in second so the eye catches the flanks first, then lands center
        hero: true,
      },
      {
        key: "seams",
        label: "Checked",
        unit: "seams",
        value: s ? s.seams_checked : 0,
        order: 0,
      },
      {
        key: "high",
        label: "Confidence",
        unit: "high",
        value: s ? s.findings_high : 0,
        order: 2,
      },
      {
        key: "proofs",
        label: "Stage 2 run",
        unit: "proofs",
        value: s ? s.proofs_run : 0,
        order: 3,
      },
    ];
  }, [stats]);

  // Live display values (what's painted), tweened toward each spec.value.
  const [display, setDisplay] = useState<number[]>(() => specs.map(() => 0));
  const [flashes, setFlashes] = useState<number[]>(() => specs.map(() => 0));

  // Per-gauge tween records + the previous target we last animated to. We keep
  // these in refs (not state) so the rAF loop reads the latest without forcing a
  // re-render on every frame just to mutate bookkeeping.
  const tweensRef = useRef<Tween[]>(specs.map(() => null as unknown as Tween));
  const prevTargetRef = useRef<number[]>(specs.map(() => 0));
  const flashUntilRef = useRef<number[]>(specs.map(() => 0));
  const initedRef = useRef(false);

  // Snapshot the current targets each render so the loop closure stays fresh.
  const targetsRef = useRef<number[]>(specs.map((g) => g.value));
  targetsRef.current = specs.map((g) => g.value);

  useAnimationFrame((now) => {
    const targets = targetsRef.current;

    // First frame: kick off the staggered intro sweep from 0 → target.
    if (!initedRef.current) {
      initedRef.current = true;
      tweensRef.current = specs.map((g, i) => ({
        from: 0,
        to: targets[i],
        start: now + g.order * 130, // stagger by source order
        duration: 1200,
      }));
      prevTargetRef.current = [...targets];
    }

    let changed = false;
    const nextDisplay = [...display];
    const nextFlash = [...flashes];

    for (let i = 0; i < specs.length; i++) {
      // Detect a realtime bump: target moved (almost always upward) since last frame.
      if (Math.abs(targets[i] - prevTargetRef.current[i]) > 1e-6) {
        const cur = tweensRef.current[i]
          ? sampleTween(tweensRef.current[i], now).value
          : display[i];
        tweensRef.current[i] = {
          from: cur, // re-tween from wherever we are now, no snap
          to: targets[i],
          start: now,
          duration: 900,
        };
        // Only flash on an *increase*, the satisfying "tick."
        if (targets[i] > prevTargetRef.current[i]) {
          flashUntilRef.current[i] = now + 600;
        }
        prevTargetRef.current[i] = targets[i];
      }

      // Advance the tween.
      const tw = tweensRef.current[i];
      if (tw) {
        const { value } = sampleTween(tw, now);
        if (Math.abs(value - nextDisplay[i]) > 1e-3) {
          nextDisplay[i] = value;
          changed = true;
        }
      }

      // Advance the flash envelope (0..1, decaying over 600ms).
      const f =
        flashUntilRef.current[i] > now
          ? (flashUntilRef.current[i] - now) / 600
          : 0;
      if (Math.abs(f - nextFlash[i]) > 1e-3) {
        nextFlash[i] = f;
        changed = true;
      }
    }

    if (changed) {
      setDisplay(nextDisplay);
      setFlashes(nextFlash);
    }
  });

  const rounds = stats?.rounds_accepted ?? 0;

  // Render order: seams, FINDINGS (hero, center), high, proofs, so on wide screens
  // the hero sits in the middle of the row; on mobile they wrap gracefully.
  const ordered = [specs[1], specs[0], specs[2], specs[3]];
  const indexOf = (key: string) => specs.findIndex((g) => g.key === key);

  return (
    <div className="relative isolate w-full overflow-hidden rounded-2xl border border-white/[0.08] bg-gradient-to-b from-[#0e0f0e] to-[#0a0b0a] px-6 py-10 shadow-[0_30px_80px_-20px_rgba(0,0,0,0.8),inset_0_1px_0_rgba(255,255,255,0.04)] backdrop-blur-sm sm:px-10 sm:py-12">
      {/* ambient blobs */}
      <motion.div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/2 -z-10 h-[40rem] w-[52rem] -translate-x-1/2 -translate-y-1/2 rounded-full blur-[120px]"
        animate={{ opacity: [0.5, 0.78, 0.5], scale: [1, 1.05, 1] }}
        transition={{ duration: 16, repeat: Infinity, ease: "easeInOut" }}
        style={{
          background: "radial-gradient(circle, rgba(52,211,153,0.1), transparent 64%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute right-0 top-0 -z-10 h-72 w-72 rounded-full blur-[120px]"
        style={{
          background: "radial-gradient(circle, rgba(52,211,153,0.06), transparent 70%)",
        }}
      />

      {/* dotted texture, masked to an ellipse so it fades at the edges */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 opacity-[0.6]"
        style={{
          backgroundImage:
            "radial-gradient(rgba(52,211,153,0.05) 1px, transparent 1px)",
          backgroundSize: "34px 34px",
          maskImage:
            "radial-gradient(ellipse 80% 72% at 50% 50%, black, transparent 82%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 80% 72% at 50% 50%, black, transparent 82%)",
        }}
      />

      {/* hairline "frame as glow": a soft inset ring with a radial mask, not a hard border */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 rounded-2xl"
        style={{
          boxShadow: "inset 0 0 0 1px rgba(110,231,183,0.1)",
          maskImage:
            "radial-gradient(120% 120% at 50% 0%, #000 55%, transparent 100%)",
          WebkitMaskImage:
            "radial-gradient(120% 120% at 50% 0%, #000 55%, transparent 100%)",
        }}
      />

      {/* header */}
      <motion.div
        className="relative mb-9 flex items-center justify-between"
        initial={{ opacity: 0, y: 14, filter: "blur(8px)" }}
        animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
        transition={{ duration: 0.8, ease: EASE }}
      >
        <div className="flex items-center gap-2.5">
          <motion.span
            className="h-1.5 w-1.5 rounded-full"
            style={{ background: EMERALD, boxShadow: "0 0 8px rgba(52,211,153,0.8)" }}
            animate={{ opacity: [1, 0.3, 1] }}
            transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }}
          />
          <span className="font-mono text-[9px] uppercase tracking-[0.32em] text-emerald-300/55">
            Live seam sweep
          </span>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-emerald-200/70 tabular-nums">
          {withCommas(rounds)}{" "}
          <span className="text-emerald-300/45">rounds accepted</span>
        </span>
      </motion.div>

      {/* the four gauges, wrapping on mobile, hero centered on wide rows */}
      <div className="relative flex flex-wrap items-start justify-center gap-x-10 gap-y-12 sm:gap-x-14">
        {ordered.map((g) => {
          const i = indexOf(g.key);
          const target = g.value;
          const ms = nextMilestone(target);
          const progress = target <= 0 ? 0 : Math.min(1, display[i] / ms);
          return (
            <motion.div
              key={g.key}
              initial={{ opacity: 0, y: 20, filter: "blur(8px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              transition={{ duration: 0.9, ease: EASE, delay: 0.1 + g.order * 0.1 }}
            >
              <Gauge
                spec={g}
                displayValue={display[i]}
                progress={progress}
                flash={flashes[i]}
              />
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
