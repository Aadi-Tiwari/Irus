// A toy of the stage-1 payload check, running in the browser so the page can be poked
// at without installing anything. The real check parses Python with the standard
// library `ast` and TypeScript with a dependency-free scanner that masks strings and
// comments before any structural parsing. This one is handed the declared fields
// directly. What it shares with the real thing is the part that matters: it is a
// deterministic comparison of what each side declares, with no model in the path, and
// it says `unknown` instead of guessing.

export type Encoding = "json" | "multipart" | "urlencoded";

export type Side = {
  encoding: Encoding;
  // `name: type`. Types are compared only when both sides declare one.
  fields: Record<string, string>;
  required: string[];
  // A spread (`...rest`) means the scanner cannot enumerate the body, so
  // missing-field checks are suppressed for this seam rather than guessed at.
  spread?: boolean;
};

export type Check = {
  label: string;
  status: "PASS" | "FAIL" | "UNKNOWN";
  detail: string;
};

export function checkSeam(client: Side, server: Side): Check[] {
  const checks: Check[] = [];

  checks.push(
    client.encoding === server.encoding
      ? { label: "encoding matches", status: "PASS", detail: `both sides use ${server.encoding}` }
      : {
          label: "encoding matches",
          status: "FAIL",
          detail: `client sends ${client.encoding}, server expects ${server.encoding}`,
        },
  );

  if (client.spread) {
    checks.push({
      label: "payload shape matches",
      status: "UNKNOWN",
      detail: "client body is assembled through a spread, so the fields cannot be enumerated",
    });
    return checks;
  }

  const missing = server.required.filter((f) => !(f in client.fields));
  checks.push(
    missing.length === 0
      ? { label: "payload shape matches", status: "PASS", detail: "every required field is sent" }
      : {
          label: "payload shape matches",
          status: "FAIL",
          detail: missing
            .map((f) => `server requires \`${f}\`${server.fields[f] ? ` (${server.fields[f]})` : ""}`)
            .join("; "),
        },
  );

  const mistyped = Object.keys(client.fields).filter(
    (f) => server.fields[f] && server.fields[f] !== client.fields[f],
  );
  if (mistyped.length > 0) {
    checks.push({
      label: "field types match",
      status: "FAIL",
      detail: mistyped
        .map((f) => `\`${f}\`: client sends ${client.fields[f]}, server declares ${server.fields[f]}`)
        .join("; "),
    });
  }

  const unread = Object.keys(client.fields).filter((f) => !(f in server.fields));
  if (unread.length > 0) {
    checks.push({
      label: "no unread fields",
      status: "UNKNOWN",
      detail: `server never reads ${unread.map((f) => `\`${f}\``).join(", ")}, which may be deliberate`,
    });
  }

  return checks;
}

// Presets are the two halves of the recorded session, so the box reproduces the
// headline finding without anything to install.
export const PRESETS: { name: string; note: string; client: Side; server: Side }[] = [
  {
    name: "POST /api/checkout",
    note: "the recorded session: agent B's form against agent A's handler",
    client: { encoding: "multipart", fields: { user_email: "str", total: "str" }, required: [] },
    server: {
      encoding: "json",
      fields: { email: "str", amount: "int" },
      // Reported in the order the handler declares them, which is the order the
      // recorded session's transcript prints.
      required: ["amount", "email"],
    },
  },
  {
    name: "POST /api/checkout, after the fix",
    note: "the consumer adapted, because the producer is authoritative by default",
    client: { encoding: "json", fields: { email: "str", amount: "int" }, required: [] },
    server: {
      encoding: "json",
      fields: { email: "str", amount: "int" },
      required: ["email", "amount"],
    },
  },
  {
    name: "POST /api/refund",
    note: "a body built through a spread: reported unknown, never guessed",
    client: { encoding: "json", fields: { order_id: "str" }, required: [], spread: true },
    server: {
      encoding: "json",
      fields: { order_id: "str", reason: "str" },
      required: ["order_id", "reason"],
    },
  },
];
