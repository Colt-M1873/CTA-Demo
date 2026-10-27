# 趋势门控 + 假突破过滤 + 截面等权因子（含 ADX）+ 等权仓位

> 记录日期：2026-10-28（Asia/Shanghai）  
> 代码入口：`Desktop\vnpy\backtest_trend_xs_adx.py`  
> 策略模块：`Desktop\vnpy\strategies\trend_xs_adx.py`  
> 回测结果：`Desktop\vnpy\data\trend_xs_adx_results\`  
> 对照：`Desktop\vnpy\data\trend_xs_ew_filter_results\`（20 商品、无 ADX、假突破过滤 + 等权仓位）  
> **不含 XGBoost**

---

## 1. 相对上一版（EW+过滤 20）改了什么

| 项 | 上版 EW+过滤 20 | 本版 |
|--|--|--|
| 宇宙 | 20 商品 | **40 商品**（全部本地商品日线；排除 IF/IH/IC/IM/T/TF/TS/TL） |
| 截面因子 | mom20/60/120 + low_vol + oi_chg | 同左 **+ ADX(14)**，六因子等权 robust-z |
| 空头打分 | 同一综合分取尾部 | **方向因子取反**后取头部；ADX / low_vol 两侧都保持正向 |
| 假突破过滤 | 有（实体/ATR + 量能） | **保留** |
| 仓位 | 等权资金 | **保留** |
| 门控 / 调仓 | Donchian 20；每 5 日 | 同左 |

> 注意：宇宙与因子同时变了，**不是纯 ADX 单因子 A/B**。回撤变浅也可能来自 40 池分散或起步更晚。

---

## 2. ADX(14) 计算（Wilder，无泄漏约定）

对每个品种日线 OHLC：

1. \(TR_t\)、\(+DM_t\)、\(-DM_t\) 按经典定义（首根因无昨值记为 NaN）。  
2. Wilder RMA：首值 = 近 `period` 根 SMA，其后  
   \(rma_t = (rma_{t-1}\cdot(n-1) + x_t)/n\)，\(n=14\)。  
3. \(+DI,-DI\) → \(DX\) → 再对 DX 做 Wilder RMA 得 **ADX**。  

**打分时点**：调仓日使用当日收盘可知的 `ADX_t`（与「信号日收盘成交」假设一致）。未用未来 bar。  
若更保守，可改为 `ADX_{t-1}`；本版文档化为 **当日收盘 ADX**。

经济含义：**ADX 越高 = 趋势越强**（不区分多空方向）。因此：

- 多头池：ADX robust-z **正向**计入等权综合分；  
- 空头池：动量 / OI 变化 z 取反后与 **正向 ADX、正向 low_vol** 等权合成，再取分数最高约 25%（强下跌趋势 + 相对低波优先）。

---

## 3. 假突破过滤与等权仓位（与上版相同）

- 入场：`Donchian` 门控 ∧ `|body|/ATR ≥ 0.25`（方向一致）∧ `volume >` 先验 20 日均量（rolling 后 `shift(1)`）。  
- 出场：只看原始门控；过滤不强制平仓。  
- 仓位：`w = GROSS_LEVERAGE / n_sel`，`lots = floor(Capital * w / (price * multiplier))`，`GROSS_LEVERAGE=1.0`，单品种最多 50 手；买不起 1 手则跳过。

---

## 4. 40 商品宇宙与乘数

本地 `data\*_daily_main_sina.csv` 中全部商品（40）；金融期货已排除。

新增 20 个名称的合约乘数 / 最小变动价位为**常用默认**（仅影响手数与 PnL 尺度，非交易所实时规则核对）：

| 代码 | size | tick | 交易所 |
|--|--|--|--|
| A | 10 | 1 | DCE |
| AL | 5 | 5 | SHFE |
| B | 10 | 1 | DCE |
| BU | 10 | 1 | SHFE |
| C | 10 | 1 | DCE |
| CS | 10 | 1 | DCE |
| EB | 5 | 1 | DCE |
| EG | 10 | 1 | DCE |
| FU | 10 | 1 | SHFE |
| HC | 10 | 1 | SHFE |
| JD | 10 | 1 | DCE |
| NI | 1 | 10 | SHFE |
| OI | 10 | 1 | CZCE |
| PB | 5 | 5 | SHFE |
| RM | 10 | 1 | CZCE |
| SN | 1 | 10 | SHFE |
| SP | 10 | 2 | SHFE |
| SR | 10 | 1 | CZCE |
| UR | 20 | 1 | CZCE |
| ZN | 5 | 5 | SHFE |

原 20 个规格未改（见 `strategies\trend_xs_adx.py` 中 `COMMODITY_SPECS`）。

---

## 5. 复现

```text
C:\Users\Administrator\Desktop\vnpy\.venv\Scripts\python.exe backtest_trend_xs_adx.py
```

输出：

- `data\trend_xs_adx_results\summary.json`
- `equity_curve.csv` / `trades.csv` / `report.txt`

---

## 6. 回测结果对比

跑批时间：2026-10-28（Asia/Shanghai）。

| 指标 | 上版 EW+过滤 20 | **本版 ADX + 40** |
|--|--|--|
| 区间 | 2009-09-30 → 2026-10-27（4159 日） | **2011-09-28 → 2026-10-27（3671 日）** |
| 总收益 | **19.1291%** | 11.8913% |
| 年化 | **1.0662%** | 0.7743% |
| 最大回撤 | −37.8207% | **−24.0852%** |
| 夏普 | **0.1505** | 0.1256 |
| 期末权益 | 1,191,291 | 1,118,913 |
| 开/平仓 | 544 / 544 | 749 / 747 |
| 胜率（平仓） | **43.93%** | 40.03% |
| 调仓次数 | 832 | 735 |
| 过滤挡下 | 734 | 1195 |

（参考）同机 ATR 仓位 20、无过滤：总收益 11.02%，夏普 0.13，最大回撤 −22.4%。

**解读（简）**：加入 ADX 并扩到 40 后，夏普/收益低于上版 20 名 EW+过滤，但最大回撤明显变浅（约 −24% vs −38%）。起步更晚（要等一半品种够长）、池子更散、空头打分对 low_vol 也改为正向，都会影响结果。仍远未到可上线水平。

---

## 7. 注意

- 新浪主力连续，换月/跳空未建模。  
- 以信号日收盘成交；ADX 用当日收盘值。  
- 等权在贵合约上可能 0 手。  
- 新品种乘数/tick 为默认值，实盘前需核对。  
- 历史回测 ≠ 未来收益。
