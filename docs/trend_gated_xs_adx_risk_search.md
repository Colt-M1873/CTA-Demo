# 风控参数网格搜索（ADX+40 等权信号不变）

脚本：acktest_trend_xs_adx_risk_search.py
汇总：data/trend_xs_adx_risk_search/search_summary.csv
推荐配置：data/trend_xs_adx_risk_search/best_config.json → profile **search_best**
完整结果：data/trend_xs_adx_risk_search_best_results/

## 设定
- 宇宙：40 商品；信号/ADX/假突破/等权选仓不变
- 只搜风控层：波动目标、缩放下限、总杠杆上限、回撤半仓/空仓阈值与恢复滞后
- 共 20 组；排序：夏普 ↓，回撤（绝对值更浅）↓，总收益 ↓
- Walk-forward 与原回测一致：波动用历史权益收益，无当日偷看

## 推荐：search_best（原名 vol15_floor04_cap08_dd15_25）
- vol_target **15%**，vol_scale_min **0.40**，gross_cap **0.80**
- DD HALF>**15%** / FLAT>**25%**；FLAT→HALF ≤15%，HALF→NORMAL ≤10%
- 夏普 **0.1442**，年化 **0.7549%**，最大回撤 **-17.4845%**，总收益 **11.5789%**
- 平均/最大总杠杆 **0.1245 / 0.8642**；半仓天数 1349，空仓天数 0

## Top 对照

| name | Sharpe | ann% | maxDD% | total% | avg_gross | HALF | FLAT |
|--|--|--|--|--|--|--|--|
| vol15_floor04_cap08_dd15_25 | 0.1442 | 0.755 | -17.48 | 11.58 | 0.1245 | 1349 | 0 |
| vol_off_cap08_dd15_25 | 0.1406 | 0.732 | -17.68 | 11.20 | 0.1249 | 1349 | 0 |
| risk_off | 0.1256 | 0.774 | -24.09 | 11.89 | 0.2003 | 0 | 0 |
| vol15_floor06_cap10_dd_off | 0.1215 | 0.720 | -22.49 | 11.01 | 0.1918 | 0 | 0 |
| vol20_floor08_cap10_dd_off | 0.1189 | 0.700 | -23.83 | 10.69 | 0.1978 | 0 | 0 |
| vol15_floor04_cap10_dd_off | 0.1177 | 0.681 | -22.50 | 10.39 | 0.1915 | 0 | 0 |
| vol15_floor06_cap10_dd20_30 | 0.1140 | 0.610 | -22.36 | 9.26 | 0.1554 | 1335 | 0 |
| vol12_floor04_cap08_dd15_25 | 0.1107 | 0.529 | -19.51 | 7.99 | 0.1267 | 1231 | 0 |

## 结论（诚实）
- 相对无风控（Sharpe≈0.126、DD≈-24%）与 loose（≈0.111），**search_best 夏普≈0.144、回撤≈-17.5%**，是本网格里最好的风险层。
- 次优几乎是 **关掉波动目标、只保留 cap=0.8 + DD15/25**（Sharpe≈0.141）——说明半仓熔断+杠杆上限贡献最大，温和波动缩放略有加分。
- **仅靠拧风控参数到不了夏普 0.6**；样本内最好仍在 **0.14～0.15** 一带。要再抬夏普需要信号/数据/因子侧，而不是继续穷举风控。

运行：python backtest_trend_xs_adx_risk.py --profile search_best

