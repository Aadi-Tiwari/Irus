"use client";

import { useCallback, useRef, useState } from "react";
import { AnimatePresence, motion, type Variants } from "motion/react";
import { PRESETS, checkSeam, type Check, type Encoding, type Side } from "@/lib/seam-check";
import { STATUS_ACCENT } from "@/lib/scale";

/* ──────────────────────────────────────────────────────────────────────────
 * SeamCheckBox: the judge-usable beat.
 *
 * Declare what each side of one seam sends and expects, and get the stage-1
 * check lines back: PASS, FAIL, or UNKNOWN. It runs in the browser with no
 * network and no model in the path, so the same two sides always produce the
 * same lines. This is a toy of the real stage-1 payload check, which is handed
 * nothing and instead parses both sides out of your code.
 *
 * Aesthetic: matches the rest of the app exactly, near-black, emerald-only
 * accent at low opacity, mono/tabular numbers, glow-as-frame (inset hairline
 * box-shadow on a radial-masked layer, never a hard border), dotted texture,
 * and motion/react springs (stiffness 140 / damping 18) for scale/number
 * changes with a stagger-in reveal (opacity + y + blur to 0).
 * ────────────────────────────────────────────────────────────────────────── */

const ease = [0.22, 1, 0.36, 1] as const;
const SPRING = { type: "spring" as const, stiffness: 140, damping: 18, mass: 0.6 };

const EMERALD = "#34d399";
const EMERALD_LIGHT = "#6ee7b7";
const EMERALD_PALE = "#a7f3d0";

const ENCODINGS: Encoding[] = ["json", "multipart", "urlencoded"];

type Status = "idle" | "loading" | "results" | "error";

/* A finished check run: the lines, plus which seam produced them. */
type Run = { seam: string; checks: Check[] };

/* verdict to tone. PASS is the emerald the whole page already uses, FAIL takes
   the broken-seam red from the live map, UNKNOWN stays slate, so one colour
   means one thing everywhere on the site. */
function verdictTone(status: Check["status"]) {
  if (status === "PASS") return { color: STATUS_ACCENT.pass, glow: "rgba(52,211,153,0.55)" };
  if (status === "FAIL") return { color: STATUS_ACCENT.broken, glow: "rgba(208,59,59,0.5)" };
  return { color: STATUS_ACCENT.unknown, glow: "rgba(148,163,184,0.45)" };
}

/* `name:type, other:type` in, a declared side out. `...rest` marks a body the
   scanner cannot enumerate, which suppresses the missing-field check rather
   than guessing at it. */
function parseFields(raw: string) {
  const fields: Record<string, string> = {};
  let spread = false;
  for (const part of raw.split(",")) {
    const token = part.trim();
    if (!token) continue;
    if (token.startsWith("...")) {
      spread = true;
      continue;
    }
    const [name, type] = token.split(":").map((s) => s.trim());
    if (!name) continue;
    fields[name] = type ?? "";
  }
  return { fields, spread };
}

function formatFields(side: Side) {
  const parts = Object.entries(side.fields).map(([k, v]) => (v ? `${k}:${v}` : k));
  if (side.spread) parts.push("...rest");
  return parts.join(", ");
}

/* two digits, so the ordinals stay in one column */
function ordinal(i: number) {
  return String(i + 1).padStart(2, "0");
}

/* ── icons (inline SVG, no icon libraries) ──────────────────────────────── */
function SearchIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.7" />
      <path d="m20 20-3.2-3.2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}
function SparkIcon({ size = 13 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 3v4M12 17v4M3 12h4M17 12h4M6.3 6.3l2.4 2.4M15.3 15.3l2.4 2.4M17.7 6.3l-2.4 2.4M8.7 15.3l-2.4 2.4"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
function LeafIcon({ size = 12 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M5 19c0-8 6-14 14-14 0 8-6 14-14 14Z" fill="currentColor" opacity={0.22} />
      <path d="M5 19c0-8 6-14 14-14 0 8-6 14-14 14Z" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" />
      <path d="M6 18C9 14 12 11 16 9" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" />
    </svg>
  );
}

/* ── verdict pill: the word + a tiny fill bar in its colour ─────────────── */
function VerdictPill({ status }: { status: Check["status"] }) {
  const tone = verdictTone(status);
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-emerald-300/45">verdict</span>
      <span className="font-mono text-[12px] tabular-nums" style={{ color: tone.color }}>
        {status}
      </span>
      <span className="relative h-1.5 w-14 overflow-hidden rounded-full bg-white/[0.08]">
        <motion.span
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ background: tone.color, boxShadow: `0 0 8px ${tone.glow}` }}
          initial={{ width: 0 }}
          animate={{ width: "100%" }}
          transition={{ ...SPRING, delay: 0.12 }}
        />
      </span>
    </span>
  );
}

/* ── one check line ─────────────────────────────────────────────────────── */
const cardRise: Variants = {
  hidden: { opacity: 0, y: 16, filter: "blur(8px)" },
  show: { opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: 0.55, ease } },
};

function CheckCard({
  check,
  seam,
  index,
  top,
}: {
  check: Check;
  seam: string;
  index: number;
  top: boolean;
}) {
  const tone = verdictTone(check.status);

  return (
    <motion.div variants={cardRise} className="relative">
      {/* the line that fails gets a brighter ambient bloom behind it */}
      {top && (
        <div
          aria-hidden
          className="pointer-events-none absolute -inset-3 -z-10 rounded-[24px] blur-2xl"
          style={{ background: "radial-gradient(60% 80% at 30% 30%, rgba(52,211,153,0.16), transparent 70%)" }}
        />
      )}

      <div
        className="relative overflow-hidden rounded-2xl border bg-gradient-to-b from-[#0e0f0e] to-[#0a0b0a] px-4 py-3.5 backdrop-blur-sm"
        style={{
          borderColor: top ? "rgba(52,211,153,0.28)" : "rgba(255,255,255,0.08)",
          boxShadow: top
            ? "0 30px 80px -20px rgba(0,0,0,0.8), 0 0 0 1px rgba(110,231,183,0.16), inset 0 1px 0 rgba(255,255,255,0.05)"
            : "0 30px 80px -20px rgba(0,0,0,0.8), inset 0 1px 0 rgba(255,255,255,0.04)",
        }}
      >
        {/* glow-as-frame: a hairline emerald inset, radially masked so it reads
            as light catching the edge rather than a drawn border. */}
        {top && (
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 rounded-2xl"
            style={{
              boxShadow: "inset 0 0 0 1px rgba(110,231,183,0.18)",
              maskImage: "radial-gradient(120% 130% at 50% 0%, #000 45%, transparent 100%)",
              WebkitMaskImage: "radial-gradient(120% 130% at 50% 0%, #000 45%, transparent 100%)",
            }}
          />
        )}

        <div className="relative">
          {/* header: marker · check name · seam · ordinal */}
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
              {top && (
                <span
                  className="flex-none rounded-md px-1.5 py-px font-mono text-[9px] font-semibold uppercase tracking-[0.18em]"
                  style={{
                    color: "#06281c",
                    background: `linear-gradient(135deg, ${EMERALD}, ${EMERALD_PALE})`,
                    boxShadow: "0 0 14px rgba(52,211,153,0.45)",
                  }}
                >
                  look here
                </span>
              )}
              <span
                className="truncate font-mono text-[13.5px] font-medium"
                style={top ? { color: EMERALD_PALE, textShadow: "0 0 12px rgba(110,231,183,0.4)" } : { color: "rgba(255,255,255,0.9)" }}
              >
                {check.label}
              </span>
              <span className="flex-none rounded border border-emerald-400/15 bg-emerald-400/[0.06] px-1.5 py-px font-mono text-[9px] uppercase tracking-wide text-emerald-200/80">
                {seam}
              </span>
            </div>

            {/* the verdict, glowing */}
            <span className="flex flex-none items-baseline gap-0.5">
              <span
                className="font-mono text-[16px] font-semibold tabular-nums leading-none"
                style={{ color: tone.color, textShadow: `0 0 12px ${tone.glow}` }}
              >
                {ordinal(index)}
              </span>
              <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-emerald-300/45">check</span>
            </span>
          </div>

          {/* what the two sides actually declared */}
          <p className="mt-2 line-clamp-2 text-[12.5px] leading-relaxed text-white/55">{check.detail}</p>

          {/* footer: verdict pill + where the answer came from */}
          <div className="mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-white/[0.06] pt-2.5">
            <VerdictPill status={check.status} />

            <div className="flex items-center gap-1.5">
              <span style={{ color: EMERALD_LIGHT }}>
                <LeafIcon />
              </span>
              <span className="font-mono text-[11.5px] text-emerald-200/85">no model in this path</span>
              <span className="font-mono text-[10px] text-white/30">· same input, same answer</span>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

/* ── loading skeleton: pulsing emerald hairlines, no spinner ─────────────── */
function SkeletonCard({ i }: { i: number }) {
  return (
    <motion.div
      className="overflow-hidden rounded-2xl border border-white/[0.07] bg-gradient-to-b from-[#0e0f0e] to-[#0a0b0a] px-4 py-3.5"
      animate={{ opacity: [0.45, 0.85, 0.45] }}
      transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut", delay: i * 0.14 }}
    >
      <div className="flex items-center justify-between">
        <div className="h-3.5 w-40 rounded-full bg-emerald-400/[0.10]" />
        <div className="h-3.5 w-12 rounded-full bg-emerald-400/[0.10]" />
      </div>
      <div className="mt-3 h-2.5 w-[88%] rounded-full bg-white/[0.05]" />
      <div className="mt-2 h-2.5 w-[64%] rounded-full bg-white/[0.05]" />
      <div className="mt-3 flex items-center justify-between border-t border-white/[0.05] pt-2.5">
        <div className="h-2.5 w-24 rounded-full bg-emerald-400/[0.08]" />
        <div className="h-2.5 w-28 rounded-full bg-emerald-400/[0.08]" />
      </div>
    </motion.div>
  );
}

/* ── one declared side of the seam ──────────────────────────────────────── */
function SideBar({
  role,
  value,
  onChange,
  encoding,
  onEncoding,
  placeholder,
  children,
}: {
  role: string;
  value: string;
  onChange: (v: string) => void;
  encoding: Encoding;
  onEncoding: (e: Encoding) => void;
  placeholder: string;
  children?: React.ReactNode;
}) {
  return (
    <div
      className="group flex items-center gap-3 rounded-2xl border border-white/[0.08] bg-gradient-to-b from-[#0e0f0e] to-[#0a0b0a] px-4 py-3 backdrop-blur-sm transition-colors focus-within:border-emerald-400/40"
      style={{ boxShadow: "0 30px 80px -28px rgba(0,0,0,0.85), inset 0 1px 0 rgba(255,255,255,0.04)" }}
    >
      <span className="text-emerald-300/45 transition-colors group-focus-within:text-emerald-300/80">
        <SearchIcon />
      </span>
      <span className="flex-none font-mono text-[9px] uppercase tracking-[0.2em] text-emerald-300/45">{role}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        spellCheck={false}
        autoComplete="off"
        aria-label={`Fields the ${role} declares`}
        className="w-full bg-transparent font-mono text-[13px] text-white/85 placeholder:text-white/25 focus:outline-none"
      />
      <select
        value={encoding}
        onChange={(e) => onEncoding(e.target.value as Encoding)}
        aria-label={`Encoding the ${role} uses`}
        className="flex-none appearance-none rounded-xl border border-emerald-400/25 bg-emerald-400/[0.08] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.18em] text-emerald-200 transition-all hover:border-emerald-400/45 focus:outline-none"
      >
        {ENCODINGS.map((enc) => (
          <option key={enc} value={enc} className="bg-[#0e0f0e] text-emerald-100">
            {enc}
          </option>
        ))}
      </select>
      {children}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
export default function SeamCheckBox() {
  const [clientFields, setClientFields] = useState("");
  const [clientEncoding, setClientEncoding] = useState<Encoding>("json");
  const [serverFields, setServerFields] = useState("");
  const [serverEncoding, setServerEncoding] = useState<Encoding>("json");
  const [seam, setSeam] = useState("custom seam");

  const [status, setStatus] = useState<Status>("idle");
  const [run, setRun] = useState<Run | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // a submit while the previous reveal is still pending supersedes it, so the
  // older result can never land on top of the fresher one
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);

  const check = useCallback((client: Side, server: Side, name: string) => {
    if (pending.current) clearTimeout(pending.current);

    if (Object.keys(server.fields).length === 0) {
      setErrorMsg("the server side declares no fields, so there is nothing to compare");
      setStatus("error");
      return;
    }

    setStatus("loading");
    setErrorMsg(null);

    pending.current = setTimeout(() => {
      setRun({ seam: name, checks: checkSeam(client, server) });
      setStatus("results");
    }, 260);
  }, []);

  const fromInputs = () => {
    const c = parseFields(clientFields);
    const s = parseFields(serverFields);
    const client: Side = {
      encoding: clientEncoding,
      fields: c.fields,
      required: [],
      spread: c.spread,
    };
    // hand-declared sides have no separate required list, so every field the
    // server declares is treated as required
    const server: Side = {
      encoding: serverEncoding,
      fields: s.fields,
      required: Object.keys(s.fields),
    };
    return { client, server };
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const { client, server } = fromInputs();
    check(client, server, seam);
  };

  const pickPreset = (preset: (typeof PRESETS)[number]) => {
    setClientFields(formatFields(preset.client));
    setClientEncoding(preset.client.encoding);
    setServerFields(formatFields(preset.server));
    setServerEncoding(preset.server.encoding);
    setSeam(preset.name);
    check(preset.client, preset.server, preset.name);
  };

  const loading = status === "loading";
  const ready = clientFields.trim().length > 0 || serverFields.trim().length > 0;

  // colour is scarce: only the first failing line is marked
  const topIndex = run ? run.checks.findIndex((c) => c.status === "FAIL") : -1;

  return (
    <div className="relative isolate w-full max-w-2xl">
      {/* ambient radial bloom behind the whole box */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-0 -z-10 h-[26rem] w-[34rem] -translate-x-1/2 rounded-full blur-[120px]"
        style={{ background: "radial-gradient(circle, rgba(52,211,153,0.10), transparent 65%)" }}
      />
      {/* dotted texture, masked to an ellipse so it fades at the edges */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 opacity-60"
        style={{
          backgroundImage: "radial-gradient(rgba(52,211,153,0.05) 1px, transparent 1px)",
          backgroundSize: "34px 34px",
          maskImage: "radial-gradient(ellipse 85% 70% at 50% 30%, black, transparent 84%)",
          WebkitMaskImage: "radial-gradient(ellipse 85% 70% at 50% 30%, black, transparent 84%)",
        }}
      />

      {/* ── the two sides of one seam ────────────────────────────────────── */}
      <form onSubmit={onSubmit} className="relative space-y-2.5">
        <SideBar
          role="client"
          value={clientFields}
          onChange={setClientFields}
          encoding={clientEncoding}
          onEncoding={setClientEncoding}
          placeholder='fields it sends, e.g. "user_email:str, total:str"'
        />
        <SideBar
          role="server"
          value={serverFields}
          onChange={setServerFields}
          encoding={serverEncoding}
          onEncoding={setServerEncoding}
          placeholder='fields it requires, e.g. "email:str, amount:int"'
        >
          <button
            type="submit"
            disabled={loading || !ready}
            className="flex flex-none items-center gap-1.5 rounded-xl border border-emerald-400/25 bg-emerald-400/[0.08] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.18em] text-emerald-200 transition-all hover:border-emerald-400/45 hover:bg-emerald-400/[0.14] disabled:cursor-not-allowed disabled:opacity-40"
            style={{ boxShadow: "0 0 18px -6px rgba(52,211,153,0.5)" }}
          >
            <SparkIcon />
            check
          </button>
        </SideBar>
      </form>

      {/* ── body: state machine ──────────────────────────────────────────── */}
      <div className="relative mt-4 min-h-[120px]">
        <AnimatePresence mode="wait">
          {/* IDLE: the recorded session's seams, one click away */}
          {status === "idle" && (
            <motion.div
              key="idle"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.4, ease }}
            >
              <div className="flex flex-wrap gap-2">
                {PRESETS.map((p) => (
                  <button
                    key={p.name}
                    type="button"
                    onClick={() => pickPreset(p)}
                    title={p.note}
                    className="rounded-full border border-emerald-400/12 bg-emerald-400/[0.03] px-3 py-1.5 font-mono text-[11px] text-white/55 transition-colors hover:border-emerald-400/30 hover:text-emerald-200/85"
                  >
                    {p.name}
                  </button>
                ))}
              </div>
              <p className="mt-4 max-w-md text-[12px] leading-relaxed text-white/35">
                Declare what each side sends and expects. This is a{" "}
                <span className="text-emerald-200/75">toy of the stage-1 payload check</span>: it is
                handed the fields, where the real one parses them out of your code. Every field the
                server declares counts as required, and <span className="font-mono">...rest</span>{" "}
                marks a body that cannot be enumerated.
              </p>
            </motion.div>
          )}

          {/* LOADING: pulsing skeletons */}
          {status === "loading" && (
            <motion.div
              key="loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
              className="space-y-2.5"
            >
              <div className="mb-1 flex items-center gap-2">
                <motion.span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ background: EMERALD, boxShadow: `0 0 8px ${EMERALD}` }}
                  animate={{ opacity: [1, 0.25, 1] }}
                  transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
                />
                <span className="font-mono text-[9px] uppercase tracking-[0.28em] text-emerald-300/55">
                  comparing both sides…
                </span>
              </div>
              {[0, 1, 2].map((i) => (
                <SkeletonCard key={i} i={i} />
              ))}
            </motion.div>
          )}

          {/* RESULTS: staggered check lines */}
          {status === "results" && run && (
            <motion.div
              key="results"
              initial="hidden"
              animate="show"
              exit={{ opacity: 0, transition: { duration: 0.2 } }}
              variants={{ hidden: {}, show: { transition: { staggerChildren: 0.07, delayChildren: 0.04 } } }}
              className="space-y-2.5"
            >
              {run.checks.map((c, i) => (
                <CheckCard key={c.label} check={c} seam={run.seam} index={i} top={i === topIndex} />
              ))}
            </motion.div>
          )}

          {/* ERROR: nothing to compare */}
          {status === "error" && (
            <motion.div
              key="error"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.4, ease }}
              className="rounded-2xl border border-amber-400/20 bg-amber-400/[0.02] px-5 py-6 text-center"
            >
              <div className="font-mono text-[12.5px] text-amber-300/90">the check had nothing to read</div>
              <p className="mx-auto mt-1.5 max-w-sm font-mono text-[11px] text-white/35">{errorMsg}</p>
              <button
                type="button"
                onClick={() => setStatus("idle")}
                className="mt-3 rounded-lg border border-amber-400/25 bg-amber-400/[0.06] px-3 py-1.5 font-mono text-[11px] tracking-wide text-amber-200 transition-colors hover:border-amber-400/45"
              >
                start over
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* caption */}
      <p className="mt-4 font-mono text-[9.5px] uppercase tracking-[0.2em] text-emerald-300/40">
        a toy of the stage-1 check · runs in your browser, no network, no model · the real one parses your code
      </p>
    </div>
  );
}
