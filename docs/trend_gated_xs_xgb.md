# 趋势门控 + 截面 XGBoost 多因子

> 记录日期：2026-10-27（Asia/Shanghai）  
> 代码入口：`Desktop/vnpy/backtest_trend_xs_xgb.py`  
> 策略模块：`Desktop/vnpy/strategies/trend_xs_xgb.py`（复用 `trend_xs_multifactor.py` 的门控/仓位）  
> 回测结果：`Desktop/vnpy/data/trend_xs_xgb_results/`  
> 基线（等权因子）：`Desktop/vnpy/data/trend_xs_results/` 与 `docs/trend_gated_xs_multifactor.md`

---

## 1. ML 加在哪

**只替换截面打分**，不替换唐奇安趋势门控。

| 模块 | 实现 |
|------|------|
| 趋势门控 | 仍用 Donchian 20 日规则（先验高低，无同日偷看） |
| 截面打分 | XGBoost 回归预测下一持有期收益，再在同向池内排序 |
| 仓位 | 仍用 ATR 风险手数 |
| 调仓 / 出场 | 每 5 个交易日调仓；门控翻转强制平仓 |

样本不足时 **回退** 到等权稳健 z 因子分（与基线相同）。

---

## 2. 特征（leak-free）

与基线相同的五个因子，外加一个廉价通道位置：

| 特征 | 定义 |
|------|------|
| mom_20 / mom_60 / mom_120 | 近 N 日收益率 |
| low_vol | -sigma(近 20 日日收益) |
| oi_chg_20 | 持仓量 20 日变化率 |
| channel_pos | (close - donchian_low) / (donchian_high - donchian_low)，通道用 **前一日及以前** 高低 |

全部用调仓日当日及以前信息；标签窗口在训练时必须已结束。

---

## 3. 标签选择

**回归**：预测未来 `HORIZON_DAYS = 5` 个交易日的 **收盘到收盘收益率**（与调仓周期一致）。

在同向合格池内按预测值排序：

- 做多池：取预测收益最高的约 25%
- 做空池：取预测收益最低的约 25%

未采用分类/排名标签，是为了在小样本下更直接、实现简单；排序仍按预测值截面比较。

---

## 4. Walk-forward 训练

- **扩展窗口**：每个调仓日 t，用所有 date < t 且标签已可知（远期窗口终点不超过当日）的样本训练。
- **不偷看**：当日特征只用于打分与事后入库；训练矩阵不含当日行。
- **门槛**：至少 `MIN_TRAIN_SAMPLES=200` 条已标注样本，且至少 `MIN_TRAIN_REBALANCES=50` 个历史调仓日；否则用等权因子。
- **模型**：`XGBRegressor`，max_depth=3, n_estimators=80, learning_rate=0.05, subsample/colsample=0.8, min_child_weight=5, reg_lambda=1。

本轮实际：943 次调仓中，**fallback 384 / xgb 559**（前期不足样本走等权）。

---

## 5. 组合规则（与基线一致）

- 商品池 12 个：AG AU CF CU I M MA RB RU SC TA Y（金融期货不混截面）
- 选股比例约 25%；ATR 仓位 risk_frac_per_name=0.01，单品种最多 20 手
- 本金 100 万；佣金万 1；滑点 1 跳；信号日收盘价成交（偏乐观）

---

## 6. 如何运行

```
cd C:\Users\Administrator\Desktop\vnpy
.\.venv\Scripts\python.exe backtest_trend_xs_xgb.py
```

依赖：已在 `.venv` 安装 `xgboost`、`scikit-learn`。
基线对比可另跑：`backtest_trend_xs_multifactor.py`（不改动）。

输出目录 `data/trend_xs_xgb_results/`：

- `equity_curve.csv` / `trades.csv` / `score_mode_log.csv`
- `summary.json` / `report.txt`

---

## 7. 回测结果（实盘脚本，非编造）

区间：**2007-07-05 → 2026-10-27**（4714 个交易日）

| 指标 | 等权因子基线 | 本节 XGB |
|------|--------------|----------|
| 总收益 | 23.016% | **8.3404%** |
| 年化 | 1.1135% | **0.4292%** |
| 最大回撤 | -20.5136% | **-23.4370%** |
| 夏普 | 0.223 | **0.1022** |
| 期末权益 | 1,230,160 | **1,083,404** |
| 开/平仓 | 671 / 671 | 676 / 676 |
| 平仓胜率 | 43.22% | 42.31% |
| 调仓 | 943 | 943（xgb 559 + fallback 384） |

**结论（对本数据）**：在相同门控与仓位下，把截面等权换成 walk-forward XGB **没有提升**，总收益与夏普都弱于基线。可能原因：品种池小、5 日标签噪声大、主力连续未建模换月、树模型在扩展样本上仍易拟合噪声。

末次拟合特征重要性（仅供参考）：channel_pos 0.187、oi_chg_20 0.179、low_vol 0.169、mom_120 0.168、mom_60 0.160、mom_20 0.138。

---

## 8. 注意与局限

- 新浪主力连续，换月缺口未建模。
- 信号日收盘成交偏乐观。
- 前期较长时间为等权 fallback，曲线是混合策略。
- 小截面 + 短 horizon 标签，ML 增益不保证；回测不等于未来。
- 基线脚本保持可独立运行，便于 A/B。

---

## 9. 文件清单

| 路径 | 说明 |
|------|------|
| strategies/trend_xs_xgb.py | ExpandingXGBScorer、特征扩展、训练门槛 |
| backtest_trend_xs_xgb.py | Walk-forward 回测入口 |
| data/trend_xs_xgb_results/ | 净值、成交、summary、report |
| docs/trend_gated_xs_xgb.md | 本文档 |

---

## 10. 后续 retune（20 日 / 20 品种）

见 **docs/trend_gated_xs_xgb_20d.md** 与 data/trend_xs_xgb_results_20d/。  
模块默认已改为 20d 门槛；本文件对应的旧 5d 结果仍在 data/trend_xs_xgb_results/，可用 acktest_trend_xs_xgb.py（已 pin LEGACY_5D）复现。

