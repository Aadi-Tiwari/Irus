"use client";

import { useEffect, useRef, useState } from "react";
import {
  EDGES,
  FINAL_STATS,
  FINDINGS,
  LOG,
  NODES,
  type Edge,
  type Finding,
  type LogEvent,
  type Node,
  type Stats,
} from "./session-fixture";

// Live state of the map. `irus watch` replays the append-only log over server-sent
// events on connect, so a refresh rebuilds identical state and the log doubles as a
// recording. Nothing here touches the network: the log is checked in, and replaying it
// on a timer is exactly what the real client does with the stream it receives.

export type { Edge, Finding, Node, Stats };

const REPLAY_SPEED = 6; // the sweep finishes in 280ms; stretch it so the eye can follow
const HOLD_MS = 4200; // pause on the finished state before looping

export function useSession() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [seen, setSeen] = useState<Set<string>>(new Set());
  const [log, setLog] = useState<LogEvent[]>([]);
  const [pulse, setPulse] = useState<{ id: string; nonce: number } | null>(null);
  const [done, setDone] = useState(false);
  const nonce = useRef(0);

  useEffect(() => {
    let timers: ReturnType<typeof setTimeout>[] = [];
    let loop: ReturnType<typeof setTimeout>;
    let active = true;

    const byId = new Map(FINDINGS.map((f) => [f.id, f]));

    const run = () => {
      if (!active) return;
      setFindings([]);
      setSeen(new Set());
      setLog([]);
      setStats(null);
      setDone(false);

      timers = LOG.map((e) =>
        setTimeout(() => {
          if (!active) return;
          setLog((prev) => [e, ...prev].slice(0, 40));
          setSeen((prev) => new Set(prev).add(e.id));
          nonce.current += 1;
          setPulse({ id: e.id, nonce: nonce.current });
          if (e.type === "finding") {
            const f = byId.get(e.id);
            if (f) setFindings((prev) => (prev.some((x) => x.id === f.id) ? prev : [...prev, f]));
          }
        }, e.t * REPLAY_SPEED),
      );

      const end = LOG[LOG.length - 1].t * REPLAY_SPEED;
      timers.push(
        setTimeout(() => {
          if (!active) return;
          setStats(FINAL_STATS);
          setDone(true);
        }, end + 120),
      );
      loop = setTimeout(run, end + HOLD_MS);
    };

    run();

    return () => {
      active = false;
      timers.forEach(clearTimeout);
      clearTimeout(loop);
    };
  }, []);

  return { stats, findings, log, seen, pulse, done, nodes: NODES, edges: EDGES };
}
