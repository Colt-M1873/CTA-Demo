# 趋势门控 + 假突破过滤 + 截面等权因子 + 等权仓位

> 记录日期：2026-10-27（Asia/Shanghai）  
> 代码入口：`Desktop\vnpy\backtest_trend_xs_ew_filter.py`  
> 策略模块：`Desktop\vnpy\strategies\trend_xs_ew_filter.py`  
> 回测结果：`Desktop\vnpy\data\trend_xs_ew_filter_results\`  
> 对照基线：`Desktop\vnpy\data\trend_xs_results_20\`（同 20 商品、等权因子、ATR 仓位、无假突破过滤）  
> **不含 XGBoost**

---

## 1. 相对基线改了什么

| 项 | 基线 `trend_xs_results_20` | 本版 |
|--|--|--|
| 宇宙 | 20 商品 | 同左 |
| 截面因子 | 等权 robust-z（mom20/60/120 + 低波动 + OI 变化） | 同左 |
| 选取 | 同向池约前/后 25% | 同左 |
| 调仓 | 每 5 个交易日 | 同左 |
| 趋势门控 | Donchian 20（先验高低） | 同左；**出场仍只看门控** |
| 入场 | 过门控即可进截面池 | 门控 **+ 假突破过滤** |
| 仓位 | ATR 波动缩放 | **等权资金权重** |

---

## 2. 假突破过滤（入场专用，精确规则）

对每个品种、每个交易日 \(t\)（日线，假定以当日收盘成交）：

### 2.1 仍先过 Donchian 门控（无未来）

- 上轨 = \(\max(high_{t-20},\ldots,high_{t-1})\)
- 下轨 = \(\min(low_{t-20},\ldots,low_{t-1})\)
- `long_eligible`：\(close_t >\) 上轨  
- `short_eligible`：\(close_t <\) 下轨  

### 2.2 过滤条件（须全部满足才 `long_enter_ok` / `short_enter_ok`）

记 \(ATR_t\) = 近 20 日 True Range 均值（含当日 TR，与基线 ATR 一致）。

1. **实体确认（body / ATR）**  
   - 多：\((close_t - open_t) / ATR_t \ge 0.25\)（`BODY_ATR_MIN = 0.25`）  
   - 空：\((open_t - close_t) / ATR_t \ge 0.25\) 即 body_atr \(\le -0.25\)  
   - 含义：突破日要有足够「顺着方向的实体」，削弱针形假突破。

2. **成交量确认（相对先验均量，无泄漏）**  
   - \(vol\_sma\_prior_t = mean(volume_{t-20},\ldots,volume_{t-1})\)（rolling 20 再 `shift(1)`，**不含当日**）  
   - 要求：\(volume_t > vol\_sma\_prior_t\)

**入场池**：`long_enter_ok = long_eligible ∧ body_long_ok ∧ vol_confirm`（空头对称）。

**出场**：仍用原始 `long_eligible` / `short_eligible`。某日实体变弱或缩量**不会**因此强制平仓，避免过滤把持仓抖掉；只有通道门控翻转或调仓换标的才平。

未采用 ADX，是为了保持规则简单、可复现；体量 + 实体已覆盖「假突破过滤」的常见实务折中。

---

## 3. 等权仓位（精确公式）

在调仓日，设选中的多+空一共 \(n\) 个品种（`n_sel`），总名义杠杆上限 `GROSS_LEVERAGE = 1.0`（相对账户本金）：

\[
w_i = \frac{\text{GROSS\_LEVERAGE}}{n}
\]

\[
lots_i = \left\lfloor \frac{Capital \times w_i}{price_i \times multiplier_i} \right\rfloor
\]

- 若 \(lots_i < 1\)（一合约名义已超过预算）→ **开 0 手**（跳过该标的）。  
- 另有上限 `MAX_LOTS_PER_NAME = 50`。  
- 多头 `+lots`，空头 `-lots`。  
- 本金默认 `Capital = 1_000_000`。

与基线 ATR 仓位的区别：不再按波动缩手数，而是尽量让每个入选品种占用相近的资金名义；贵合约（如 AU、SC）在 \(n\) 较大时更容易买不起 1 手而被跳过。

---

## 4. 截面与调仓（与基线相同）

- 因子：`mom_20, mom_60, mom_120, low_vol(-vol_20), oi_chg_20`  
- 池内 robust-z（中位数/MAD）后等权合成  
- 做多池取分数最高约 25%；做空池取最低约 25%（池 \<4 则各取 1）  
- 每 5 个交易日调仓；费用：佣金万 1 + 1 tick 滑点（与基线一致）

---

## 5. 复现

```text
C:\Users\Administrator\Desktop\vnpy\.venv\Scripts\python.exe backtest_trend_xs_ew_filter.py
```

输出：

- `data\trend_xs_ew_filter_results\summary.json`
- `equity_curve.csv` / `trades.csv` / `report.txt`

---

## 6. 回测结果与基线对比

跑批时间：2026-10-27（Asia/Shanghai）。区间均为 `2009-09-30 -> 2026-10-27`（4159 交易日）。

| 指标 | 基线 ATR 20（无过滤） | 本版 EW+假突破过滤 |
|--|--|--|
| 总收益 | 11.0232% | **19.1291%** |
| 年化 | 0.6356% | **1.0662%** |
| 最大回撤 | **-22.3767%** | -37.8207% |
| 夏普 | 0.1251 | **0.1505** |
| 期末权益 | 1,110,232 | 1,191,291 |
| 开/平仓 | 753 / 753 | 544 / 544 |
| 胜率（平仓） | 42.23% | 43.93% |
| 调仓次数 | 832 | 832 |
| 过滤挡下（有门控未入场） | — | 734 |

解读（简）：收益与夏普略好于 ATR 基线，开仓更少（过滤生效）；但等权名义暴露往往更「满」，最大回撤明显加深（约 -38% vs -22%）。教学/对照有用，仍远未到可上线水平。

## 7. 注意

- 新浪主力连续，换月/跳空未建模。  
- 以信号日收盘成交，偏乐观。  
- 等权在贵合约上可能经常 0 手，实际暴露低于 `GROSS_LEVERAGE`。  
- 过滤用当日实体与成交量（在「收盘成交」假设下可接受）；均量严格用先验 20 日。  
- 历史回测 ≠ 未来收益。

