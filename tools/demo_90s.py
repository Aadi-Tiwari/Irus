"""The ninety-second demo, as a rehearsable script.

Five steps, in the order a judge can follow: state the problem, run it live,
show the number, reveal the twist, say what is next.

Everything here is real. The two halves were written by two agents that could
not see each other, the merge is a real git merge, and the finding is the one
the checker produces on that code. Nothing is planted and no agent runs live,
because a live agent is slow, nondeterministic, and will not produce the bug on
cue.

Run:  python tools/demo_90s.py          rehearse, pausing on Enter
      python tools/demo_90s.py --auto   run straight through, for timing
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO = Path(__file__).resolve().parents[1]
SESSION = REPO / "fixtures" / "gate-b-session"

BOLD, DIM, RED, GREEN, OFF = "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[0m"


def beat(auto: bool, seconds: float = 0.0) -> None:
    if auto:
        time.sleep(seconds)
    else:
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit(0)


def say(text: str) -> None:
    print(f"\n{BOLD}{text}{OFF}", flush=True)


def run(command: list[str], cwd: Path = REPO) -> int:
    print(f"{DIM}$ {' '.join(command)}{OFF}", flush=True)
    return subprocess.run(command, cwd=str(cwd)).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auto", action="store_true", help="no pauses; for timing")
    args = parser.parse_args()
    auto = args.auto
    started = time.perf_counter()

    # 1 ---------------------------------------------------------------- problem
    say("When two AI agents build two halves of one feature, integration")
    say("accuracy drops from 58% to 25%. Both report success. Nothing catches it.")
    print(f"{DIM}   The Specification Gap, arXiv 2603.24284{OFF}")
    beat(auto, 6)

    # 2 ------------------------------------------------------------- run it live
    say("Two agents. One spec. Separate worktrees. Neither could see the other.")
    print(f"{DIM}   The spec never named a field:{OFF}")
    print('   "the customer can change their display name and their marketing')
    print('    email preference (on or off)"')
    beat(auto, 5)

    say("Each wrote its half. Here is what they chose:")
    print(f"{DIM}   backend/app/schemas.py{OFF}")
    print("     class ProfileUpdateRequest(BaseModel):")
    print("         display_name: str")
    print(f"         {RED}marketing_emails{OFF}: bool")
    print(f"{DIM}   frontend/src/api/profile.ts{OFF}")
    print("     export interface UpdateProfileRequest {")
    print("       display_name: string;")
    print(f"       {RED}marketing_opt_in{OFF}: boolean;")
    print("     }")
    beat(auto, 6)

    say("Git merged both branches. Zero conflicts. Both sides compile.")
    print(f"{GREEN}   every signal available says this is fine{OFF}")
    beat(auto, 4)

    say("irus check")
    # Run once and keep the exit code. Running it twice to read the status
    # would double the pause on stage and invite the question of why the same
    # command appears twice.
    code = run([sys.executable, "-m", "irus", "check", str(SESSION), "--no-baseline"])
    print(f"\n{DIM}$ echo $?{OFF}\n{code}    {DIM}<- fails the merge gate{OFF}")
    beat(auto, 8)

    # 3 ----------------------------------------------------------------- number
    say("The number.")
    print("   72.1% precision over 226 judged findings, across five repositories")
    print("   nobody on this project wrote: dispatch, flower, redash, reflex,")
    print("   full-stack-fastapi-template.")
    print(f"\n{DIM}   Every false positive is published in findings/ledger.md.{OFF}")
    print(f"{DIM}   Labels come from raw text search, a different method than the{OFF}")
    print(f"{DIM}   parsed-syntax scanner that produced them, so the number is not{OFF}")
    print(f"{DIM}   the checker grading itself.{OFF}")
    beat(auto, 8)

    # 4 ------------------------------------------------------------------ twist
    say("The twist.")
    print("   There is no model anywhere in this. No API key. No network.")
    print("   Zero required dependencies. It just ran offline on this laptop.")
    beat(auto, 5)

    say("And it is not one demo repo. Point it at a different project:")
    run([sys.executable, "-m", "irus", "check",
         str(REPO / "tests" / "fixtures" / "shop"), "--no-baseline"])
    beat(auto, 6)

    # 5 ------------------------------------------------------------------- next
    say("What is next.")
    print("   Environment variables read but set nowhere is the one check the")
    print("   prior-art survey found genuinely unoccupied: dotenv-linter never")
    print("   reads source, knip has no env issue types, and nothing cross-")
    print("   references code against CI config. It runs at 97% precision.")
    print(f"\n{DIM}   elapsed: {time.perf_counter() - started:.0f}s{OFF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
