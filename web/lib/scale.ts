// What the measured latency means at sizes people actually work at.
//
// Two numbers were measured on one machine against a synthetic 500-file project: a
// full sweep at 0.28s best and 0.51s median against a 2.0s budget, and an incremental
// re-check after one edit at 83ms best and 105ms median against a 200ms budget. The
// sweep is linear in source files, so scaling by file count is arithmetic on a
// measurement rather than a second measurement. Everything below is derived from those
// two numbers and labelled as derived wherever it is shown.

export const MEASURED = {
  files: 500,
  sweepBestMs: 280,
  sweepMedianMs: 510,
  incrementalBestMs: 83,
  incrementalMedianMs: 105,
  sweepBudgetMs: 2000,
  incrementalBudgetMs: 200,
  testsPassing: 96,
  requiredDependencies: 0,
} as const;

export function derived(files: number) {
  const factor = files / MEASURED.files;
  const sweepMs = MEASURED.sweepMedianMs * factor;
  return {
    files,
    sweepMs,
    sweepSeconds: sweepMs / 1000,
    // How many times a full sweep fits inside one minute of wall clock.
    sweepsPerMinute: 60000 / sweepMs,
    // An incremental re-check touches only the seams whose code changed, so it does
    // not scale with repo size.
    incrementalMs: MEASURED.incrementalMedianMs,
    // Headroom against the budget the sweep was written to hold.
    budgetHeadroom: MEASURED.sweepBudgetMs / sweepMs,
  };
}

export const SCALES = [500, 2_000, 10_000, 50_000];

// Status accents, matching the live map. Used by the graph and the check chips so one
// color means one thing everywhere on the site.
export const STATUS_ACCENT: Record<string, string> = {
  broken: "#d03b3b",
  orphan: "#c98500",
  active: "#3987e5",
  healthy: "#898781",
  pass: "#34d399",
  unknown: "#94a3b8",
};

// Seam kind to accent, for chips and legends.
export const KIND_COLOR: Record<string, string> = {
  encoding: "#d03b3b",
  payload: "#f472b6",
  response: "#a78bfa",
  env: "#c98500",
  orphan: "#fbbf24",
  route: "#22d3ee",
  other: "#94a3b8",
};
