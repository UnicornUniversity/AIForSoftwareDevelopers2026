"""Eurojackpot historical draw analysis.

Standard library only -- no third-party imports. This module is the single source of
truth for every number reported in the deliverables: the Markdown write-up, the
Jupyter notebook and the two D3 pages all read what this produces, so they cannot
silently disagree with each other.

Usage:
    python analysis.py [path/to/eurojackpot.csv] [--out stats.json]
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import itertools
import json
import math
import random
import statistics
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

# --------------------------------------------------------------------------------------
# Game rules and the era boundary
# --------------------------------------------------------------------------------------

SET1_SIZE, SET1_UNIVERSE = 5, 50
SET2_SIZE, SET2_UNIVERSE = 2, 12

# Eurojackpot changed on 2022-03-25: the second set went from 1-10 to 1-12 and the draw
# cadence doubled from weekly (Fridays) to twice weekly (Tuesdays and Fridays). Both
# changes are visible in this file and both corrupt naive whole-history statistics.
ERA_B_START = dt.date(2022, 3, 25)

# The universe of Set #2 before the change. Used so Era A is scored on its own terms.
SET2_UNIVERSE_ERA_A = 10


@dataclass(frozen=True)
class Draw:
    date: dt.date
    year: int  # the file's `rok` column -- an ISO *week-year*, not the calendar year
    week: int
    set1: tuple[int, ...]
    set2: tuple[int, ...]
    era: str  # "A" or "B"

    @property
    def calendar_year(self) -> int:
        """The calendar year, taken from the date.

        `rok` is the ISO week-year, so it disagrees with the calendar year for draws in
        the first/last days of a year -- 4 rows here, e.g. `30. 12. 2025` is tagged
        `2026` because it falls in ISO week 1 of 2026. Grouping by `rok` would silently
        move those draws into the wrong year, so calendar analysis uses this.
        """
        return self.date.year


# --------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------


def parse_czech_date(text: str) -> dt.date:
    """Parse the file's `12. 5. 2026` (day. month. year.) format."""
    parts = [p.strip() for p in text.split(".")]
    if len(parts) != 3:
        raise ValueError(f"unrecognised date: {text!r}")
    day, month, year = (int(p) for p in parts)
    return dt.date(year, month, day)


def load_draws(path: str | Path) -> list[Draw]:
    """Read the CSV and return draws sorted oldest-first.

    Four details matter here and are easy to get wrong:

    * the file is semicolon-delimited, not comma-delimited;
    * dates are Czech ``d. m. yyyy``, not ISO;
    * rows are stored *newest first*, so we sort ascending. Skipping this silently
      inverts every recency and gap calculation downstream;
    * there is in fact **no** BOM in this file (the first bytes are ``datum;``), but we
      open with ``utf-8-sig`` anyway -- it strips a BOM if one is ever added and is a
      no-op otherwise.
    """
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for raw in csv.reader(fh, delimiter=";"):
            if not any(cell.strip() for cell in raw):
                continue  # blank line
            rows.append(raw)

    if not rows:
        raise ValueError(f"{path}: file is empty")

    header, body = rows[0], rows[1:]
    if "osudi" not in ";".join(header):
        raise ValueError(f"{path}: unexpected header {header!r}")

    draws: list[Draw] = []
    for lineno, row in enumerate(body, start=2):
        if len(row) < 10:
            raise ValueError(f"{path}:{lineno}: expected 10 fields, got {len(row)}")
        date = parse_czech_date(row[0])
        set1 = tuple(int(x) for x in row[3:8])
        set2 = tuple(int(x) for x in row[8:10])
        draws.append(
            Draw(
                date=date,
                year=int(row[1]),
                week=int(row[2]),
                set1=set1,
                set2=set2,
                era="B" if date >= ERA_B_START else "A",
            )
        )

    draws.sort(key=lambda d: d.date)
    return draws


# --------------------------------------------------------------------------------------
# Chi-square goodness of fit (no scipy available -- implemented from scratch)
# --------------------------------------------------------------------------------------


def _gamma_series(a: float, x: float, itmax: int = 500, eps: float = 1e-14) -> float:
    """Regularised lower incomplete gamma P(a, x) by series expansion."""
    ap, total, delta = a, 1.0 / a, 1.0 / a
    for _ in range(itmax):
        ap += 1.0
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * eps:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_cf(a: float, x: float, itmax: int = 500, eps: float = 1e-14) -> float:
    """Regularised upper incomplete gamma Q(a, x) by continued fraction."""
    tiny = 1e-300
    b, c, d = x + 1.0 - a, 1.0 / tiny, 1.0 / (x + 1.0 - a)
    h = d
    for i in range(1, itmax + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        step = d * c
        h *= step
        if abs(step - 1.0) < eps:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def chi2_sf(x: float, df: int) -> float:
    """Upper-tail probability P(X^2 > x) -- i.e. the p-value -- for `df` d.o.f."""
    if x <= 0 or df <= 0:
        return 1.0
    a, xx = df / 2.0, x / 2.0
    return 1.0 - _gamma_series(a, xx) if xx < a + 1.0 else _gamma_cf(a, xx)


def chi2_critical(df: int, alpha: float = 0.05) -> float:
    """Critical value of chi-square at `alpha`, found by bisecting `chi2_sf`."""
    lo, hi = 0.0, 10.0
    while chi2_sf(hi, df) > alpha:
        hi *= 2.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if chi2_sf(mid, df) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def chi_square(counts: collections.Counter, universe: int, n_observations: int) -> dict:
    """Goodness of fit against a uniform distribution over ``1..universe``.

    Zero-count categories are included deliberately: dropping them would shrink the
    degrees of freedom and overstate significance.
    """
    expected = n_observations / universe
    observed = [counts.get(i, 0) for i in range(1, universe + 1)]
    statistic = sum((o - expected) ** 2 / expected for o in observed)
    df = universe - 1
    p = chi2_sf(statistic, df)
    return {
        "statistic": statistic,
        "df": df,
        "p_value": p,
        "p_value_str": format_p(p),
        "critical_05": chi2_critical(df),
        "expected": expected,
        "n": n_observations,
        "universe": universe,
        "uniform_at_05": statistic <= chi2_critical(df),
    }


def format_p(p: float) -> str:
    """Format a p-value for prose.

    The pooled Set #2 test is so extreme that the incomplete-gamma evaluation
    underflows to exactly 0.0. Reporting "p = 0" would be wrong, so anything below
    1e-12 is shown as a bound instead.
    """
    if p < 1e-12:
        return "< 1e-12"
    if p < 1e-4:
        return f"{p:.2e}"
    return f"{p:.3f}"


# --------------------------------------------------------------------------------------
# Descriptive statistics
# --------------------------------------------------------------------------------------


def all_numbers(draws: list[Draw], which: str) -> list[int]:
    return [n for d in draws for n in getattr(d, which)]


def frequency(numbers: list[int]) -> collections.Counter:
    return collections.Counter(numbers)


def gap_stats(draws: list[Draw], which: str, universe: int) -> dict[int, dict]:
    """Per number: appearances, mean/max gap between appearances, current drought.

    "Gap" is counted in draws, not days -- the draw cadence doubles inside this file,
    so day counts would not be comparable across the whole history.
    """
    occurrences: dict[int, list[int]] = {n: [] for n in range(1, universe + 1)}
    for idx, draw in enumerate(draws):
        for n in getattr(draw, which):
            occurrences[n].append(idx)

    last_index = len(draws) - 1
    out: dict[int, dict] = {}
    for n, idxs in occurrences.items():
        if len(idxs) >= 2:
            diffs = [b - a for a, b in zip(idxs, idxs[1:])]
            mean_gap = statistics.fmean(diffs)
            max_gap = max(diffs)
        else:
            mean_gap = max_gap = float(len(draws))
        drought = last_index - idxs[-1] if idxs else len(draws)
        expected_gap = len(draws) / len(idxs) if idxs else float("inf")
        out[n] = {
            "count": len(idxs),
            "mean_gap": mean_gap,
            "max_gap": max_gap,
            "drought": drought,
            "expected_gap": expected_gap,
            "last_seen": str(draws[idxs[-1]].date) if idxs else None,
        }
    return out


def positional_frequency(draws: list[Draw]) -> list[collections.Counter]:
    """Frequency by *column* within Set #1.

    This is only meaningful because the CSV does not store Set #1 sorted -- the
    ``N. cislo`` column is the order the balls came out. If a future revision of the
    file sorts the rows, this analysis becomes meaningless.
    """
    cols = [collections.Counter() for _ in range(SET1_SIZE)]
    for draw in draws:
        for i, n in enumerate(draw.set1):
            cols[i][n] += 1
    return cols


def cooccurrence(draws: list[Draw], which: str, universe: int) -> collections.Counter:
    pairs: collections.Counter = collections.Counter()
    for draw in draws:
        nums = sorted(getattr(draw, which))
        for i, a in enumerate(nums):
            for b in nums[i + 1 :]:
                pairs[(a, b)] += 1
    return pairs


def top_pairs(pairs: collections.Counter, k: int = 10) -> list[dict]:
    return [{"a": a, "b": b, "count": c} for (a, b), c in pairs.most_common(k)]


def cooccurrence_summary(draws: list[Draw], which: str, universe: int) -> dict:
    """Pair-level view: how many of the C(universe, 2) pairs were ever seen at all.

    With ~1,200 pairs on screen at once, a "most common pair" list is rank-order noise:
    at alpha = 0.05 you expect ~5% of the pairs to look significant by chance alone. Both
    numbers are reported so the multiplicity is visible rather than implied.
    """
    pairs = cooccurrence(draws, which, universe)
    size = SET1_SIZE if which == "set1" else SET2_SIZE
    n_pairs = math.comb(universe, 2)
    return {
        "draws": len(draws),
        "possible_pairs": n_pairs,
        "pairs_seen": len(pairs),
        "pairs_never_seen": n_pairs - len(pairs),
        # P(a given pair is in one draw) = (size/universe) * ((size-1)/(universe-1)).
        "expected_per_pair": len(draws) * (size / universe) * ((size - 1) / (universe - 1)),
        "expected_false_positives_at_05": 0.05 * n_pairs,
        "top": top_pairs(pairs, 5),
    }


def parity_decade(draws: list[Draw], universe: int) -> dict:
    numbers = all_numbers(draws, "set1")
    odd = sum(1 for n in numbers if n % 2)
    decade = collections.Counter((n - 1) // 10 for n in numbers)
    return {
        "odd": odd,
        "even": len(numbers) - odd,
        "decades": [
            {"label": f"{d * 10 + 1}-{d * 10 + 10}", "count": decade.get(d, 0)}
            for d in range(universe // 10)
        ],
    }


def yearly_drift(draws: list[Draw]) -> list[dict]:
    by_year: dict[int, list[Draw]] = collections.defaultdict(list)
    for d in draws:
        by_year[d.calendar_year].append(d)  # calendar year, not the ISO week-year in `rok`
    out = []
    for year in sorted(by_year):
        ds = by_year[year]
        s2 = all_numbers(ds, "set2")
        out.append(
            {
                "year": year,
                "draws": len(ds),
                "set2_universe": max(s2) if s2 else 0,
                "first": str(ds[0].date),
                "last": str(ds[-1].date),
                "partial": len(ds) < 100,
            }
        )
    return out


def has_adjacent_pair(nums: tuple[int, ...] | list[int]) -> bool:
    ordered = sorted(nums)
    return any(b - a == 1 for a, b in zip(ordered, ordered[1:]))


def adjacency(draws: list[Draw]) -> dict:
    """How often a draw contains two consecutive numbers, against the exact rate.

    The exact figure is enumerated over all C(50, 5) combinations rather than
    simulated, so there is no Monte-Carlo error in the comparison.
    """
    observed = sum(1 for d in draws if has_adjacent_pair(d.set1))
    total = math.comb(SET1_UNIVERSE, SET1_SIZE)
    exact = sum(
        1
        for combo in itertools.combinations(range(1, SET1_UNIVERSE + 1), SET1_SIZE)
        if has_adjacent_pair(combo)
    )
    return {
        "observed": observed,
        "draws": len(draws),
        "observed_rate": observed / len(draws),
        "exact_rate": exact / total,
        "exact_count": exact,
        "combinations": total,
    }


def consecutive_overlap(draws: list[Draw], which: str = "set1") -> dict:
    """Mean numbers shared between back-to-back draws -- a direct independence check."""
    overlaps = [
        len(set(getattr(a, which)) & set(getattr(b, which)))
        for a, b in zip(draws, draws[1:])
    ]
    size = SET1_SIZE if which == "set1" else SET2_SIZE
    universe = SET1_UNIVERSE if which == "set1" else SET2_UNIVERSE
    return {
        "mean": statistics.fmean(overlaps),
        "expected": size * size / universe,
        "pairs": len(overlaps),
        "max": max(overlaps),
    }


def jackpot_odds() -> dict:
    lines = math.comb(SET1_UNIVERSE, SET1_SIZE) * math.comb(SET2_UNIVERSE, SET2_SIZE)
    return {"lines": lines, "set1_combinations": math.comb(SET1_UNIVERSE, SET1_SIZE),
            "set2_combinations": math.comb(SET2_UNIVERSE, SET2_SIZE)}


# --------------------------------------------------------------------------------------
# The predictive model
# --------------------------------------------------------------------------------------

# Weights are a documented judgement call, not fitted. They are reported in the
# write-up along with the note that the backtest verdict does not depend on them.
MODEL_WEIGHTS = {"frequency": 0.4, "recency": 0.3, "gap_ratio": 0.3}


def ensemble_scores(
    draws: list[Draw],
    which: str,
    universe: int,
    size: int,
    weights: dict[str, float] | None = None,
) -> dict[int, float]:
    """Blend three weak, partly overlapping signals into one score per number.

    * ``frequency``  -- normalised appearance count (the "hot number" story)
    * ``recency``    -- normalised draws-since-last-seen (the "due number" story)
    * ``gap_ratio``  -- current drought divided by that number's own mean gap
    """
    weights = weights or MODEL_WEIGHTS
    gaps = gap_stats(draws, which, universe)
    counts = {n: gaps[n]["count"] for n in range(1, universe + 1)}

    max_count = max(counts.values()) or 1
    max_drought = max(gaps[n]["drought"] for n in gaps) or 1

    scores = {}
    for n in range(1, universe + 1):
        freq = counts[n] / max_count
        recency = gaps[n]["drought"] / max_drought
        mean_gap = gaps[n]["mean_gap"] or 1.0
        gap_ratio = min(gaps[n]["drought"] / mean_gap, 3.0) / 3.0
        scores[n] = (
            weights["frequency"] * freq
            + weights["recency"] * recency
            + weights["gap_ratio"] * gap_ratio
        )
    return scores


def weighted_sample_without_replacement(
    scores: dict[int, float], size: int, rng: random.Random, floor: float = 1e-6
) -> list[int]:
    """Sample `size` distinct numbers, favouring higher scores. Used to build a line."""
    pool = {n: max(s, floor) for n, s in scores.items()}
    chosen: list[int] = []
    for _ in range(size):
        total = sum(pool.values())
        pick = rng.random() * total
        acc = 0.0
        for n in sorted(pool):
            acc += pool[n]
            if acc >= pick:
                chosen.append(n)
                del pool[n]
                break
        else:  # pragma: no cover - floating point edge
            chosen.append(max(pool, key=pool.get))
            del pool[chosen[-1]]
    return sorted(chosen)


def backtest(
    draws: list[Draw],
    which: str = "set1",
    universe: int = SET1_UNIVERSE,
    size: int = SET1_SIZE,
    n_targets: int = 120,
    lines_per_target: int = 60,
    seed: int = 20260512,
) -> dict:
    """Walk-forward check of whether the model has any real edge.

    For each target draw, scores are fitted on *strictly earlier* draws only, then
    `lines_per_target` candidate lines are generated and matched against the actual
    result. The same number of uniformly random lines is scored on the same targets
    as a control. The analytic expectation for a random 5-from-50 line is
    ``5 * 5/50 = 0.5`` matched numbers.
    """
    rng = random.Random(seed)
    start = max(len(draws) - n_targets, universe)
    model_matches, random_matches = [], []

    for t in range(start, len(draws)):
        history, actual = draws[:t], set(getattr(draws[t], which))
        scores = ensemble_scores(history, which, universe, size)

        for _ in range(lines_per_target):
            line = weighted_sample_without_replacement(scores, size, rng)
            model_matches.append(len(set(line) & actual))

        for _ in range(lines_per_target):
            line = rng.sample(range(1, universe + 1), size)
            random_matches.append(len(set(line) & actual))

    analytic = size * size / universe

    def summarise(values: list[int]) -> dict:
        mean = statistics.fmean(values)
        sd = statistics.pstdev(values)
        stderr = sd / math.sqrt(len(values))
        return {
            "mean_matched": mean,
            "sd": sd,
            "stderr": stderr,
            "ci95_low": mean - 1.96 * stderr,
            "ci95_high": mean + 1.96 * stderr,
            "n_lines": len(values),
            "distribution": {str(k): values.count(k) for k in sorted(set(values))},
        }

    model_sum, random_sum = summarise(model_matches), summarise(random_matches)
    diff = model_sum["mean_matched"] - random_sum["mean_matched"]
    # Standard error of the difference of two independent means.
    se_diff = math.sqrt(model_sum["stderr"] ** 2 + random_sum["stderr"] ** 2)
    z = diff / se_diff if se_diff else 0.0
    p = math.erfc(abs(z) / math.sqrt(2.0))
    beats_random = p < 0.05 and diff > 0

    return {
        "targets": len(draws) - start,
        "lines_per_target": lines_per_target,
        "analytic_expectation": analytic,
        "model": model_sum,
        "random_baseline": random_sum,
        "difference": diff,
        "z": z,
        "p_value": p,
        "beats_random": beats_random,
        "conclusion": (
            "The model matches no more numbers than chance; it has no predictive edge."
            if not beats_random
            else "The model beat the random baseline on this sample -- investigate before trusting it."
        ),
    }


# --------------------------------------------------------------------------------------
# Assembling the report
# --------------------------------------------------------------------------------------


def build_view(draws: list[Draw], label: str, note: str, set2_universe: int) -> dict:
    s1, s2 = all_numbers(draws, "set1"), all_numbers(draws, "set2")
    c1, c2 = frequency(s1), frequency(s2)

    def cells(counter: collections.Counter, universe: int) -> list[dict]:
        ranked = {
            n: rank
            for rank, (n, _) in enumerate(
                sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])), start=1
            )
        }
        return [
            {"n": n, "count": counter.get(n, 0), "rank": ranked.get(n, 0)}
            for n in range(1, universe + 1)
        ]

    top5 = [{"n": n, "count": c} for n, c in sorted(c1.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]
    top2 = [{"n": n, "count": c} for n, c in sorted(c2.items(), key=lambda kv: (-kv[1], kv[0]))[:2]]
    bottom5 = [{"n": n, "count": c} for n, c in sorted(c1.items(), key=lambda kv: (kv[1], kv[0]))[:5]]

    return {
        "label": label,
        "note": note,
        "draws": len(draws),
        "first": str(draws[0].date),
        "last": str(draws[-1].date),
        "set1": {
            "universe": SET1_UNIVERSE,
            "size": SET1_SIZE,
            "cells": cells(c1, SET1_UNIVERSE),
            "expected": len(s1) / SET1_UNIVERSE,
            "top5": top5,
            "bottom5": bottom5,
            "min": min(c1.values()),
            "max": max(c1.values()),
        },
        "set2": {
            "universe": set2_universe,
            "size": SET2_SIZE,
            "cells": cells(c2, set2_universe),
            "expected": len(s2) / set2_universe,
            "top2": top2,
            "min": min(c2.values()),
            "max": max(c2.values()),
        },
    }


def build_report(draws: list[Draw]) -> dict:
    era_a = [d for d in draws if d.era == "A"]
    era_b = [d for d in draws if d.era == "B"]

    sets = {}
    for name, subset, s2_universe in (
        ("full", draws, SET2_UNIVERSE),
        ("era_a", era_a, SET2_UNIVERSE_ERA_A),
        ("era_b", era_b, SET2_UNIVERSE),
    ):
        s1, s2 = all_numbers(subset, "set1"), all_numbers(subset, "set2")
        sets[name] = {
            "chi2_set1": chi_square(frequency(s1), SET1_UNIVERSE, len(s1)),
            "chi2_set2": chi_square(frequency(s2), s2_universe, len(s2)),
        }

    ordered = sorted(draws, key=lambda d: d.date)
    return {
        "meta": {
            "source": "eurojackpot.csv",
            "draws": len(draws),
            "first_draw": str(ordered[0].date),
            "last_draw": str(ordered[-1].date),
            "years": sorted({d.year for d in draws}),
            "set1_universe": SET1_UNIVERSE,
            "set2_universe": SET2_UNIVERSE,
            "era_boundary": str(ERA_B_START),
            # `rok` is the ISO week-year, not the calendar year -- these rows prove it.
            "week_year_mismatches": [
                {"date": str(d.date), "rok": d.year, "calendar_year": d.calendar_year}
                for d in draws
                if d.year != d.calendar_year
            ],
        },
        "eras": {
            "a": {"draws": len(era_a), "first": str(era_a[0].date), "last": str(era_a[-1].date)},
            "b": {"draws": len(era_b), "first": str(era_b[0].date), "last": str(era_b[-1].date)},
        },
        "views": {
            "era_b": build_view(
                era_b,
                "Current rules (from 25 Mar 2022)",
                "Set #2 drawn from 1-12, twice-weekly draws.",
                SET2_UNIVERSE,
            ),
            "full": build_view(
                draws,
                "Full history (2014-2026)",
                "Spans a rule change: Set #2 was 1-10 before 25 Mar 2022, so 11 and 12 "
                "look artificially cold here.",
                SET2_UNIVERSE,
            ),
        },
        "chi2": sets,
        "gaps": {
            "era_b_set1": gap_stats(era_b, "set1", SET1_UNIVERSE),
            "era_b_set2": gap_stats(era_b, "set2", SET2_UNIVERSE),
        },
        "positional_set1_full": [
            {
                "position": i + 1,
                "top": [{"n": n, "count": c} for n, c in col.most_common(5)],
                "min": min(col.values()),
                "max": max(col.values()),
                "distinct": len(col),
                "chi2": chi_square(col, SET1_UNIVERSE, sum(col.values())),
            }
            for i, col in enumerate(positional_frequency(draws))
        ],
        "parity_decade": parity_decade(era_b, SET1_UNIVERSE),
        "adjacency": adjacency(draws),
        "overlap": {
            "set1_full": consecutive_overlap(draws, "set1"),
            "set1_era_b": consecutive_overlap(era_b, "set1"),
        },
        "odds": jackpot_odds(),
        "cooccurrence": {
            "era_b_set1": top_pairs(cooccurrence(era_b, "set1", SET1_UNIVERSE), 10),
            "era_b_set2": top_pairs(cooccurrence(era_b, "set2", SET2_UNIVERSE), 5),
            "full_set1": cooccurrence_summary(draws, "set1", SET1_UNIVERSE),
        },
        "yearly": yearly_drift(draws),
        "model": {
            "weights": MODEL_WEIGHTS,
            "features": ["frequency", "recency", "gap_ratio"],
            "fitted_on": "Era B only",
            "suggested_lines": None,  # filled below
        },
    }


def suggest_lines(draws: list[Draw], n_lines: int = 5, seed: int = 7) -> list[dict]:
    """Generate the headline suggested lines, seeded so the output is reproducible."""
    era_b = [d for d in draws if d.era == "B"]
    rng = random.Random(seed)
    s1 = ensemble_scores(era_b, "set1", SET1_UNIVERSE, SET1_SIZE)
    s2 = ensemble_scores(era_b, "set2", SET2_UNIVERSE, SET2_SIZE)
    return [
        {
            "set1": weighted_sample_without_replacement(s1, SET1_SIZE, rng),
            "set2": weighted_sample_without_replacement(s2, SET2_SIZE, rng),
        }
        for _ in range(n_lines)
    ]


def self_check(draws: list[Draw], report: dict) -> list[str]:
    """Assert the invariants the write-up depends on. Returns notes, raises on failure."""
    notes = []

    def expect(actual, wanted, what):
        if actual != wanted:
            raise AssertionError(f"{what}: expected {wanted}, got {actual}")
        notes.append(f"OK  {what} = {wanted}")

    expect(len(draws), 821, "draws parsed")
    expect(len(all_numbers(draws, "set1")), 4105, "Set #1 values")
    expect(len(all_numbers(draws, "set2")), 1642, "Set #2 values")
    expect(report["eras"]["a"]["draws"], 389, "Era A draws")
    expect(report["eras"]["b"]["draws"], 432, "Era B draws")

    for d in draws:
        if len(set(d.set1)) != SET1_SIZE or len(set(d.set2)) != SET2_SIZE:
            raise AssertionError(f"{d.date}: duplicate numbers within a draw")
        if not all(1 <= n <= SET1_UNIVERSE for n in d.set1):
            raise AssertionError(f"{d.date}: Set #1 out of range")
        if not all(1 <= n <= SET2_UNIVERSE for n in d.set2):
            raise AssertionError(f"{d.date}: Set #2 out of range")
    notes.append("OK  no intra-row duplicates, all values in range")

    if [d.date for d in draws] != sorted(d.date for d in draws):
        raise AssertionError("draws are not sorted oldest-first")
    notes.append("OK  draws sorted oldest-first")

    # Regression values computed during planning. If any of these move, the analysis
    # has changed and the write-up must be revisited.
    expected_chi2 = {
        ("full", "chi2_set1"): (40.74, 49),
        ("era_a", "chi2_set1"): (29.47, 49),
        ("era_b", "chi2_set1"): (47.08, 49),
        ("era_a", "chi2_set2"): (4.72, 9),
        ("era_b", "chi2_set2"): (7.94, 11),
    }
    for (view, key), (want_stat, want_df) in expected_chi2.items():
        got = report["chi2"][view][key]
        if round(got["statistic"], 2) != want_stat or got["df"] != want_df:
            raise AssertionError(
                f"chi2 {view}/{key}: expected {want_stat} (df {want_df}), "
                f"got {got['statistic']:.2f} (df {got['df']})"
            )
        if not got["uniform_at_05"]:
            raise AssertionError(f"chi2 {view}/{key}: unexpectedly rejects uniformity")
    notes.append("OK  all 5 chi-square tests match reference values (all uniform at alpha=0.05)")

    # The trap: naive Set #2 counts make 11 and 12 look dead.
    full_cells = {c["n"]: c["count"] for c in report["views"]["full"]["set2"]["cells"]}
    if (full_cells[11], full_cells[12]) != (62, 77):
        raise AssertionError(f"trap counts changed: 11={full_cells[11]}, 12={full_cells[12]}")
    notes.append("OK  naive whole-history Set #2 counts still show the 2022 artefact (11->62, 12->77)")

    # The hot five is unstable across the era boundary.
    full_top = [c["n"] for c in report["views"]["full"]["set1"]["top5"]]
    era_b_top = [c["n"] for c in report["views"]["era_b"]["set1"]["top5"]]
    if full_top != [20, 35, 11, 16, 34] or era_b_top != [11, 17, 20, 30, 13]:
        raise AssertionError(f"hot-list instability changed: {full_top} vs {era_b_top}")
    notes.append(f"OK  Set #1 top-5 unstable across eras ({full_top} vs {era_b_top})")

    # The trap, quantified: pooling the two Set #2 universes *does* reject uniformity,
    # which is exactly the false positive the era split removes.
    pooled = report["chi2"]["full"]["chi2_set2"]
    if round(pooled["statistic"], 2) != 85.42 or pooled["uniform_at_05"]:
        raise AssertionError(f"pooled Set #2 chi2 changed: {pooled['statistic']:.2f}")
    notes.append(
        f"OK  pooled Set #2 chi2 = {pooled['statistic']:.2f} (df {pooled['df']}, "
        f"p {pooled['p_value_str']}) REJECTS uniformity -- the artefact, quantified"
    )

    # Structural checks on the composition of a draw.
    adj = report["adjacency"]
    if (adj["observed"], adj["combinations"]) != (280, 2118760):
        raise AssertionError(f"adjacency changed: {adj['observed']}")
    if round(adj["exact_rate"], 4) != 0.3530:
        raise AssertionError(f"exact adjacency rate changed: {adj['exact_rate']}")
    notes.append(
        f"OK  draws containing a consecutive pair: {adj['observed']}/{adj['draws']} "
        f"= {adj['observed_rate']:.4f} vs exact {adj['exact_rate']:.4f}"
    )

    ov = report["overlap"]["set1_full"]
    if round(ov["mean"], 4) != 0.4927:
        raise AssertionError(f"consecutive overlap changed: {ov['mean']}")
    notes.append(f"OK  mean overlap between consecutive draws = {ov['mean']:.4f} (expected 0.5)")

    # Section 7 quotes the full-history pair counts, the mean gap and the longest drought.
    co = report["cooccurrence"]["full_set1"]
    if (co["pairs_seen"], co["possible_pairs"]) != (1224, 1225):
        raise AssertionError(f"co-occurrence coverage changed: {co['pairs_seen']}/{co['possible_pairs']}")
    if round(co["expected_per_pair"], 2) != 6.70:
        raise AssertionError(f"expected pairs per pair changed: {co['expected_per_pair']}")
    if (co["top"][0]["a"], co["top"][0]["b"], co["top"][0]["count"]) != (34, 49, 16):
        raise AssertionError(f"most common pair changed: {co['top'][0]}")
    notes.append(
        f"OK  Set #1 pairs seen at least once: {co['pairs_seen']}/{co['possible_pairs']} "
        f"(expected {co['expected_per_pair']:.2f} each; top pair "
        f"{co['top'][0]['a']}-{co['top'][0]['b']} x{co['top'][0]['count']}; "
        f"{co['expected_false_positives_at_05']:.1f} false positives expected at alpha=0.05)"
    )

    gaps_b = report["gaps"]["era_b_set1"]
    mean_of_means = statistics.fmean(g["mean_gap"] for g in gaps_b.values())
    if abs(mean_of_means - 10.0) > 0.05:
        raise AssertionError(f"mean gap changed: {mean_of_means}")
    worst = max(gaps_b.items(), key=lambda kv: kv[1]["drought"])
    if (worst[0], worst[1]["drought"]) != (24, 40):
        raise AssertionError(f"longest drought changed: number {worst[0]}, {worst[1]['drought']} draws")
    notes.append(
        f"OK  Era B mean gap {mean_of_means:.2f} draws (theory 10); longest drought "
        f"number {worst[0]} at {worst[1]['drought']} draws"
    )

    if report["odds"]["lines"] != 139_838_160:
        raise AssertionError(f"jackpot odds changed: {report['odds']['lines']}")
    notes.append(f"OK  jackpot odds = 1 in {report['odds']['lines']:,}")

    week_year = report["meta"]["week_year_mismatches"]
    if len(week_year) != 4:
        raise AssertionError(f"expected 4 rok/calendar-year mismatches, got {len(week_year)}")
    notes.append(f"OK  `rok` is an ISO week-year: {len(week_year)} rows differ from the calendar year")

    return notes


def default_csv(here: Path) -> Path:
    """Prefer the copy sitting beside this file, so the folder stands alone.

    The same file also exists one level up; the two are byte-identical. The local copy
    wins so that this deliverable reads only its own folder, falling back to the parent
    for the case where someone has trimmed the folder down to just the scripts.
    """
    local = here / "eurojackpot.csv"
    return local if local.exists() else here.parent / "eurojackpot.csv"


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", nargs="?", default=str(default_csv(here)))
    ap.add_argument("--out", default=str(here / "stats.json"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    draws = load_draws(args.csv)
    report = build_report(draws)
    report["model"]["suggested_lines"] = suggest_lines(draws)
    # Backtest on Era B only: the cadence and the Set #2 universe both changed at the
    # boundary, so mixing eras would feed the model incomparable history.
    report["backtest"] = backtest([d for d in draws if d.era == "B"])

    notes = self_check(draws, report)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    if not args.quiet:
        for note in notes:
            print(note)
        bt = report["backtest"]
        print(f"\nWrote {args.out}")
        print(
            f"Backtest over {bt['targets']} draws x {bt['lines_per_target']} lines:\n"
            f"  model  {bt['model']['mean_matched']:.4f} matched "
            f"[{bt['model']['ci95_low']:.3f}, {bt['model']['ci95_high']:.3f}]\n"
            f"  random {bt['random_baseline']['mean_matched']:.4f} matched "
            f"[{bt['random_baseline']['ci95_low']:.3f}, {bt['random_baseline']['ci95_high']:.3f}]\n"
            f"  analytic expectation {bt['analytic_expectation']:.2f}   "
            f"p = {bt['p_value']:.3f}\n  -> {bt['conclusion']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
