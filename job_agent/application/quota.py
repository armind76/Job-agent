"""
Graphics computing quota: guarantee a minimum percentage of application slots
go to Tier-3 (graphics / GPU / HPC) jobs.

Default is 10%. Jobs are interleaved so graphics picks appear throughout
the review queue rather than being bunched at the end.
"""
import math
from typing import Sequence

from job_agent.db.models import Job

GRAPHICS_TIER = 3
DEFAULT_GRAPHICS_PCT = 0.10


def select_with_graphics_quota(
    jobs: Sequence[Job],
    limit: int,
    graphics_pct: float = DEFAULT_GRAPHICS_PCT,
) -> list[Job]:
    """
    Return up to `limit` jobs from `jobs`, guaranteeing that at least
    `graphics_pct` of the selected slots are Tier-3 graphics/GPU jobs
    (when enough Tier-3 jobs are available).

    Within each bucket jobs are ordered: lowest tier first, highest score first.
    The two buckets are then interleaved so graphics jobs appear every ~N positions
    instead of all at the end.

    Edge cases:
    - Fewer Tier-3 jobs than the quota requires → use all of them, fill
      remaining slots with other jobs (quota is best-effort).
    - No Tier-3 jobs at all → return highest-priority other jobs unchanged.
    - `graphics_pct` of 0 → no Tier-3 enforcement (all slots go to others).
    """
    if limit <= 0:
        return []

    tier3 = [j for j in jobs if j.priority_tier == GRAPHICS_TIER]
    others = [j for j in jobs if j.priority_tier != GRAPHICS_TIER]

    def _rank(j: Job) -> tuple:
        return (j.priority_tier or 4, -(j.priority_score or 0.0))

    tier3 = sorted(tier3, key=_rank)
    others = sorted(others, key=_rank)

    # How many slots go to graphics?
    n_graphics = math.ceil(limit * graphics_pct) if (tier3 and graphics_pct > 0) else 0
    n_graphics = min(n_graphics, len(tier3))      # can't exceed what exists
    n_others = min(limit - n_graphics, len(others))

    pool_t3 = tier3[:n_graphics]
    pool_ot = others[:n_others]

    if not pool_t3:
        return pool_ot[:limit]

    # Interleave: after every `every_n` other jobs, inject one Tier-3 job.
    # For 10%: every 9 other jobs → 1 graphics = 10% of total.
    other_frac = 1.0 - graphics_pct
    every_n = max(1, round(other_frac / graphics_pct))  # 9 for 10%

    result: list[Job] = []
    t3_iter = iter(pool_t3)
    since_last_injection = 0

    for job in pool_ot:
        result.append(job)
        since_last_injection += 1
        if since_last_injection >= every_n:
            nxt = next(t3_iter, None)
            if nxt is not None:
                result.append(nxt)
                since_last_injection = 0

    # Drain any remaining Tier-3 slots (if others ran out first)
    for j in t3_iter:
        result.append(j)

    return result[:limit]


def quota_summary(jobs: list[Job]) -> str:
    """Return a one-line string describing the graphics quota in a job list."""
    total = len(jobs)
    if total == 0:
        return "0 jobs selected"
    n_t3 = sum(1 for j in jobs if j.priority_tier == GRAPHICS_TIER)
    pct = n_t3 / total * 100
    return f"{total} jobs ({n_t3} graphics/GPU = {pct:.0f}%)"
