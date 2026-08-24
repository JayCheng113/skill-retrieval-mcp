---
name: timeseries-forecasting
description: Fit and evaluate forecasting models on seasonal time series such as demand, traffic or sensor readings.
category: analysis
tags: [forecasting, timeseries, seasonality, backtesting]
---

# Forecasting a seasonal series

Split by time, never at random. A shuffled split lets the model see the future,
and the resulting score is meaningless no matter how good it looks.

Decompose first. If trend and seasonality are additive, a linear model on lagged
features is usually enough; if the seasonal amplitude grows with the level, take
logs before fitting rather than reaching for a bigger model.

Evaluate with rolling-origin backtesting: fit on everything up to time `t`,
predict the next horizon, advance `t`, repeat. A single held-out tail measures one
draw from a distribution and will mislead you about variance.

Always report against a naive baseline — last value, or last season's value. A
surprising number of elaborate models fail to beat it.
