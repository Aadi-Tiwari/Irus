// The recorded session that the live map replays.
//
// Irus never demos a live agent: slow, nondeterministic, and it will not produce the
// bug on cue. `irus watch` replays an append-only JSONL event log, and on connect the
// server replays the whole log so a refresh rebuilds identical state. This module is
// that log, checked in, so the page reproduces the same session on every visit.
//
// Baseline anchor: the git merge-base of the two active worktrees. Everything already
// in the baseline is context, never a finding.

export const BASELINE_SHA = "acab5370f983";

export type SeamStatus = "broken" | "orphan" | "active" | "healthy";
export type Confidence = "high" | "medium" | "unknown";

// Status colors, validated all-pairs for colorblindness. Healthy carries no color:
// color is scarce and always means "look here".
export const STATUS_COLOR: Record<SeamStatus, string> = {
  broken: "#d03b3b",
  orphan: "#c98500",
  active: "#3987e5",
  healthy: "#898781",
};

export type Node = {
  id: string;
  label: string;
  // Which side of the boundary this node sits on. Producers declare an interface,
  // consumers call it.
  role: "producer" | "consumer" | "config";
  // Which worktree wrote it this session. Identity is a ring or a filter, never the
  // fill. `null` means the node predates the baseline.
  agent: "a" | "b" | null;
  file: string;
  // Blast radius drives node size: how many other nodes depend on this one.
  blastRadius: number;
  // Baseline nodes render small, dim, unlabelled. Pure context.
  layer: "baseline" | "session";
};

export type Edge = {
  source: string;
  target: string;
  // `missing` is the whole product: a connection that should exist and does not,
  // drawn as a dashed red arc with the endpoints pulled apart so the gap is legible.
  kind: "ok" | "missing" | "mismatch";
  layer: "baseline" | "session";
};

export type Finding = {
  id: string;
  seam: string;
  kind: "encoding" | "payload" | "response" | "env" | "orphan";
  confidence: Confidence;
  producer: string;
  consumer: string | null;
  detail: string;
  // Stage 2 verdict. The verdict comes from the application, not from our checker,
  // which is what makes it evidence. `null` means stage 2 has not run for this seam.
  proof: { tier: 1 | 2 | 3; verdict: string } | null;
  // Which side is authoritative. Default: the producer. Written into the receipt so a
  // later round cannot flip it.
  authority: "producer" | "consumer";
};

export const NODES: Node[] = [
  // --- session layer: what the two agents touched this round -------------------
  { id: "srv-checkout", label: "POST /api/checkout", role: "producer", agent: "a", file: "server/routes/checkout.py", blastRadius: 6, layer: "session" },
  { id: "cli-checkout", label: "CheckoutForm", role: "consumer", agent: "b", file: "web/src/CheckoutForm.tsx", blastRadius: 5, layer: "session" },
  { id: "srv-order", label: "GET /api/orders/{id}", role: "producer", agent: "a", file: "server/routes/orders.py", blastRadius: 4, layer: "session" },
  { id: "cli-order", label: "OrderSummary", role: "consumer", agent: "b", file: "web/src/OrderSummary.tsx", blastRadius: 3, layer: "session" },
  { id: "srv-refund", label: "POST /api/refund", role: "producer", agent: "a", file: "server/routes/refund.py", blastRadius: 1, layer: "session" },
  { id: "cfg-webhook", label: "STRIPE_WEBHOOK_SECRET", role: "config", agent: "a", file: "server/config.py", blastRadius: 2, layer: "session" },

  // --- baseline layer: everything that predates the merge-base -----------------
  { id: "srv-health", label: "GET /api/health", role: "producer", agent: null, file: "server/routes/health.py", blastRadius: 1, layer: "baseline" },
  { id: "cli-health", label: "HealthBadge", role: "consumer", agent: null, file: "web/src/HealthBadge.tsx", blastRadius: 1, layer: "baseline" },
  { id: "srv-session", label: "POST /api/session", role: "producer", agent: null, file: "server/routes/session.py", blastRadius: 3, layer: "baseline" },
  { id: "cli-session", label: "useSession", role: "consumer", agent: null, file: "web/src/useSession.ts", blastRadius: 3, layer: "baseline" },
  { id: "srv-catalog", label: "GET /api/catalog", role: "producer", agent: null, file: "server/routes/catalog.py", blastRadius: 2, layer: "baseline" },
  { id: "cli-catalog", label: "CatalogGrid", role: "consumer", agent: null, file: "web/src/CatalogGrid.tsx", blastRadius: 2, layer: "baseline" },
  { id: "srv-user", label: "GET /api/me", role: "producer", agent: null, file: "server/routes/user.py", blastRadius: 2, layer: "baseline" },
  { id: "cli-user", label: "AccountMenu", role: "consumer", agent: null, file: "web/src/AccountMenu.tsx", blastRadius: 2, layer: "baseline" },
  { id: "cfg-db", label: "DATABASE_URL", role: "config", agent: null, file: "server/config.py", blastRadius: 4, layer: "baseline" },
];

export const EDGES: Edge[] = [
  { source: "cli-checkout", target: "srv-checkout", kind: "mismatch", layer: "session" },
  { source: "cli-order", target: "srv-order", kind: "mismatch", layer: "session" },
  { source: "cli-checkout", target: "srv-refund", kind: "missing", layer: "session" },
  { source: "srv-checkout", target: "cfg-webhook", kind: "missing", layer: "session" },
  { source: "cli-health", target: "srv-health", kind: "ok", layer: "baseline" },
  { source: "cli-session", target: "srv-session", kind: "ok", layer: "baseline" },
  { source: "cli-catalog", target: "srv-catalog", kind: "ok", layer: "baseline" },
  { source: "cli-user", target: "srv-user", kind: "ok", layer: "baseline" },
  { source: "srv-session", target: "cfg-db", kind: "ok", layer: "baseline" },
  { source: "srv-catalog", target: "cfg-db", kind: "ok", layer: "baseline" },
];

// Five findings introduced this session, three high confidence. One pre-existing
// finding sits in the baseline and is therefore invisible.
export const FINDINGS: Finding[] = [
  {
    id: "f-1a2b3c",
    seam: "POST /api/checkout",
    kind: "encoding",
    confidence: "high",
    producer: "server/routes/checkout.py:18",
    consumer: "web/src/CheckoutForm.tsx:44",
    detail: "client sends multipart, server expects json",
    proof: { tier: 1, verdict: "request rejected before send: content-type mismatch" },
    authority: "producer",
  },
  {
    id: "f-4d5e6f",
    seam: "POST /api/checkout",
    kind: "payload",
    confidence: "high",
    producer: "server/routes/checkout.py:18",
    consumer: "web/src/CheckoutForm.tsx:44",
    detail: "server requires `amount` (int); server requires `email` (str)",
    proof: { tier: 2, verdict: "422 Unprocessable Entity from the app's own test client" },
    authority: "producer",
  },
  {
    id: "f-7a8b9c",
    seam: "GET /api/orders/{id}",
    kind: "response",
    confidence: "high",
    producer: "server/routes/orders.py:31",
    consumer: "web/src/OrderSummary.tsx:12",
    detail: "client reads `customer.name`, handler returns `customer_name`",
    proof: { tier: 3, verdict: "200 OK, body has no `customer` key" },
    authority: "producer",
  },
  {
    id: "f-2c3d4e",
    seam: "STRIPE_WEBHOOK_SECRET",
    kind: "env",
    confidence: "medium",
    producer: "server/config.py:9",
    consumer: null,
    detail: "read at import time, never set in compose, .env.example or CI",
    proof: null,
    authority: "producer",
  },
  {
    id: "f-5f6a7b",
    seam: "POST /api/refund",
    kind: "orphan",
    confidence: "medium",
    producer: "server/routes/refund.py:22",
    consumer: null,
    detail: "route mounted, no client in either worktree calls it",
    proof: null,
    authority: "producer",
  },
];

export type Stats = {
  seams_checked: number;
  findings_session: number;
  findings_high: number;
  baseline_suppressed: number;
  proofs_run: number;
  rounds_accepted: number;
  sweep_ms: number;
  incremental_ms: number;
};

// The state the log replays to. Every number here is either counted off the fixture
// above or measured on this machine; nothing is projected.
export const FINAL_STATS: Stats = {
  seams_checked: NODES.length,
  findings_session: FINDINGS.length,
  findings_high: FINDINGS.filter((f) => f.confidence === "high").length,
  baseline_suppressed: 1,
  proofs_run: FINDINGS.filter((f) => f.proof !== null).length,
  rounds_accepted: 2,
  sweep_ms: 280,
  incremental_ms: 83,
};

export type LogEvent = {
  t: number; // ms since the sweep started
  type: "seam" | "finding" | "proof" | "round";
  id: string;
  text: string;
};

// The append-only log, in the order `irus watch` streams it over server-sent events.
export const LOG: LogEvent[] = [
  { t: 0, type: "round", id: "baseline", text: `baseline ${BASELINE_SHA} loaded, 1 pre-existing finding suppressed` },
  { t: 40, type: "seam", id: "srv-checkout", text: "parsed server/routes/checkout.py" },
  { t: 70, type: "seam", id: "cli-checkout", text: "parsed web/src/CheckoutForm.tsx" },
  { t: 110, type: "finding", id: "f-1a2b3c", text: "POST /api/checkout: encoding matches FAIL" },
  { t: 150, type: "finding", id: "f-4d5e6f", text: "POST /api/checkout: payload shape matches FAIL" },
  { t: 190, type: "seam", id: "srv-order", text: "parsed server/routes/orders.py" },
  { t: 215, type: "seam", id: "cli-order", text: "parsed web/src/OrderSummary.tsx" },
  { t: 240, type: "finding", id: "f-7a8b9c", text: "GET /api/orders/{id}: response shape matches FAIL" },
  { t: 258, type: "seam", id: "cfg-webhook", text: "parsed server/config.py" },
  { t: 262, type: "finding", id: "f-2c3d4e", text: "STRIPE_WEBHOOK_SECRET: set somewhere FAIL" },
  { t: 275, type: "seam", id: "srv-refund", text: "parsed server/routes/refund.py" },
  { t: 280, type: "finding", id: "f-5f6a7b", text: "POST /api/refund: has a caller FAIL" },
  { t: 284, type: "round", id: "sweep", text: "sweep complete in 280ms, 5 findings (3 high)" },
  { t: 300, type: "proof", id: "f-1a2b3c", text: "tier 1: request rejected before send" },
  { t: 340, type: "proof", id: "f-4d5e6f", text: "tier 2: 422 Unprocessable Entity" },
  { t: 420, type: "proof", id: "f-7a8b9c", text: "tier 3: 200 OK, body has no `customer` key" },
  { t: 470, type: "round", id: "round-1", text: "round 1 accepted: 5 failing seams to 2" },
  { t: 553, type: "round", id: "round-2", text: "round 2 accepted: 2 failing seams to 0" },
];
