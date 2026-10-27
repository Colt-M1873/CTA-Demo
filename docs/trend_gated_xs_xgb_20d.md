# 趋势门控 + 截面 XGBoost 多因子（20 日 retune）

> 记录日期：2026-10-27（Asia/Shanghai）  
> 代码入口：`Desktop/vnpy/backtest_trend_xs_xgb_20d.py`  
> 策略模块：`Desktop/vnpy/strategies/trend_xs_xgb.py`（复用 `trend_xs_multifactor.py` 的门控/仓位）  
> 回测结果：`Desktop/vnpy/data/trend_xs_xgb_results_20d/`  
> 旧版 5 日 / 12 品种结果保留：`data/trend_xs_xgb_results/`（见 `docs/trend_gated_xs_xgb.md`）  
> 等权 20 品种基线：`data/trend_xs_results_20/`

---

## 1. 相对上一版改了什么

| 项 | 旧 XGB（12 品种 / 5 日） | 本版 retune |
|------|---------------------------|-------------|
| 宇宙 | 12 商品 | **20 商品**（`COMMODITY_SPECS`，无金融） |
| 调仓 | 每 5 个交易日 | **每 20 个交易日** |
| 标签 | 未来 5 日收益 | **未来 20 日收益**（与调仓对齐） |
| `MIN_TRAIN_SAMPLES` | 200 | **1500** |
| `MIN_TRAIN_REBALANCES` | 50 | **100** |
| 树参数 | depth=3, lr=0.05, 80 树… | **不变**（保守，未网格搜索） |
| 门控 / ATR / 选约 25% | 不变 | 不变 |

样本不足时仍 **fallback** 到等权稳健 z 因子分。

---

## 2. 特征与训练

特征同旧版：`mom_20/60/120`、`low_vol`、`oi_chg_20`、`channel_pos`（先验通道，无偷看）。

Walk-forward 扩展窗口：每个调仓日 t，用 date &lt; t 且标签窗口已结束的样本训练；当日特征只打分与入库。

`XGBRegressor`：max_depth=3, n_estimators=80, learning_rate=0.05, subsample/colsample=0.8, min_child_weight=5, reg_lambda=1。

---

## 3. 如何运行

```
cd C:\Users\Administrator\Desktop\vnpy
.\.venv\Scripts\python.exe backtest_trend_xs_xgb_20d.py
```

旧 5 日入口仍可用（已 pin 到 LEGACY_5D）：`backtest_trend_xs_xgb.py` → `data/trend_xs_xgb_results/`。

输出 `data/trend_xs_xgb_results_20d/`：`equity_curve.csv` / `trades.csv` / `score_mode_log.csv` / `summary.json` / `report.txt`。

---

## 4. 回测结果（实盘脚本，非编造）

区间：**2009-09-30 → 2026-10-27**（4159 个交易日）  
宇宙：**20** 商品 — AG, AU, CF, CU, FG, I, J, JM, L, M, MA, P, PP, RB, RU, SA, SC, TA, V, Y

| 指标 | 旧 XGB（12 名 / 5 日） | 等权 20 基线（5 日调仓） | **本版 XGB 20d** |
|------|------------------------|--------------------------|------------------|
| 总收益 | 8.3404% | 11.0232% | **1.3491%** |
| 年化 | 0.4292% | 0.6356% | **0.0812%** |
| 最大回撤 | -23.437% | -22.3767% | **-7.0612%** |
| 夏普 | 0.1022 | 0.1251 | **0.0437** |
| 期末权益 | 1083403.75 | 1110231.79 | **1013491.37** |
| 平仓胜率 | 42.31% | 42.23% | **42.86%** |
| 调仓 / xgb / fallback | 559+384 | — | **208 / 90 / 118** |

训练门槛实值：MIN_TRAIN_SAMPLES=1500，MIN_TRAIN_REBALANCES=100，horizon=20。  
历史行数 3557，已标注 3537；末次模式 xgb。

**结论（对本数据）**：20 日 retune 后总收益与夏普仍弱于旧 XGB 与等权 20 基线；回撤明显更小（交易更稀）。约一半以上调仓仍是等权 fallback（118/208），真正 XGB 区间更短。等权 20 基线仍是 5 日调仓，对比时 horizon 不完全一致。

末次特征重要性：

| 特征 | importance |
|------|--------------|
| mom_60 | 0.2125 |
| low_vol | 0.1769 |
| channel_pos | 0.1706 |
| mom_120 | 0.1656 |
| mom_20 | 0.1465 |
| oi_chg_20 | 0.1278 |


---

## 5. 注意与局限

- 新浪主力连续，换月缺口未建模；信号日收盘成交偏乐观。
- 更高开训门槛 → 前期更长为等权 fallback，净值是混合策略。
- 等权 20 基线仍是 **5 日调仓**，与本版 20 日 horizon 不完全同设定，对比时注意。
- 小截面 + 噪声标签下 ML 不保证优于等权；回测 ≠ 未来。

---

## 6. 文件清单

| 路径 | 说明 |
|------|------|
| strategies/trend_xs_xgb.py | 默认 20d 门槛；含 `LEGACY_5D` |
| backtest_trend_xs_xgb_20d.py | 本版回测入口 |
| backtest_trend_xs_xgb.py | 旧 5d 入口（pin LEGACY_5D） |
| data/trend_xs_xgb_results_20d/ | 本版结果 |
| docs/trend_gated_xs_xgb_20d.md | 本文档 |
