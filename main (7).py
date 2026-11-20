"""Forecaster for make.fun's gta6-trophy-rarity-forecast-01.

Reads one case file (JSON) from the input directory: the house's recorded
reads of Exophase's GTA VI (PS5) trophy page before the case checkpoint.
For every trophy it writes five quantiles (5/25/50/75/95%) of the earn rate
the page will show at the case's target time.

A rate is a ratio, so the forecast models its two sides separately and
then cross-checks them against a direct fit of the rate itself:

- Earners: how many tracked players hold the trophy (rate x players,
  recovered from each read). Earners never shrink; their growth is fitted
  on the log scale, against time and against log-time, and the better
  fit is extended, damped.
- Players: how many players Exophase tracks for the game. The pool grows
  fast after launch and each jump dilutes every rate, so the pool gets
  its own growth fit, extrapolated the same way.
- Direct: the rate's own history fitted on the logit scale (the scale
  the contest scores), again against time and log-time.

The median is the average, on the logit scale, of the counts forecast
(earners / players) and the direct forecast. The spread combines a
random-walk term that grows with the square root of the horizon, the
direct fit's residual scatter, the size of the median's own move, the
pool's expected growth (a bigger pool jump means a less certain rate),
and how far the counts and direct forecasts disagree.

Story trophies form a funnel (Chapter 1 before Chapter 2, the final
mission before the platinum), so no quantile level may rise along that
chain; later trophies are pulled down to the earlier one's level.

Standard library only, no network, deterministic: the same case always
produces the same bytes.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# The grader runs with -P, which keeps this file's directory off sys.path;
# put it back first so a module shipped beside main.py would still import.
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

HALF_LIFE_HOURS = 18.0   # weight of a read halves this many hours back
DAMP = 0.55              # how much of a fitted trend we dare to extend
DAMP_POOL = 0.8          # pool growth is steadier, so it is damped less
MAX_UP = 2.2             # cap on the median's upward move, logit units
MAX_DOWN = 1.2           # cap on the median's downward move, logit units
RW_SIGMA = 0.45          # random-walk spread, logit units per sqrt(day)
SIGMA_FLOOR = 0.25
SIGMA_CAP = 1.7


def clamp_rate(pct: float) -> float:
    return min(99.99, max(0.01, pct))


def logit(pct: float) -> float:
    r = clamp_rate(pct)
    return math.log(r / (100.0 - r))


def inv_logit_pct(x: float) -> float:
    if x >= 0:
        return 100.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return 100.0 * e / (1.0 + e)


def round4(x: float):
    """Round to 4 decimals, half up, matching JavaScript's Math.round."""
    scaled = x * 10000
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000
    return int(value) if float(value).is_integer() else value


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def weighted_line(xs, ys, ws):
    """Weighted least squares y ~ a + b*x; returns (a, b, weighted resid std)."""
    sw = sum(ws)
    mx = sum(w * x for x, w in zip(xs, ws)) / sw
    my = sum(w * y for y, w in zip(ys, ws)) / sw
    sxx = sum(w * (x - mx) ** 2 for x, w in zip(xs, ws))
    if sxx <= 0:
        return my, 0.0, 0.0
    sxy = sum(w * (x - mx) * (y - my) for x, y, w in zip(xs, ys, ws))
    b = sxy / sxx
    a = my - b * mx
    var = sum(w * (y - (a + b * x)) ** 2 for x, y, w in zip(xs, ys, ws)) / sw
    return a, b, math.sqrt(var)


def weights_for(times):
    t_end = times[-1]
    return [0.5 ** ((t_end - t) / HALF_LIFE_HOURS) for t in times]


def best_move(times, ys, t_target, damp):
    """Extend a series to t_target with the better of two trend shapes.

    Fits y against time and against log-time (a diffusion curve that
    saturates), weighted toward recent reads, and returns (move from the
    last observed y, residual std of the winning fit). The move is the
    winning slope times the gap in its own x-space, damped.
    """
    if len(times) < 2:
        return 0.0, 0.0
    ws = weights_for(times)
    _, b_lin, resid_lin = weighted_line(times, ys, ws)
    move_lin = b_lin * (t_target - times[-1])
    log_xs = [math.log(max(t, 0.25)) for t in times]
    _, b_log, resid_log = weighted_line(log_xs, ys, ws)
    move_log = b_log * (math.log(max(t_target, 0.25)) - log_xs[-1])
    if resid_log <= resid_lin:
        return move_log * damp, resid_log
    return move_lin * damp, resid_lin


def forecast_pool(times, players, t_target):
    """Extrapolate the tracked-player pool to the target time."""
    p_last = players[-1]
    if len(times) < 2 or p_last <= 0:
        return float(p_last)
    move, _ = best_move(times, [math.log(max(p, 1)) for p in players],
                        t_target, DAMP_POOL)
    move = min(math.log(8.0), max(0.0, move))
    return p_last * math.exp(move)


def forecast_case(case):
    history = case["history"]
    if not history:
        raise ValueError("case has no history")
    release = parse_time(case["game"]["release_date"])
    if release.tzinfo is None:
        release = release.replace(tzinfo=timezone.utc)

    # Collapse consecutive identical reads: between Exophase refreshes the
    # page does not change, and repeats carry no new information.
    snaps = []  # (hours_since_release, players_tracked, rates)
    for read in history:
        t = (parse_time(read["at"]) - release).total_seconds() / 3600.0
        snap = (t, read["players_tracked"], read["rates"])
        if not snaps or snaps[-1][1] != snap[1] or snaps[-1][2] != snap[2]:
            snaps.append(snap)
    times = [s[0] for s in snaps]
    players = [s[1] for s in snaps]
    t_target = times[-1] + case["horizon_minutes"] / 60.0
    horizon_days = case["horizon_minutes"] / 1440.0

    p_target = forecast_pool(times, players, t_target)
    pool_log_growth = math.log(p_target / players[-1]) if players[-1] > 0 else 0.0

    rows = []
    for i, trophy in enumerate(case["trophies"]):
        pts = [(snaps[j][0], snaps[j][2][i], snaps[j][1]) for j in range(len(snaps))
               if snaps[j][2][i] is not None]
        if not pts:
            pts = [(times[-1], 0.0, players[-1])]
        p_times = [p[0] for p in pts]
        p_rates = [p[1] for p in pts]
        last_rate = p_rates[-1]
        y_last = logit(last_rate)

        # Direct forecast: the rate's own logit trend.
        move_d, resid = best_move(p_times, [logit(r) for r in p_rates],
                                  t_target, DAMP)
        move_d = min(MAX_UP, max(-MAX_DOWN, move_d))
        direct_logit = y_last + move_d

        # Counts forecast: extend the earners, divide by the pool target.
        earners = [r / 100.0 * pool for _, r, pool in pts]
        move_e, _ = best_move(p_times,
                              [math.log(e + 0.5) for e in earners],
                              t_target, 0.7)
        e_target = (earners[-1] + 0.5) * math.exp(move_e) - 0.5
        e_target = min(max(e_target, earners[-1]), p_target)
        counts_logit = logit(100.0 * e_target / p_target) if p_target > 0 else y_last

        median_logit = 0.5 * direct_logit + 0.5 * counts_logit

        sigma = math.sqrt(
            (RW_SIGMA ** 2) * horizon_days
            + (resid ** 2) * min(horizon_days, 2.0)
            + (0.35 * abs(median_logit - y_last)) ** 2
            + (0.30 * pool_log_growth) ** 2
            + (0.25 * abs(counts_logit - direct_logit)) ** 2
        )
        sigma = min(SIGMA_CAP, max(SIGMA_FLOOR, sigma))

        qs = [inv_logit_pct(median_logit + z * sigma) for z in Z]
        qs = [min(100.0, max(0.0, q)) for q in qs]
        qs.sort()
        rows.append({"id": trophy["id"], "q": [round4(q) for q in qs]})

    enforce_funnel(rows, story_chain(case["trophies"]))
    return {"trophies": rows}


def story_chain(trophies):
    """Ids of the story funnel, in order: Chapter 1..N, the final mission,
    then the platinum. A player cannot hold a later one without the earlier
    ones, so earn rates along this chain can never increase."""
    chapters = []
    final = None
    platinum = None
    for trophy in trophies:
        desc = trophy["description"]
        if desc.startswith("Complete Chapter "):
            try:
                chapters.append((int(desc.split()[2].strip(".")), trophy["id"]))
            except (ValueError, IndexError):
                pass
        elif desc == "Complete the final mission.":
            final = trophy["id"]
        if trophy["tier"] == "platinum":
            platinum = trophy["id"]
    chain = [tid for _, tid in sorted(chapters)]
    if final is not None:
        chain.append(final)
    if platinum is not None:
        chain.append(platinum)
    return chain


def enforce_funnel(rows, chain):
    """Pull each quantile level down along the story chain so it never
    rises: elementwise minima keep every row's levels non-decreasing."""
    by_id = {row["id"]: row for row in rows}
    for k in range(len(LEVELS)):
        ceiling = None
        for tid in chain:
            row = by_id.get(tid)
            if row is None:
                continue
            if ceiling is not None and row["q"][k] > ceiling:
                row["q"][k] = ceiling
            ceiling = row["q"][k]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        out = json.dumps(forecast, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / f"{path.stem}.out").write_text(out, encoding="utf-8")


if __name__ == "__main__":
    main()
