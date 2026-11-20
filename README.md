# makefun-gta-trophy-forecast

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Fauziwildan0856/makefun-gta-trophy-forecast/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Fauziwildan0856/makefun-gta-trophy-forecast/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

A forecaster for GTA VI (PS5) trophy earn rates. For each competition case it reads the house's recorded reads of the Exophase trophy page and writes five quantiles (5/25/50/75/95%) per trophy for the earn rate the page will show at the case's target time.

A rate is a ratio, so the program models its two sides separately and then cross-checks them against a direct fit of the rate itself:

- **Earners** — how many tracked players hold the trophy (rate × players, recovered from each read). Earners never shrink; their growth is fitted on the log scale, against time and against log-time, and the better fit is extended, damped.
- **Players** — how many players Exophase tracks for the game. The pool grows fast after launch and each jump dilutes every rate, so the pool gets its own growth fit, extrapolated the same way.
- **Direct** — the rate's own history fitted on the logit scale (the scale the contest scores), again against time and log-time.

The median is the average, on the logit scale, of the counts forecast (earners / players) and the direct forecast. The spread combines a random-walk term that grows with the square root of the horizon, the direct fit's residual scatter, the size of the median's own move, the pool's expected growth, and how far the counts and direct forecasts disagree.

Story trophies form a funnel (Chapter 1 before Chapter 2, the final mission before the platinum), so no quantile level may rise along that chain; later trophies are pulled down to the earlier one's level.

Pure Python 3 standard library, offline, deterministic: the same case file always produces the same forecast. Validated on the kit's two practice cases (55 trophies each, valid output, well under the per-case time limit) and on synthetic dilution scenarios, where the two-cohort pool-growth behaviour matters most.

## Run it

```sh
python3 main.py
```

The program reads every case file (`<id>.in`) from `/input` (override with the `MAKEFUN_INPUT_DIR` environment variable) and writes `<id>.out` to `/output` (override with `MAKEFUN_OUTPUT_DIR`). Each output file holds one JSON object: `{"trophies": [{"id": n, "q": [q05, q25, q50, q75, q95]}, ...]}` with quantiles as percentages between 0 and 100, non-decreasing.

---

<sub>Entered on [make.fun](https://make.fun/?ref=z63ha401&utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards</sub>
