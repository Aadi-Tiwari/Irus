"use client";

import { motion, useAnimationFrame } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  STATUS_COLOR,
  type Edge as SeamEdge,
  type Node as SeamNode,
  type SeamStatus,
} from "@/lib/session-fixture";

/**
 * SeamMap: the live map that `irus watch` draws.
 *
 * Two layers on one canvas. The baseline layer (everything that predates the
 * merge-base) renders small, dim, thin-edged and unlabelled: pure context. The
 * session layer renders full size, with color and labels, on top. Node size is
 * blast radius. Color is scarce and always means "look here", so healthy nodes
 * carry no color and only broken seams, orphans and the node being checked
 * right now are tinted. Identity, meaning which worktree wrote a node, is a
 * ring around it and never the fill.
 *
 * The single most important mark is absence: an edge with kind `missing` is a
 * connection that should exist and does not, drawn as a dashed red arc with the
 * endpoints pulled apart so the gap is legible.
 *
 * Everything is drawn on a single <canvas> (no graph libs). Layout is seeded
 * from the node id through an LCG, so the codebase looks the same every session
 * and spatial memory works, and SSR and CSR agree, because we never call Math.random
 * during render. Sits transparently over the page's near-black background.
 */

// ---- props -----------------------------------------------------------------

type Pulse = { id: string; nonce: number } | null;

interface SeamMapProps {
  nodes: SeamNode[];
  edges: SeamEdge[];
  pulse?: Pulse;
}

// ---- palette + constants ---------------------------------------------------

const EMERALD_PALE = "167, 243, 208"; // #a7f3d0, pale

const EASE = [0.22, 1, 0.36, 1] as const;

// STATUS_COLOR as rgb triples, so the canvas can vary alpha per node.
function hexTriple(hex: string) {
  const n = parseInt(hex.slice(1), 16);
  return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
}
const STATUS_RGB: Record<SeamStatus, string> = {
  broken: hexTriple(STATUS_COLOR.broken),
  orphan: hexTriple(STATUS_COLOR.orphan),
  active: hexTriple(STATUS_COLOR.active),
  healthy: hexTriple(STATUS_COLOR.healthy),
};

// Same LCG used elsewhere in the app, deterministic so SSR/CSR layout match.
function makeRand(seed: number) {
  let s = seed >>> 0 || 1;
  return () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
}

// Cheap stable hash so an id always maps to the same seed/angle.
function hashStr(str: string) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

// A node lives in a unit-ish space centered on (0,0); we scale to pixels at
// draw time so the layout is resolution-independent and resizes for free.
type Node = {
  id: string;
  label: string;
  // the connected group this node belongs to, keyed by its lowest member id
  cluster: string;
  agent: "a" | "b" | null;
  layer: "baseline" | "session";
  status: SeamStatus;
  weight: number; // blast radius, normalized 0..1
  // labels sit on the outward side of the lobe so neighbours do not overlap
  labelAbove: boolean;
  // cluster center (the lobe this node belongs to), in unit space
  cx: number;
  cy: number;
  // resting offset from the cluster center
  ox: number;
  oy: number;
  // per-node wobble parameters (phase + speed + amplitude)
  wphX: number;
  wphY: number;
  wspX: number;
  wspY: number;
  wampX: number;
  wampY: number;
  // live position (unit space), eased by the sim each frame
  x: number;
  y: number;
  // transient flash energy 0..1 driven by `pulse`
  flash: number;
  radiusBase: number; // px-ish base radius before blast-radius scaling
};

// A traveling particle fired on a pulse: lerps from -> to along a thread.
type Particle = {
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  t: number; // 0..1 progress
  speed: number; // progress per second
  hue: string; // rgb triple
};

// An expanding ring emitted at a node on pulse.
type Ring = {
  x: number;
  y: number;
  t: number; // 0..1 life
  speed: number;
};

// A declared connection between two nodes, resolved to node indices.
type Link = { a: number; b: number; kind: SeamEdge["kind"]; layer: SeamEdge["layer"] };

export default function SeamMap({ nodes: seamNodes, edges: seamEdges, pulse = null }: SeamMapProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // Canvas pixel size in CSS px (not device px). Kept in a ref so the RAF loop
  // reads the freshest value without re-subscribing.
  const sizeRef = useRef({ w: 0, h: 0, dpr: 1 });

  // -- derive per-node status + size from the declared edges ----------------
  // Status comes off the edges rather than a field, so the map can never
  // disagree with the seams it draws. Blast radius drives size.
  const { nodes, links, clusterAngles } = useMemo(
    () => buildLayout(seamNodes, seamEdges),
    [seamNodes, seamEdges],
  );

  // Keep a live, mutable copy of nodes for the sim (we mutate x/y/flash every
  // frame; React state would thrash). We rebuild it whenever the layout memo
  // changes identity.
  const nodesRef = useRef<Node[]>(nodes);
  const linksRef = useRef<Link[]>(links);
  useEffect(() => {
    nodesRef.current = nodes;
    linksRef.current = links;
  }, [nodes, links]);

  const particlesRef = useRef<Particle[]>([]);
  const ringsRef = useRef<Ring[]>([]);

  // index from node id -> node index, for O(1) pulse lookup
  const idIndex = useMemo(() => {
    const m = new Map<string, number>();
    nodes.forEach((n, i) => m.set(n.id, i));
    return m;
  }, [nodes]);

  // small mono caption state: total nodes + a "live" heartbeat dot
  const [, force] = useState(0);

  // -- respond to a pulse: flash node + launch ring + particle --------------
  const lastNonce = useRef<number | null>(null);
  useEffect(() => {
    if (!pulse) return;
    if (lastNonce.current === pulse.nonce) return;
    lastNonce.current = pulse.nonce;

    // The log also carries finding and round events, whose ids are not nodes.
    // Those simply do not land on the map.
    const idx = idIndex.get(pulse.id);
    if (idx == null) return;
    const target = nodesRef.current[idx];
    if (!target) return;

    target.flash = 1;
    ringsRef.current.push({ x: target.x, y: target.y, t: 0, speed: 0.9 });

    // Pick an origin for the traveling particle: a random node from the same
    // cluster if one exists, else the graph center. The rand here is seeded by
    // the nonce so it stays deterministic per pulse (and never in render).
    const rand = makeRand(hashStr(pulse.id) ^ (pulse.nonce * 2654435761));
    const sameCluster = nodesRef.current.filter(
      (n) => n.cluster === target.cluster && n.id !== target.id,
    );
    let fromX = 0;
    let fromY = 0;
    if (sameCluster.length > 0) {
      const origin = sameCluster[Math.floor(rand() * sameCluster.length)];
      fromX = origin.x;
      fromY = origin.y;
    }
    particlesRef.current.push({
      fromX,
      fromY,
      toX: target.x,
      toY: target.y,
      t: 0,
      speed: 1.6,
      hue: STATUS_RGB.active,
    });
  }, [pulse, idIndex]);

  // -- size + DPR handling via ResizeObserver -------------------------------
  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;

    const apply = () => {
      const rect = wrap.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
      const w = Math.max(1, Math.round(rect.width));
      const h = Math.max(1, Math.round(rect.height));
      sizeRef.current = { w, h, dpr };
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
    };

    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(wrap);
    return () => ro.disconnect();
  }, []);

  // -- the animation loop ---------------------------------------------------
  // We mutate node positions toward (clusterCenter + wobble), draw edges, glow
  // nodes (radius/brightness ∝ blast radius), then particles and rings. A clock
  // accumulator gives time-based motion that's frame-rate independent.
  const clockRef = useRef(0);
  const lastTsRef = useRef<number | null>(null);

  useAnimationFrame((t) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const { w, h, dpr } = sizeRef.current;
    if (w === 0 || h === 0) return;

    // delta time in seconds, clamped so a tab-switch doesn't teleport things
    const last = lastTsRef.current;
    const dt = last == null ? 0.016 : Math.min(0.05, (t - last) / 1000);
    lastTsRef.current = t;
    clockRef.current += dt;
    const now = clockRef.current;

    const nodeArr = nodesRef.current;
    const linkArr = linksRef.current;

    // The unit space is roughly [-1, 1]; map it into the canvas with a margin
    // so glow halos never clip at the edges. Scale is the smaller half-extent.
    const cxPx = w / 2;
    const cyPx = h / 2;
    const scale = Math.min(w, h) * 0.46;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    // ---- advance the sim: drift + breathe -------------------------------
    // Each node eases toward (clusterCenter + slow sine wobble). The easing is
    // a critically-damped-ish lerp; the wobble supplies the "alive" motion and
    // the pull toward the cluster center supplies the "breathing."
    const breathe = 1 + Math.sin(now * 0.35) * 0.045; // whole-web inhale/exhale
    for (let i = 0; i < nodeArr.length; i++) {
      const n = nodeArr[i];
      const targetX =
        (n.cx + n.ox + Math.sin(now * n.wspX + n.wphX) * n.wampX) * breathe;
      const targetY =
        (n.cy + n.oy + Math.cos(now * n.wspY + n.wphY) * n.wampY) * breathe;
      // ease (the 6 controls stiffness; higher = snappier)
      n.x += (targetX - n.x) * Math.min(1, dt * 1.8);
      n.y += (targetY - n.y) * Math.min(1, dt * 1.8);
      // decay flash energy
      if (n.flash > 0) n.flash = Math.max(0, n.flash - dt * 1.6);
    }

    // helper: unit-space -> device-css px. Positions spread anisotropically so a
    // handful of seams fills a wide panel instead of knotting in the middle;
    // `scale` still drives radii and thresholds, so marks stay round.
    const spreadX = Math.min(w * 0.44, scale * 2.4);
    const spreadY = h * 0.44;
    const px = (ux: number) => cxPx + ux * spreadX;
    const py = (uy: number) => cyPx + uy * spreadY;

    // ---- agreeing seams: faint threads, thinner still on the baseline ---
    for (let e = 0; e < linkArr.length; e++) {
      const link = linkArr[e];
      if (link.kind !== "ok") continue;
      const a = nodeArr[link.a];
      const b = nodeArr[link.b];
      const ax = px(a.x);
      const ay = py(a.y);
      const bx = px(b.x);
      const by = py(b.y);
      const dxp = ax - bx;
      const dyp = ay - by;
      const dist = Math.hypot(dxp, dyp);
      // soften the thread as the two ends drift apart, but never below the
      // floor: these are declared connections, and dropping one would be a
      // claim that it does not exist
      const fade = Math.max(0.25, 1 - dist / (scale * 0.42));
      const dim = link.layer === "baseline" ? 0.6 : 1;
      const alpha = (0.03 + fade * 0.11 + (a.flash + b.flash) * 0.06) * dim;
      ctx.lineWidth = link.layer === "baseline" ? 0.6 : 1;
      ctx.strokeStyle = `rgba(${STATUS_RGB.healthy}, ${alpha})`;
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.lineTo(bx, by);
      ctx.stroke();
    }

    // ---- disagreeing seams: both sides exist, they do not agree ---------
    for (let e = 0; e < linkArr.length; e++) {
      const link = linkArr[e];
      if (link.kind !== "mismatch") continue;
      const a = nodeArr[link.a];
      const b = nodeArr[link.b];
      ctx.lineWidth = 1.4;
      ctx.strokeStyle = `rgba(${STATUS_RGB.broken}, ${0.5 + (a.flash + b.flash) * 0.2})`;
      ctx.beginPath();
      ctx.moveTo(px(a.x), py(a.y));
      ctx.lineTo(px(b.x), py(b.y));
      ctx.stroke();
    }

    // ---- absence, drawn explicitly --------------------------------------
    // A connection that should exist and does not. The endpoints are pulled
    // apart so the gap itself is the mark.
    for (let e = 0; e < linkArr.length; e++) {
      const link = linkArr[e];
      if (link.kind !== "missing") continue;
      const a = nodeArr[link.a];
      const b = nodeArr[link.b];
      const ax = px(a.x);
      const ay = py(a.y);
      const bx = px(b.x);
      const by = py(b.y);
      const dxp = bx - ax;
      const dyp = by - ay;
      const len = Math.hypot(dxp, dyp) || 1;
      const ux = dxp / len;
      const uy = dyp / len;
      const gap = Math.min(18, len * 0.16);
      const sx = ax + ux * gap;
      const sy = ay + uy * gap;
      const ex = bx - ux * gap;
      const ey = by - uy * gap;
      const mx = (sx + ex) / 2 - uy * len * 0.16;
      const my = (sy + ey) / 2 + ux * len * 0.16;
      ctx.setLineDash([5, 5]);
      ctx.lineWidth = 1.4;
      ctx.strokeStyle = `rgba(${STATUS_RGB.broken}, ${0.55 + (a.flash + b.flash) * 0.2})`;
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.quadraticCurveTo(mx, my, ex, ey);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // ---- nodes: glowing dots, radius/brightness ∝ blast radius ----------
    for (let i = 0; i < nodeArr.length; i++) {
      const n = nodeArr[i];
      const x = px(n.x);
      const y = py(n.y);

      // blast radius drives size + brightness; flash spikes both transiently
      const flash = n.flash;
      const weight = n.weight;
      // the node the checker is touching right now reads as active, unless it
      // already carries a status worth keeping on screen
      const status: SeamStatus = n.status === "healthy" && flash > 0.05 ? "active" : n.status;
      const hue = STATUS_RGB[status];
      const dim = n.layer === "baseline" ? 0.45 : 1;
      const core = n.radiusBase * (0.5 + weight * 1.35) * (1 + flash * 0.9);
      const glowR = core * (5 + weight * 4 + flash * 6);

      // soft radial glow
      const g = ctx.createRadialGradient(x, y, 0, x, y, glowR);
      const glowA = (0.1 + weight * 0.18 + flash * 0.5) * dim;
      g.addColorStop(0, `rgba(${hue}, ${glowA})`);
      g.addColorStop(0.4, `rgba(${hue}, ${glowA * 0.4})`);
      g.addColorStop(1, `rgba(${hue}, 0)`);
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(x, y, glowR, 0, Math.PI * 2);
      ctx.fill();

      // bright core dot
      ctx.fillStyle = `rgba(${hue}, ${(0.55 + weight * 0.4 + flash * 0.4) * dim})`;
      ctx.beginPath();
      ctx.arc(x, y, core, 0, Math.PI * 2);
      ctx.fill();

      // a tiny hot center on the nodes with the widest blast radius
      if (n.layer === "session" && (weight > 0.55 || flash > 0.1)) {
        ctx.fillStyle = `rgba(255, 255, 255, ${0.18 + flash * 0.45})`;
        ctx.beginPath();
        ctx.arc(x, y, core * 0.42, 0, Math.PI * 2);
        ctx.fill();
      }

      // which worktree wrote it: a ring, never the fill. Agent A is solid,
      // agent B is dashed, and the baseline carries no ring at all.
      if (n.agent) {
        ctx.setLineDash(n.agent === "b" ? [2, 3] : []);
        ctx.lineWidth = 1;
        ctx.strokeStyle = `rgba(255, 255, 255, ${0.22 + flash * 0.35})`;
        ctx.beginPath();
        ctx.arc(x, y, core + 4.5, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    // ---- labels: session layer only, the baseline stays anonymous -------
    ctx.font = "9px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.textAlign = "center";
    for (let i = 0; i < nodeArr.length; i++) {
      const n = nodeArr[i];
      if (n.layer !== "session") continue;
      const status: SeamStatus = n.status === "healthy" && n.flash > 0.05 ? "active" : n.status;
      const core = n.radiusBase * (0.5 + n.weight * 1.35) * (1 + n.flash * 0.9);
      const offset = core + 9;
      ctx.textBaseline = n.labelAbove ? "bottom" : "top";
      ctx.fillStyle = `rgba(${STATUS_RGB[status]}, ${0.62 + n.flash * 0.3})`;
      ctx.fillText(n.label, px(n.x), py(n.y) + (n.labelAbove ? -offset : offset));
    }

    // ---- expanding flash rings ------------------------------------------
    const rings = ringsRef.current;
    for (let i = rings.length - 1; i >= 0; i--) {
      const r = rings[i];
      r.t += dt * r.speed;
      if (r.t >= 1) {
        rings.splice(i, 1);
        continue;
      }
      const x = px(r.x);
      const y = py(r.y);
      const eased = 1 - Math.pow(1 - r.t, 3); // easeOutCubic
      const radius = 6 + eased * (scale * 0.18);
      const alpha = (1 - r.t) * 0.5;
      ctx.strokeStyle = `rgba(${STATUS_RGB.active}, ${alpha})`;
      ctx.lineWidth = 1.5 * (1 - r.t) + 0.5;
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.stroke();
    }

    // ---- traveling particles --------------------------------------------
    const particles = particlesRef.current;
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      p.t += dt * p.speed;
      if (p.t >= 1) {
        particles.splice(i, 1);
        continue;
      }
      // easeInOut for a satisfying glide
      const e = p.t < 0.5 ? 2 * p.t * p.t : 1 - Math.pow(-2 * p.t + 2, 2) / 2;
      const ux = p.fromX + (p.toX - p.fromX) * e;
      const uy = p.fromY + (p.toY - p.fromY) * e;
      const x = px(ux);
      const y = py(uy);

      // a short comet trail
      const tailE =
        Math.max(0, p.t - 0.06) < 0.5
          ? 2 * Math.max(0, p.t - 0.06) ** 2
          : 1 - Math.pow(-2 * Math.max(0, p.t - 0.06) + 2, 2) / 2;
      const tx = px(p.fromX + (p.toX - p.fromX) * tailE);
      const ty = py(p.fromY + (p.toY - p.fromY) * tailE);
      const tg = ctx.createLinearGradient(tx, ty, x, y);
      tg.addColorStop(0, `rgba(${p.hue}, 0)`);
      tg.addColorStop(1, `rgba(${p.hue}, 0.6)`);
      ctx.strokeStyle = tg;
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.moveTo(tx, ty);
      ctx.lineTo(x, y);
      ctx.stroke();

      // particle head glow
      const headR = 7;
      const pg = ctx.createRadialGradient(x, y, 0, x, y, headR);
      pg.addColorStop(0, `rgba(${p.hue}, 0.95)`);
      pg.addColorStop(0.5, `rgba(${p.hue}, 0.4)`);
      pg.addColorStop(1, `rgba(${p.hue}, 0)`);
      ctx.fillStyle = pg;
      ctx.beginPath();
      ctx.arc(x, y, headR, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "rgba(255,255,255,0.9)";
      ctx.beginPath();
      ctx.arc(x, y, 1.6, 0, Math.PI * 2);
      ctx.fill();
    }
  });

  // Repaint the caption heartbeat ~every second (cheap, decoupled from RAF).
  // liveOn starts false on both SSR and first client render (no Date.now() in render → no
  // hydration mismatch), then toggles on the interval.
  const [liveOn, setLiveOn] = useState(false);
  useEffect(() => {
    const id = setInterval(() => {
      force((n) => (n + 1) % 1000);
      setLiveOn((v) => !v);
    }, 1100);
    return () => clearInterval(id);
  }, []);

  void clusterAngles;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12, filter: "blur(8px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      transition={{ duration: 0.9, ease: EASE }}
      className="relative h-full w-full overflow-hidden rounded-2xl border border-white/[0.08] bg-gradient-to-b from-[#0e0f0e] to-[#0a0b0a] shadow-[0_30px_80px_-20px_rgba(0,0,0,0.8),inset_0_1px_0_rgba(255,255,255,0.04)] backdrop-blur-sm"
    >
      {/* ambient emerald blobs behind the map */}
      <div
        className="pointer-events-none absolute -inset-[20%]"
        style={{
          background:
            "radial-gradient(38% 38% at 32% 30%, rgba(52,211,153,0.10), transparent 70%), radial-gradient(42% 42% at 72% 70%, rgba(110,231,183,0.07), transparent 72%)",
          filter: "blur(120px)",
        }}
      />

      {/* dotted texture, masked to a soft ellipse */}
      <div
        className="pointer-events-none absolute inset-0 opacity-70"
        style={{
          backgroundImage:
            "radial-gradient(rgba(52,211,153,0.05) 1px, transparent 1px)",
          backgroundSize: "34px 34px",
          maskImage:
            "radial-gradient(ellipse 70% 70% at 50% 50%, #000 30%, transparent 78%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 70% 70% at 50% 50%, #000 30%, transparent 78%)",
        }}
      />

      {/* "frame as glow": a hairline drawn as an inset shadow on a masked layer */}
      <div
        className="pointer-events-none absolute inset-0 rounded-2xl"
        style={{
          boxShadow: "inset 0 0 0 1px rgba(110,231,183,0.10)",
          maskImage:
            "radial-gradient(ellipse 90% 90% at 50% 40%, #000 40%, transparent 100%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 90% 90% at 50% 40%, #000 40%, transparent 100%)",
        }}
      />

      {/* the map */}
      <div ref={wrapRef} className="absolute inset-0">
        <canvas ref={canvasRef} className="absolute inset-0 block" aria-hidden />
      </div>

      {/* subtle vignette so the map sits in a pool of dark */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 75% 75% at 50% 50%, transparent 55%, rgba(0,0,0,0.55) 100%)",
        }}
      />

      {/* tiny mono legend */}
      <div className="pointer-events-none absolute bottom-3 left-4 flex items-center gap-2">
        <span
          className="inline-block h-1.5 w-1.5 rounded-full"
          style={{
            background: `rgba(${EMERALD_PALE}, ${liveOn ? 0.95 : 0.35})`,
            boxShadow: liveOn
              ? "0 0 8px rgba(110,231,183,0.8)"
              : "0 0 0 rgba(0,0,0,0)",
            transition: "all 300ms ease",
          }}
        />
        <span className="font-mono text-[9px] uppercase tracking-[0.28em] text-emerald-300/55">
          live seam map
        </span>
      </div>

      <div className="pointer-events-none absolute bottom-3 right-4 text-right">
        <span className="font-mono text-[9px] uppercase tracking-[0.22em] tabular-nums text-emerald-300/45">
          {nodes.length} seams · size = blast radius
        </span>
      </div>
    </motion.div>
  );
}

// ---- layout construction ----------------------------------------------------

/**
 * Build the deterministic node + link layout from the declared seams.
 *
 * Clustering strategy: nodes joined by any edge share a lobe, so a producer and
 * the consumers that call it sit together and every declared connection stays
 * local. Each connected group is keyed by its lowest member id, which is stable
 * regardless of node order, and gets a fixed angle around the center (groups
 * sorted by key, then spread evenly). Nodes scatter near that lobe center with
 * jitter seeded on the node id, so the codebase lands in the same place every
 * session and the server and client produce byte-identical layouts.
 */
function buildLayout(seamNodes: SeamNode[], seamEdges: SeamEdge[]) {
  const index = new Map<string, number>();
  seamNodes.forEach((n, i) => index.set(n.id, i));

  // ---- connected groups via union-find ------------------------------------
  const parent = seamNodes.map((_, i) => i);
  const find = (i: number): number => {
    while (parent[i] !== i) {
      parent[i] = parent[parent[i]];
      i = parent[i];
    }
    return i;
  };
  for (const e of seamEdges) {
    const a = index.get(e.source);
    const b = index.get(e.target);
    if (a == null || b == null) continue;
    const ra = find(a);
    const rb = find(b);
    if (ra !== rb) parent[ra] = rb;
  }
  // key each group by its lowest member id so the key never depends on order
  const groupKey = new Map<number, string>();
  seamNodes.forEach((n, i) => {
    const root = find(i);
    const current = groupKey.get(root);
    if (current == null || n.id < current) groupKey.set(root, n.id);
  });
  const clusterOf = (i: number) => groupKey.get(find(i)) ?? seamNodes[i].id;

  // ---- group -> fixed angle -----------------------------------------------
  const clusters = Array.from(new Set(seamNodes.map((_, i) => clusterOf(i)))).sort();
  const clusterCount = Math.max(1, clusters.length);
  const clusterAngle = new Map<string, number>();
  const clusterCenter = new Map<string, { x: number; y: number }>();
  clusters.forEach((key, i) => {
    const angle = (i / clusterCount) * Math.PI * 2 - Math.PI / 2;
    clusterAngle.set(key, angle);
    // cluster centers sit on a ring; a touch of seeded radial variation so
    // the lobes aren't a perfect circle.
    const rand = makeRand(hashStr(key) ^ 0x9e3779b9);
    const ringR = 0.52 + (rand() - 0.5) * 0.16;
    clusterCenter.set(key, {
      x: Math.cos(angle) * ringR,
      y: Math.sin(angle) * ringR,
    });
  });

  // ---- status per node, read off the edges --------------------------------
  // A node on a disagreeing seam is broken. A node on a connection that should
  // exist and does not is an orphan. Broken outranks orphan. Everything else is
  // healthy and therefore carries no color.
  const status = new Map<string, SeamStatus>();
  for (const n of seamNodes) status.set(n.id, "healthy");
  for (const e of seamEdges) {
    if (e.kind === "ok") continue;
    for (const id of [e.source, e.target]) {
      if (!status.has(id)) continue;
      if (e.kind === "mismatch") status.set(id, "broken");
      else if (status.get(id) !== "broken") status.set(id, "orphan");
    }
  }

  const maxBlast = Math.max(1, ...seamNodes.map((n) => n.blastRadius));

  // Members of each lobe, ordered by id so the seat each node takes never
  // depends on input order.
  const roster = new Map<string, string[]>();
  seamNodes.forEach((n, i) => {
    const key = clusterOf(i);
    const list = roster.get(key);
    if (list) list.push(n.id);
    else roster.set(key, [n.id]);
  });
  roster.forEach((list) => list.sort());

  // ---- build nodes --------------------------------------------------------
  const nodes: Node[] = seamNodes.map((s, i) => {
    const cluster = clusterOf(i);
    const center = clusterCenter.get(cluster) ?? { x: 0, y: 0 };
    const rand = makeRand(hashStr(s.id));

    // Seats around the lobe center rather than a gaussian scatter: a summed
    // scatter piles members on top of each other and their labels collide, and
    // a label collision on this map reads as one seam instead of two.
    const list = roster.get(cluster) ?? [s.id];
    const seat = Math.max(0, list.indexOf(s.id));
    const count = Math.max(1, list.length);
    const spread = 0.2 * Math.sqrt(Math.max(2, count) / 2);
    const phase = (hashStr(cluster) % 360) * (Math.PI / 180);
    const angle = (seat / count) * Math.PI * 2 + phase;
    const radius = count === 1 ? 0 : spread * (0.92 + rand() * 0.22);
    const ox = Math.cos(angle) * radius * 1.35;
    const oy = Math.sin(angle) * radius;

    // blast radius normalized against the widest node on the map
    const weight = Math.max(0.04, Math.min(1, s.blastRadius / maxBlast));

    return {
      id: s.id,
      label: s.label,
      cluster,
      agent: s.agent,
      layer: s.layer,
      status: status.get(s.id) ?? "healthy",
      weight,
      labelAbove: oy < 0,
      cx: center.x,
      cy: center.y,
      ox,
      oy,
      wphX: rand() * Math.PI * 2,
      wphY: rand() * Math.PI * 2,
      wspX: 0.18 + rand() * 0.32,
      wspY: 0.18 + rand() * 0.32,
      wampX: 0.012 + rand() * 0.03,
      wampY: 0.012 + rand() * 0.03,
      x: center.x + ox,
      y: center.y + oy,
      flash: 0,
      // the baseline layer renders small: context, never the subject
      radiusBase: s.layer === "baseline" ? 1.15 : 2.2,
    };
  });

  // ---- resolve declared edges to node indices -----------------------------
  const links: Link[] = [];
  for (const e of seamEdges) {
    const a = index.get(e.source);
    const b = index.get(e.target);
    if (a == null || b == null) continue;
    links.push({ a, b, kind: e.kind, layer: e.layer });
  }

  return {
    nodes,
    links,
    clusterAngles: clusterAngle,
  };
}
