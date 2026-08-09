"use client";

import { useSession } from "@/lib/useSession";
import SweepGauges from "@/components/dashboard/SweepGauges";
import ScaledLatency from "@/components/dashboard/ScaledLatency";
import SeamMap from "@/components/dashboard/SeamMap";
import SeamCheckBox from "@/components/dashboard/SeamCheckBox";
import BackdropFX from "@/components/BackdropFX";

// The live map. `irus watch` replays an append-only event log on connect, so a
// refresh rebuilds identical state; useSession replays the checked-in log on a
// timer, which is the same thing with the stream cut out. No backend.
export default function DashboardPage() {
  const { stats, pulse, nodes, edges } = useSession();

  return (
    <main className="relative min-h-screen w-full overflow-x-hidden bg-transparent text-[#e8efe9]">
      <BackdropFX />
      {/* ambient atmosphere */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10"
        style={{ background: "radial-gradient(120% 80% at 50% -8%, rgba(16,185,129,0.10), transparent 60%)" }}
      />
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10 opacity-50"
        style={{
          backgroundImage: "radial-gradient(rgba(52,211,153,0.05) 1px, transparent 1px)",
          backgroundSize: "34px 34px",
          maskImage: "radial-gradient(ellipse 85% 70% at 50% 25%, black, transparent 82%)",
          WebkitMaskImage: "radial-gradient(ellipse 85% 70% at 50% 25%, black, transparent 82%)",
        }}
      />

      <header className="mx-auto flex max-w-7xl items-center justify-between px-6 py-6 md:px-10">
        <div className="flex items-center gap-2.5">
          <span className="text-lg">⧉</span>
          <span className="font-mono text-sm tracking-wide text-emerald-200/90">irus</span>
          <span className="text-white/15">·</span>
          <span className="font-mono text-[11px] uppercase tracking-[0.2em] text-white/40">live map</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400/60" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
          </span>
          <span className="font-mono text-[11px] uppercase tracking-[0.2em] text-emerald-300/70">watching</span>
        </div>
      </header>

      {/* session counters: the hero */}
      <section className="mx-auto max-w-7xl px-6 pb-12 pt-2 md:px-10">
        <SweepGauges stats={stats} />
      </section>

      {/* the live map */}
      <section className="mx-auto max-w-7xl px-6 md:px-10">
        <div className="relative h-[62vh] min-h-[440px] w-full overflow-hidden rounded-2xl border border-white/[0.08] bg-gradient-to-b from-[#0c0d0c] to-[#0a0b0a] shadow-[0_30px_80px_-20px_rgba(0,0,0,0.8),inset_0_1px_0_rgba(255,255,255,0.04)]">
          <SeamMap nodes={nodes} edges={edges} pulse={pulse} />
        </div>
      </section>

      {/* judge-usable: try it */}
      <section className="mx-auto max-w-3xl px-6 py-16 md:px-10">
        <SeamCheckBox />
      </section>

      {/* the closer */}
      <section className="mx-auto max-w-7xl px-6 pb-24 md:px-10">
        <ScaledLatency stats={stats} />
      </section>
    </main>
  );
}
