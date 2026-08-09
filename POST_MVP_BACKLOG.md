# Post-MVP backlog

Different in kind from `BACKLOG.md`: that file holds refinements already scoped to fit this project's current shape (a local, single-operator demo tool). This file holds bigger-picture ideas that would only make sense if the project's scope grew toward something closer to production/multi-session use — not scheduled, not necessarily desirable given the project's actual goals, kept for posterity so a real idea raised in conversation doesn't just evaporate.

Nothing here should drive current build-order work. Check `BACKLOG.md` and `CLAUDE.md` for what's actually in flight.

---

## Frontend / connection handling

Raised 2026-08-09 while scoping Phase 9c's toast design (`CLAUDE.md`'s Phase 9c section).

- [ ] **1. Missed-events indicator on WebSocket reconnect.** 9c's toasts fire from diffing consecutive *live* `TickRecord`s — an event that both fires and resolves while the frontend is disconnected produces no toast, only a row in the decision log once backlog is refetched via `GET /state`. Decided this is correct scope for an MVP demo tool (toasts are a "notice this now" affordance per the design brief's own framing, not a notification inbox; the decision log is the durable record; the status pill already surfaces anything still-active on reconnect). The idea considered and deferred: rather than replaying a toast per missed event (noisy, and misleadingly implies the event just happened), show a single small "N events occurred while disconnected — see log" indicator, computed by diffing the backlog's severity-relevant fields across the gap on reconnect. Would matter more if this ever became a tool people leave running unattended and check back on later, rather than a live-watched demo.

---

## Detector / interlock tuning

Raised 2026-08-09, while chasing a live bug report against the 9c frontend (a PID/Manual session that got stuck permanently reporting "sensor untrusted" after `reset_interlock()`, with no fault actually injected).

- [ ] **2. Revisit `engine/detector.py` + `engine/interlock.py` tuning more broadly — performance vs. safety trade-off, not a one-off parameter tweak.** Root-caused the immediate bug: a severe temperature excursion (~80°C, from a heater pinned at 100% until a hard-trip lockout) produces a real, sustained cooldown that the Tier-1 CUSUM detector statistically can't distinguish from sensor drift — same class of false positive `engine/detector.py`'s own docstring already documents for a startup ramp. Shipped a scoped, user-approved fix for the narrow trigger (`reset_interlock()` giving the detector a short `reset_grace_ticks` settle window instead of zero — see `CLAUDE.md`), but direct measurement against the real engine showed it only delays the false flag, not prevents it, for excursions this large: comparing grace=0 vs. grace=10 vs. grace=50 against the same seeded scenario, the flag *cleared at the identical tick (249) regardless of grace* — because CUSUM saturates at its cap (`CUSUM_CAP_MULTIPLIER * cusum_threshold_h`, currently 2.0x) almost immediately for a swing this size, and recovery time from a saturated cap is physics-determined (how fast the plant naturally decelerates), not grace-determined. Grace only changed how many ticks were flagged before that fixed clearing point.
  - The narrower lever available (shrinking `CUSUM_CAP_MULTIPLIER` for faster recovery from *any* saturated CUSUM state) was identified but deliberately not pulled — it changes detector sensitivity broadly, not just for this trigger, and needed its own evaluation the user chose to defer.
  - User's framing on deferring further: this isn't really a single-parameter fix, it's a prompt to revisit the whole detector/interlock tuning (`window_ticks`, `z_score_threshold`, `cusum_slack_k`, `cusum_threshold_h`, `stuck_variance_ratio`, `boot_grace_ticks`, `reset_grace_ticks`, `CUSUM_CAP_MULTIPLIER`, `bound_margin_k`, `trip_lockout_threshold`, etc.) as a system, evaluating real detection performance (false-positive rate under legitimate fast transients like a hard-trip cooldown, not just synthetic fault scenarios) against the safety guarantees those parameters exist to provide. Empirical, closed-loop tuning across a range of realistic scenarios, not one-off patches reacting to whichever false positive was most recently reported live.
