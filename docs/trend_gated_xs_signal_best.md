# 当前最优夏普方案详解：signal_best（entry_40_rebal_10）

> 记录日期：2026-10-28（Asia/Shanghai）  
> 目标读者：策略入门者（希望把「原理 → 实现 → 回测数字」一次看清）  
> 配置组合：风险层 `--profile search_best` + 信号层 `--signal-profile signal_best`  
> 网格原名：`entry_40_rebal_10`（已注册为 `signal_best`）  
> 代码入口：`Desktop\vnpy\backtest_trend_xs_adx_risk.py`  
> 信号模块：`Desktop\vnpy\strategies\trend_xs_adx.py`  
> 风控模块：`Desktop\vnpy\strategies\trend_xs_adx_risk.py`  
> 主结果目录：`Desktop\vnpy\data\trend_xs_signal_signal_best_results\`  
> 同结果别名：`Desktop\vnpy\data\trend_xs_signal_entry_40_rebal_10_results\`  
> 网格汇总：`Desktop\vnpy\data\trend_xs_signal_search\`  
> 短版笔记：`docs\trend_gated_xs_signal_search.md`（本文是完整版）

---

## 1. 概述

**一句话**：用更长的唐奇安通道（40 日）当趋势门，再在假突破过滤后的候选池里，用六因子截面打分做多头部、做空尾部，每 10 个交易日调仓一次；仓位外面再套一层「波动目标 + 总敞口上限 + 回撤熔断」的 `search_best` 风控。

本文覆盖：

1. 每一层（门控 / 过滤 / 因子 / 选股 / 调仓 / 风控）**为什么存在、直觉上怎么起作用**；  
2. 数据从哪来、标的池多大、已知局限；  
3. 关键文件、命令行、**从代码 / JSON 抄出的真实参数表**；  
4. 回测区间、成本假设、指标定义；  
5. **只来自结果文件的数字**（主结果、基线对比、网格邻近组）；  
6. 解读、过拟合提醒、精确复现命令。

**不是**：实盘交易说明书，也不是「夏普已经到 0.6」的承诺。样本内最好夏普约 **0.47**，仍明显低于 0.6。

---

## 2. 策略原理

整体可以想成四层管道：

```text
日线 OHLC + 量 + 持仓量
        |
        v
① 唐奇安趋势门（允许多 / 允许空 / 平仓）
        |
        v
② 假突破过滤（实体/ATR + 成交量）——只挡新开，不改出场
        |
        v
③ 截面多因子打分 → 多空各选约 25% → 等权手数
        |
        v
④ 组合风控层（波动缩放 × 杠杆帽 × 回撤倍数）
```

风控**只缩放或阻断仓位**，不改门控、过滤、因子与选股逻辑。

### 2.1 唐奇安趋势门（时序门控）

对每个品种、每个交易日 \(t\)（通道长度 = `entry_window`，本方案为 **40**）：

- 上轨 = \(\max(high_{t-40},\ldots,high_{t-1})\)（**不含当日**，防前视）  
- 下轨 = \(\min(low_{t-40},\ldots,low_{t-1})\)  
- \(close_t >\) 上轨 → **只允许多**  
- \(close_t <\) 下轨 → **只允许空**  
- 否则 → 该品种门控为 flat  

**出场**：已有多头但不再 `long_eligible` → 平多；已有空头但不再 `short_eligible` → 平空。出场只看原始门控，**不一定等到调仓日**。

**直觉**：短通道（如 20）对噪音敏感，假突破多；拉长到 40，信号更稀、更「趋势确认」，换手下降。网格里「只改成 40、仍 5 日调仓」就已明显好于基线，说明通道长度是主要杠杆之一。

### 2.2 假突破过滤（只挡入场）

门控通过后，新开仓还要同时满足（本方案）：

| 条件 | 规则 | 参数 |
|--|--|--|
| 实体强度 | 多：\((close-open)/ATR_{20} \ge 0.25\)；空：\(\le -0.25\) | `body_atr_min=0.25` |
| 量能确认 | 当日成交量 \(>\) 先验 20 日均量（rolling 后 `shift(1)`） | `use_volume_filter=True` |

过滤失败只表示「今天不新开」；已有仓位的出场仍由唐奇安门控决定。

**直觉**：突破日若实体很弱或量能不足，更像试探/假突破。网格里关掉量能过滤的几组夏普直接变负，说明这层在本数据上很关键。

### 2.3 截面多因子（在同向合格池内打分）

每个调仓日，分别对「可新开多」池与「可新开空」池计算因子，再做 **median/MAD 稳健 z-score**，等权合成综合分。

| 因子 | 定义 | 方向含义 |
|--|--|--|
| `mom_20` | 近 20 日收益率 | 方向因子：越高越偏多 |
| `mom_60` | 近 60 日收益率 | 同上 |
| `mom_120` | 近 120 日收益率 | 同上 |
| `oi_chg_20` | 持仓量 20 日变化率 | 方向因子：增仓偏多 |
| `low_vol` | \(-\sigma\)(近 20 日日收益) | **非方向**：两侧都偏好相对低波 |
| `adx` | Wilder ADX(14)，当日收盘可知 | **非方向**：两侧都偏好趋势更强 |

空头池：对方向因子的 z **取反**，再与正向的 `adx` / `low_vol` 等权合成，然后取综合分**最高**的约 25%（即「强下跌趋势 + 相对低波」优先）。多头池直接取综合分最高约 25%。

历史不足的因子记 NaN，合成时跳过。同品种不会同时出现在多空两侧（门控互斥 + 代码守卫）。

**直觉**：门控只回答「能不能顺着突破方向做」；因子回答「同向里谁更值得做」。ADX 量的是趋势强度（不分多空），低波偏好降低嘈杂品种权重。

### 2.4 选股与等权底仓

- `select_pct = 0.25`：池子 \(\ge 4\) 时取前 \(floor(n \times 0.25)\) 个（至少 1）；池子 \(< 4\) 时只取 1 个。  
- 等权手数意图：`weight = gross_leverage / n_selected`，  
  `lots = floor(Capital × weight / (price × multiplier))`，单品种最多 **50** 手；买不起 1 手则跳过。  
- 风控会把这里的 `gross_leverage` 换成「有效毛敞口」`eff_gross`（见下节）。

### 2.5 调仓频率

本方案 **每 10 个交易日**调仓一次（主日历交易日计数，不是自然周）。

调仓时：不在目标列表或方向/手数不符 → 平仓；目标新腿 → 按收盘价开仓。门控平仓可在非调仓日发生。

**直觉**：5 日调仓对噪音更敏感、换手更高；拉到 10 日后，与 40 日通道搭配，开仓次数从基线约 721 降到约 275，成本与抖动一起下降。再拉到 20 日（同网格 `rebal_20`）夏普反而掉回约 0.22——不是越慢越好。

### 2.6 风控层（`search_best`，固定不动）

信号网格搜索时**风控锁死**为先前风控网格的优胜配置 `search_best`：

| 机制 | 参数 | 作用 |
|--|--|--|
| 组合波动目标 | 目标年化 **15%**，回看 20 日权益收益（不含当日） | `vol_scale = clip(target/realized, 0.40, 1.50)` |
| 总杠杆上限 | 名义/权益 **≤ 0.80** | 防止缩放后敞口过大 |
| 回撤熔断 | DD>**15%** → 半仓；DD>**25%** → 空仓并禁止新开 | 深回撤时降风险 |
| 恢复滞回 | FLAT→HALF 当 DD≤15%；HALF→NORMAL 当 DD≤10% | 避免在阈值附近反复抖动 |

有效毛敞口（调仓日）：

\[
\text{eff\_gross} = \min(\text{RISK\_BASE\_GROSS}\times\text{vol\_scale},\;\text{GROSS\_LEVERAGE\_CAP}) \times \text{dd\_mult}
\]

其中 `RISK_BASE_GROSS=1.0`，`dd_mult ∈ {1.0, 0.5, 0.0}`。实现波动样本不足时 `vol_scale=1.0`。

**直觉**：信号边沿偏弱时，若不限制总敞口与回撤，净值波动会很大；风控把平均毛杠杆压得很低（本方案约 **0.06**），用「少赚一点、回撤浅一点」换更稳的夏普。本方案样本内 **HALF/FLAT 天数均为 0**——40+10 日信号本身回撤未触发 15%/25% 线。

---

## 3. 数据与标的

### 3.1 数据来源

- AKShare / 新浪 **主力连续** 日线 CSV：`data\*_daily_main_sina.csv`  
- 字段：`datetime, open, high, low, close, volume, open_interest, settle`（策略主要用 OHLC + volume + open_interest）

### 3.2 商品池（40，无金融期货）

排除：`IF / IH / IC / IM / T / TF / TS / TL`。  
本次回测宇宙（来自 `summary.json`，共 **40**）：

`A, AG, AL, AU, B, BU, C, CF, CS, CU, EB, EG, FG, FU, HC, I, J, JD, JM, L, M, MA, NI, OI, P, PB, PP, RB, RM, RU, SA, SC, SN, SP, SR, TA, UR, V, Y, ZN`

主日历为各品种日期的**并集**；某日无 bar 则该品种不参与当日截面与开平仓。启动条件：至少约一半品种已具备 ≥ `MIN_HISTORY`（130）根历史。

### 3.3 已知局限（读数字前必看）

1. **主力连续合约**：换月、移仓价差、跳空**未建模**；连续价上的动量/突破与真实可交易合约有偏差。  
2. **简化成本**：佣金名义 × 0.0001 + 滑点 1 个最小变动价位；无保证金约束、无涨跌停无法成交、无夜盘分段。  
3. **成交假设**：信号日**收盘价**成交——偏乐观。  
4. **样本内搜索**：信号参数在全样本上网格优选，夏普等指标**偏乐观**，不能当样本外或实盘保证。  
5. 合约乘数 / 最小变动价位为代码内常用默认，仅影响手数与 PnL 尺度。

---

## 4. 实现细节

### 4.1 关键文件

| 路径 | 作用 |
|--|--|
| `backtest_trend_xs_adx_risk.py` | 回测入口；`--profile` / `--signal-profile` |
| `strategies\trend_xs_adx.py` | 门控、过滤、因子、选股、等权手数、`SIGNAL_PROFILES` |
| `strategies\trend_xs_adx_risk.py` | 风控缩放 / 熔断、`RISK_PROFILES`（含 `search_best`） |
| `backtest_trend_xs_signal_search.py` | 信号参数网格（生成 search 汇总） |
| `data\trend_xs_signal_search\best_config.json` | 优胜配置登记 |
| `data\trend_xs_signal_search\search_summary.csv` | 25 组网格指标 |

### 4.2 怎么跑（Windows）

```bat
cd C:\Users\Administrator\Desktop\vnpy
.\.venv\Scripts\python.exe backtest_trend_xs_adx_risk.py --profile search_best --signal-profile signal_best
```

输出目录：`data\trend_xs_signal_signal_best_results\`。

若要重跑整张信号网格（耗时更长）：

```bat
.\.venv\Scripts\python.exe backtest_trend_xs_signal_search.py
```

### 4.3 参数表（真值）

#### 信号层 `signal_best`（= `entry_40_rebal_10`）

来源：`SIGNAL_PROFILES["signal_best"]` 与 `best_config.json`。

| 参数 | 值 |
|--|--|
| `entry_window` | **40** |
| `select_pct` | **0.25** |
| `rebalance_every_n_days` | **10** |
| `body_atr_min` | **0.25** |
| `use_volume_filter` | **True** |
| `factor_cols` / `factor_set` | `mom_20, mom_60, mom_120, low_vol, oi_chg_20, adx` / **all** |
| `adx_window` | 14（Wilder） |
| `vol_sma_window` | 20 |
| `capital` | 1,000,000 |
| `commission_rate` | 0.0001 |
| `max_lots_per_name` | 50 |
| `sizing` | equal_weight_then_risk_overlay |

对照基线信号 `baseline`（同文件）：entry=**20**，select=0.25，rebal=**5**，bodyATR=0.25，vol_filter=True，factors=all。

#### 风险层 `search_best`

来源：`RISK_PROFILES["search_best"]` 与风控 `best_config.json`。

| 参数 | 值 |
|--|--|
| `enable_vol_target` | True |
| `vol_target_annual` | **0.15** |
| `vol_lookback` | 20 |
| `vol_scale_min` / `max` | **0.40** / 1.50 |
| `enable_gross_leverage_cap` | True |
| `gross_leverage_cap` | **0.80** |
| `risk_base_gross` | 1.0 |
| `enable_dd_circuit` | True |
| `dd_half_threshold` | **0.15** |
| `dd_flat_threshold` | **0.25** |
| `dd_recovery_threshold`（HALF→NORMAL） | **0.10** |
| `dd_flat_recover_threshold`（FLAT→HALF） | **0.15** |

### 4.4 信号与仓位计算流程（步骤清单）

每个交易日大致按下列顺序（详见 `run_backtest`）：

1. **更新特征**：对各品种算 Donchian 门、ATR、ADX、动量/低波/OI、实体比、量能确认 → `long_enter_ok` / `short_enter_ok`。  
2. **门控平仓**：持仓方向与当日 `long_eligible` / `short_eligible` 冲突则平仓（计成本）。  
3. **回撤状态机**：用调仓前权益相对峰值更新 NORMAL / HALF / FLAT；若进入 FLAT 则强制平仓并禁止新开。  
4. **若非调仓日**：只记账权益与毛杠杆，结束。  
5. **若为调仓日**：  
   - 用历史权益收益算 `vol_scale`（不含当日）；  
   - 算 `eff_gross`；若 FLAT 或 `eff_gross≈0` 则目标为空；  
   - 否则在 `long_enter_ok` / `short_enter_ok` 池内算综合分，各选 top `select_pct`；  
   - 对目标腿用 `equal_weight_lots(..., gross_leverage=eff_gross)` 定手数；  
   - 平掉不在目标或手数不符的仓，开新目标腿。  
6. **日终**：按收盘价盯市，写入权益曲线（含 `dd_state`、`gross_leverage`）。

---

## 5. 回测设置

| 项 | 值（来自结果文件 / 代码） |
|--|--|
| 区间 | **2011-09-28 → 2026-10-27** |
| 交易日数 | **3671** |
| 本金 | 1,000,000 |
| 佣金 | 成交名义 × **0.0001** |
| 滑点 | **1 个最小变动价位** × 乘数 × 手数 |
| 成交价 | 信号日收盘价 |
| 年化天数约定 | 252 |

### 评价指标定义（代码实现）

- **总收益** = \(equity_{end}/Capital - 1\)  
- **年化** = \((equity_{end}/Capital)^{252/N} - 1\)（\(N\) 为回测日数）  
- **最大回撤** = 权益相对历史峰值的最小百分比回撤  
- **夏普** = \(\mathrm{mean}(r_d)/\mathrm{std}(r_d) \times \sqrt{252}\)，\(r_d\) 为日权益收益率  
- **胜率** = 平仓笔中 `pnl > 0` 的比例  
- **毛杠杆** = 当日多空名义敞口绝对值之和 / 权益  

网格排序规则（信号搜索）：夏普 ↓ → 最大回撤（绝对值更浅）↓ → 总收益 ↓。

---

## 6. 回测结果

> 以下数字均来自已落盘文件，非手填估算。主结果：`data\trend_xs_signal_signal_best_results\summary.json`；网格：`data\trend_xs_signal_search\search_summary.csv` 与 `best_config.json`。

### 6.1 主结果：`signal_best` + `search_best`

| 指标 | 数值 |
|--|--|
| 夏普 | **0.4728** |
| 年化收益 | **2.8221%** |
| 总收益 | **49.9925%** |
| 最大回撤 | **−11.484%** |
| 期末权益 | 1,499,925.36 |
| 净盈亏 | +499,925.36 |
| 开仓 / 平仓 | 275 / 273 |
| 平仓胜率 | 42.49% |
| 调仓次数 | 368 |
| 过滤挡下（新开拒绝） | 365 |
| HALF / FLAT 天数 | **0 / 0** |
| 强制平仓笔数 | 0 |
| 平均 / 最大毛杠杆 | **0.0622 / 0.8061** |

### 6.2 与基线及更早版本对比

「基线」= 同一 `search_best` 风控 + 信号 `baseline`（entry20 / rebal5 / select25% / 全因子 / 过滤开）——即信号网格里的 `baseline` 行，也是风控搜索时的信号设定。

| 方案 | 夏普 | 年化% | 最大回撤% | 总收益% | 来源 |
|--|--|--|--|--|--|
| **signal_best**（本方案） | **0.4728** | **2.8221** | **−11.484** | **49.9925** | signal_best `summary.json` |
| 基线 entry20+rebal5 + search_best | 0.1442 | 0.7549 | −17.4845 | 11.5789 | search_summary `baseline`；亦见 `prior_search_best_risk` |
| ADX+40 等权、无风控 | 0.1256 | — | −24.0852 | 11.8913 | `prior_adx_40`（summary 内嵌对照） |

相对基线：夏普约 **0.14 → 0.47**，总收益约 **+12% → +50%**，最大回撤约 **−17.5% → −11.5%**。

### 6.3 信号网格邻近组（同风控 `search_best`）

完整 25 组见 `search_summary.csv`。下面摘录与优胜最相关的几组（按夏普排序前段 + 关掉量能的反例）：

| name | 夏普 | 年化% | 最大回撤% | 总收益% | entry | select | rebal | bodyATR | vol滤 | 因子 |
|--|--|--|--|--|--|--|--|--|--|--|
| **entry_40_rebal_10** | **0.4728** | **2.8221** | **−11.484** | **49.9925** | 40 | 0.25 | 10 | 0.25 | True | all |
| entry_40_select_15 | 0.4696 | 3.3329 | −14.5369 | 61.2204 | 40 | 0.15 | 5 | 0.25 | True | all |
| entry_40 | 0.4040 | 2.7183 | −14.9258 | 47.8008 | 40 | 0.25 | 5 | 0.25 | True | all |
| body_04 | 0.3758 | 2.1526 | −17.8852 | 36.3778 | 20 | 0.25 | 5 | 0.40 | True | all |
| entry_40_no_adx | 0.3731 | 2.4836 | −14.5638 | 42.9575 | 40 | 0.25 | 5 | 0.25 | True | no_adx |
| rebal_10（仅改调仓） | 0.1794 | 0.8110 | −17.1832 | 12.4874 | 20 | 0.25 | 10 | 0.25 | True | all |
| baseline | 0.1442 | 0.7549 | −17.4845 | 11.5789 | 20 | 0.25 | 5 | 0.25 | True | all |
| vol_off | −0.2742 | −1.7960 | −26.7795 | −23.2034 | 20 | 0.25 | 5 | 0.25 | **False** | all |

为何没选 `entry_40_select_15`：夏普几乎一样（0.4696 vs 0.4728），但回撤更深（约 −14.5% vs −11.5%）；排序规则在夏普接近时偏好更浅回撤，故推荐 `entry_40_rebal_10`。

### 6.4 结果目录里有什么

`data\trend_xs_signal_signal_best_results\`（与 `...\entry_40_rebal_10_results\` 内容对应）：

| 文件 | 内容 |
|--|--|
| `summary.json` | 结构化指标、宇宙、信号/风控参数、与先前方案对照 |
| `report.txt` | 人类可读一行摘要 |
| `equity_curve.csv` | 每日权益、收益、回撤状态、毛杠杆等 |
| `trades.csv` | 开平仓明细 |
| `risk_rebalance_log.csv` | 调仓日风控事件（vol_scale、eff_gross、dd 等） |

网格产物：`data\trend_xs_signal_search\search_summary.csv`、`best_config.json`。

---

## 7. 解读与局限

### 7.1 为什么 40 日通道 + 10 日调仓更好

1. **拉长通道贡献最大**：仅 `entry_40`（仍 5 日调仓）夏普已到 0.404，远高于基线 0.144——假突破减少、趋势更「干净」。  
2. **再降调仓频率加分**：在 40 的基础上改成 10 日，夏普到 0.473，回撤最浅；开仓从约 590+ 降到 275，过滤拒绝也从约 739 降到 365。  
3. **单独放慢调仓不够**：`rebal_10` 仍用 entry20 时夏普只有 0.179——说明「慢调仓」要和「长通道」一起才稳。  
4. **量能过滤不可关**：`vol_off` 等组夏普为负；放宽实体门槛（`body_015`）也变差。  
5. **风控几乎没被触发熔断**：HALF/FLAT=0，平均毛杠杆仅约 0.06——收益提升主要来自信号层更干净，波动目标仍把仓位压得很克制。

### 7.2 为何仍不到夏普 0.6

- 同一方案骨架上，只拧 Donchian / 选股比例 / 调仓间隔 / 过滤 / 因子子集，样本内天花板大约就在 **0.45–0.48** 一带。  
- 数据是主力连续 + 收盘成交 + 简化成本，真实可交易夏普通常更低，不是更高。  
- 年化约 2.8%、平均杠杆约 0.06：策略偏「低频、低仓」；要把夏普再抬到 0.6+，更可能需要更干净的合约数据、更丰富/更稳健的因子或不同的方案骨架，而不是继续穷举这几个开关。

### 7.3 样本内过拟合提醒

- 优胜配置是在 **全样本 25 组**里按夏普（及回撤、收益）选出来的，存在明显的**挑选偏差**。  
- 未做严格的样本外切割或 walk-forward 参数冻结验证（波动缩放本身用历史权益，但**参数选择**是全样本的）。  
- 邻近组 `entry_40_select_15` 夏普几乎并列——说明「唯一最优」并不尖锐，实盘前应做稳健性检查。

### 7.4 不写虚假实盘承诺

历史回测 ≠ 未来收益。本文数字只描述「在当前脚本、当前 CSV、当前成本假设下跑出来的样本内结果」。不构成投资建议，也不能保证实盘夏普、回撤或收益。

---

## 8. 复现与后续

### 8.1 精确复现

```bat
cd C:\Users\Administrator\Desktop\vnpy
.\.venv\Scripts\python.exe backtest_trend_xs_adx_risk.py --profile search_best --signal-profile signal_best
```

预期：写出 `data\trend_xs_signal_signal_best_results\`，夏普约 **0.4728**，年化约 **2.8221%**，最大回撤约 **−11.484%**，总收益约 **49.9925%**（与已存 `summary.json` / `best_config.json` 一致）。

登记信息见：

- `data\trend_xs_signal_search\best_config.json` → `registered_as: signal_best`  
- `strategies\trend_xs_adx.py` → `SIGNAL_PROFILES["signal_best"]`

### 8.2 相关文档

| 文档 | 内容 |
|--|--|
| `docs\trend_gated_xs_signal_search.md` | 信号网格短笔记 |
| `docs\trend_gated_xs_adx_risk_search.md` | 风控网格与 `search_best` |
| `docs\trend_gated_xs_adx_risk.md` | 风控层原理（默认 tight 描述 + 指向 search） |
| `docs\trend_gated_xs_adx.md` | 40 商品 + ADX + 假突破（无风控） |
| `docs\trend_gated_xs_multifactor.md` | 更早的多因子门控教程向说明 |

### 8.3 可选下一步（不展开实现）

若还想往更高夏普靠近：优先考虑**更接近真实可交易**的连续/换月处理与成本，或引入经样本外验证的新因子/方案；单靠再拧 Donchian、选股比例和调仓间隔，本网格已经显示空间不大。

---

*文档数字核对来源：`data\trend_xs_signal_signal_best_results\summary.json`、`report.txt`；`data\trend_xs_signal_search\search_summary.csv`、`best_config.json`；`strategies\trend_xs_adx.py` / `trend_xs_adx_risk.py`。*
