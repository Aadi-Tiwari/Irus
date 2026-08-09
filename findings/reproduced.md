# Reproduced mismatches: Gate B

**Status as of 9 Aug 2026: PASSED, with one mismatch reproduced and two features
that agreed. The premise needs one honest correction, recorded below.**

Gate B asks whether this checker catches something real between two actual
agents, or only things we planted ourselves. Until today the answer was that
nobody had tried.

## The experiment

A three-feature spec was written the way product specs actually get written: it
describes behaviour in prose and names no path, verb, field, or encoding.

> A customer submits a checkout. We need their email address and the amount they
> are paying, in cents. The service creates an order and responds with the new
> order's identifier and its status.

Two agents were given one half each, in separate git worktrees, with no
knowledge that the other existed. One built the FastAPI backend, one built the
TypeScript client. Each reported what it had built. Neither was told what to
produce, and no mismatch was planted.

The spec, both agents' output, and the checker's own JSON output are committed
under `fixtures/gate-b-session/` so this is reproducible rather than asserted.

## The result

Git merged both branches with **zero conflicts**. Of the three seams the two
agents built independently:

| seam | outcome |
|---|---|
| `POST /orders` | agreed: `email`, `amount_cents`, JSON |
| `POST /orders/{}/receipt` | agreed: multipart, part named `file` |
| `PUT /profile` | **mismatch** |

```
PUT /profile
  where                  PASS   server backend/app/routers/profile.py:11
                              |  client frontend/src/api/profile.ts:16
  endpoint exists        PASS
  route mounted          PASS
  client calls it        PASS
  encoding matches       PASS
  payload shape matches  FAIL   server requires `marketing_emails` (bool);
                                client sends ['display_name', 'marketing_opt_in']
```

The two declarations:

```python
class ProfileUpdateRequest(BaseModel):        # backend agent
    display_name: str = Field(min_length=1, max_length=100)
    marketing_emails: bool
```

```ts
export interface UpdateProfileRequest {       // frontend agent
  display_name: string;
  marketing_opt_in: boolean;
}
```

The spec said only "their marketing email preference (on or off)". Each agent
chose a reasonable name. Neither is wrong alone. Together they are broken, both
sides compile, and git merges them clean.

**One mismatch in three features, not three in three.** That matters: a spec
rigged to guarantee divergence would have produced three, and this one did not.
Two seams matched exactly, including the multipart part name, which the agents
agreed on with no coordination at all.

## The correction the premise needs

The pitch says both agents finish and report success truthfully, and the gap
belongs to nobody.

That is not what happened. The frontend agent did **not** report unqualified
success. It listed every field it had invented, stated plainly that none of the
contract came from the spec, put the odds of all three features interoperating
at under 20%, named the specific places it expected to diverge, and asked for a
shared contract before anyone wired the halves together.

So for a capable agent given a bare spec, "both report success" is too strong.
The gap was real, it merged clean, and it was invisible to every other signal in
the toolchain, but one of the two agents did flag it. The honest version of the
claim is that the mismatch survives the merge and every automated check, not
that neither agent suspects anything.

## What the experiment exposed in the checker itself

Irus found **nothing at all** on the first run. Every route reported "client
absent". Four defects, each visible only because the code was agent-written
rather than written by us:

1. **Neither agent wrote an inline `fetch`.** The frontend agent wrote a shared
   `sendJson(method, path, body)` helper and called it from every feature, so
   the entire contract lived at the call site. The scanner only read `fetch(`.
   It now follows one hop through a project-local wrapper. One hop deliberately:
   deeper chains multiply the chance of attributing a body to the wrong request.
2. **Every request became a `GET`.** The wrapper used ES6 shorthand
   `{ method, headers }` and only `method: method` was matched.
3. **Every endpoint looked like it took no body.** The Pydantic models live in
   `schemas.py` and the handlers in `routers/`, and the model registry was
   per-file. Every real FastAPI project splits those.
4. **A patch script reported success while changing nothing**, caught only
   because the behaviour did not change.

Without those four fixes the answer to Gate B would have been a false negative:
the mismatch was there the whole time and the tool could not see it.

## Limits of this evidence

- **Two Claude subagents on one machine, not two vendors on two laptops.** The
  mechanism under test is faithfully reproduced, which is two agents with
  isolated context building two halves of one underspecified feature. The vendor
  diversity is not.
- **One session, three features, one mismatch.** That is enough to answer "does
  this ever catch something real" and nowhere near enough to estimate a rate.
- **The spec was written by us**, though deliberately not written to cause a
  collision, and two of three features did not collide.
