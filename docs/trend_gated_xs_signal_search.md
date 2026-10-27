# Signal-param search (risk fixed: search_best)

Grid size: 25. Sort: Sharpe → max DD (less neg) → total return.
Winner: **entry_40_rebal_10** registered as `signal_best`.

## Winner
- Sharpe=0.4728  ann=2.8221%  DD=-11.484%  total=49.9925%
- entry=40 select=0.25 rebal=10 bodyATR=0.25 vol_filter=True factors=all

## Top configs

| name               |   sharpe_ratio |   annual_return_pct |   max_ddpercent |   total_return_pct |   entry_window |   select_pct |   rebalance_every_n_days |   body_atr_min | use_volume_filter   | factor_set   |
|:-------------------|---------------:|--------------------:|----------------:|-------------------:|---------------:|-------------:|-------------------------:|---------------:|:--------------------|:-------------|
| entry_40_rebal_10  |         0.4728 |              2.8221 |        -11.484  |            49.9925 |             40 |         0.25 |                       10 |           0.25 | True                | all          |
| entry_40_select_15 |         0.4696 |              3.3329 |        -14.5369 |            61.2204 |             40 |         0.15 |                        5 |           0.25 | True                | all          |
| entry_40           |         0.404  |              2.7183 |        -14.9258 |            47.8008 |             40 |         0.25 |                        5 |           0.25 | True                | all          |
| body_04            |         0.3758 |              2.1526 |        -17.8852 |            36.3778 |             20 |         0.25 |                        5 |           0.4  | True                | all          |
| entry_40_no_adx    |         0.3731 |              2.4836 |        -14.5638 |            42.9575 |             40 |         0.25 |                        5 |           0.25 | True                | no_adx       |
| entry_55_body_04   |         0.3714 |              2.0561 |        -17.8336 |            34.5121 |             55 |         0.25 |                        5 |           0.4  | True                | all          |
| mom_lowvol         |         0.288  |              1.8053 |        -15.1531 |            29.7765 |             20 |         0.25 |                        5 |           0.25 | True                | mom_lowvol   |
| entry_55           |         0.2604 |              1.6888 |        -16.0681 |            27.6288 |             55 |         0.25 |                        5 |           0.25 | True                | all          |

## Reproduce
```
python backtest_trend_xs_adx_risk.py --profile search_best --signal-profile signal_best
python backtest_trend_xs_signal_search.py
```

## Ceiling note
In-sample signal tuning on Sina main-force continuous + simplified costs typically keeps Sharpe in a low band (~0.1–0.3 here). Hitting 0.6+ needs cleaner data / richer factors / different scheme — not more Donchian/select knobs alone.

Artifacts: `C:\Users\Administrator\Desktop\vnpy\data\trend_xs_signal_search` ; best results: `C:\Users\Administrator\Desktop\vnpy\data\trend_xs_signal_signal_best_results`
