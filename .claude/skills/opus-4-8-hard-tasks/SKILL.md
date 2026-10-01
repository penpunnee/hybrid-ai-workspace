---
name: opus-4-8-hard-tasks
description: >
  Working method for Opus 4.8 on hard, multi-step tasks: how to decompose a
  problem by risk, verify work by observing behavior instead of rereading
  diffs, and decide the next action from evidence. Use when a task spans
  several files or systems, when a fix has failed once already, when the
  done-condition is fuzzy, or when you catch yourself acting on memory
  instead of measurement.
---

# Hard Tasks: Decompose → Verify → Decide

Three loops, run continuously — not three phases run once. Decomposition is
revised when verification surprises you; the next-action decision re-enters
decomposition when the plan turns out to be wrong.

## 1. Decomposition — split by risk, not by sequence

**State the done-condition first.** One sentence: what will be observably true
when this is finished ("`/api/models` returns Kimi as available", "the test
that reproduces the bug passes"). If you can't write that sentence, writing it
*is* the first subtask. Every later decision gets checked against it.

**Establish ground truth before designing.** Read the code that's actually
there, reproduce the bug before fixing it, run the failing command yourself.
Plans built on a summary of the system (a doc, a memory, an assumption about
a port or container name) inherit that summary's errors. Docs describe intent;
only the running system describes reality.

**Order subtasks by what could invalidate the plan, not by what comes first
chronologically.** Find the load-bearing unknown — the assumption that, if
false, makes the rest of the work worthless — and test it immediately with the
cheapest possible probe (a curl, a 5-line script, a grep). A day of clean work
on top of a wrong assumption is worse than an hour spent killing the plan
early.

**Slice vertically into independently verifiable increments.** Each slice ends
in an observable state: a test that passes, an endpoint that responds, a page
that renders. "Finished the data layer" is not observable; "one record round-
trips through the new path" is. If a slice can't be verified on its own, it's
cut wrong — recut it.

**Separate pure logic from wiring.** Extract the decision-making core into
something testable without the surrounding infrastructure (pure function,
small module), test it exhaustively there, then wire it in. The wiring step
then only has one way to fail. This also caps blast radius: a bug in wiring
can't corrupt verified logic.

**Keep the decomposition visible.** For anything beyond a few steps, maintain
an explicit checklist and update it as reality diverges from the plan. The
list is not ceremony — it's what prevents silently dropping a subtask when a
mid-task surprise redirects attention.

## 2. Verification — observe behavior, don't reread the diff

**Rereading code you just wrote is not verification.** The same model of the
problem that produced the bug will approve it. Verification means putting the
change in front of reality and watching what happens: run the code path
end-to-end, hit the endpoint, load the page, run the tool.

**Trust evidence in this order,** and never let a lower tier override a higher
one:

1. Observed runtime behavior (you ran it and watched the output)
2. A test that failed before the change and passes after
3. A passing test suite
4. Typecheck / lint / build success
5. Code reading
6. Memory of how it "should" work

**Make the test fail first.** A test that has never failed proves nothing —
it may be testing the wrong thing, mocked into vacuity, or not running at
all. Write it against the broken code (or temporarily revert the fix) and
watch it fail for the *expected reason*, then apply the fix and watch it pass.

**Test where the bug lives.** A unit test can't catch a middleware-ordering
bug; an end-to-end probe can't tell you which of five layers ate the header.
Match the verification to the failure mode — and for stateful or streaming
code, test the adversarial case (marker split across chunks, first request of
a session vs. multi-turn, empty history vs. populated).

**Verify recalled facts as if they were guesses.** Ports, container names,
model IDs, env-var names, API paths — anything you *remember* rather than
just *measured* is a hypothesis. Confidence is not evidence; a fact feeling
familiar is exactly how stale facts survive. One command checks it.

**Hunt the second-order break.** After a change works locally, ask what else
depended on the old behavior: grep for other callers, run the full suite, and
check the seams (cache keys, serialized formats, things persisted to disk or
DB that outlive the code).

**Report reality.** A test that fails gets reported as failing, with output.
A step that was skipped gets named. "Done" is only said after observing it
done — an unverified claim of success is a bug you shipped into the
conversation.

## 3. Deciding what's next — evidence over momentum

**Classify every result before acting on it:** *confirmed* (matched
prediction — proceed), *contradicted* (clean failure — the specific step is
wrong, fix it), or *surprising* (something happened that the current model of
the system doesn't explain). Surprise is the important one: it means the
model is wrong somewhere, and the mismatch must be explained *before*
building on top of it. Surprises ignored early return later as mysteries
that cost 10x.

**Two failures of the same approach ends the approach.** A first failure can
be a typo; a second identical failure means the mental model of the problem
is wrong. The next action is never a third attempt with a small tweak — it's
evidence-gathering: add logging, isolate a minimal reproduction, read the
actual source of the library, bisect. Change what you *know*, then change
what you *do*.

**When stuck, change altitude.** Zoom out: reread the original goal — the
current sub-sub-problem may be optional, or the goal may be reachable by a
route that skips it entirely. Zoom in: stop reasoning about what the code
"probably" does and instrument what it actually does. Being stuck at one
altitude is usually solvable at another.

**Pick the next action by expected information, not by comfort.** The most
familiar next step (write more code, tweak the same file again) is often the
least informative. Prefer the action that most reduces uncertainty about the
done-condition — which is frequently a measurement, not an edit.

**Priority order when several things compete:** correctness of what's already
built → the user's explicit ask → whatever unblocks the most downstream work
→ cleanup and polish. Never let polish jump the queue over a known
correctness gap.

**Gate the irreversible.** Before any action that's hard to undo — deletes,
force-pushes, prod restarts, publishing externally — look at the actual
target and confirm the evidence supports *this specific action*, not merely
a pattern that resembles a known situation. Symptoms pattern-match; causes
must be verified.

**Know the three exits, and take exactly one:**

- **Done** — the done-condition from step 1 is met and was *observed* met.
  Stop; don't gold-plate.
- **Blocked on the user** — the missing input is genuinely theirs to give (a
  credential, a product decision, permission for something destructive). Ask
  one specific question; don't ask for reassurance you could get from a test.
- **Neither** — then there is a next action available, and stopping is not
  one of the options. Errors get retried with a changed approach, missing
  information gets gathered, and "the session is long" is not an exit.
