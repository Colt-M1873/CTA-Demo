# vnpy CTA 学习仓库

> 面向：想用 **VeighNa（vnpy）+ 本地回测** 学习商品期货 CTA / 截面趋势思路的初学者  
> 定位：**研究与学习用**，以本地日线回测为主；**不是**生产级实盘交易系统  
> 当前最优配置：风险层 `search_best` + 信号层 `signal_best`（网格名 `entry_40_rebal_10`）  
> 详细方案文档：[`docs/trend_gated_xs_signal_best.md`](docs/trend_gated_xs_signal_best.md)

---

## 1. 这个仓库是什么

本仓库在 Windows 本机上搭了一套「下载公开期货日线 → 写策略规则 → 跑回测 → 记文档」的学习流水线，围绕 **商品期货趋势门控 + 截面多因子** 展开，并叠了假突破过滤与组合风控。

它同时保留了：

- **vnpy / vnpy_ctp** 环境说明与 SimNow 连接脚本（见根目录 `README.txt`、`connect_simnow_ctp.py`）——方便以后接仿真行情；  
- 一系列 **自写的日线回测脚本**（不依赖 GUI），用来快速迭代 CTA 想法。

请按「学习笔记仓库」来用：数字来自当前脚本与 CSV，**历史回测 ≠ 未来收益**，也 **不构成投资建议**。

---

## 2. 主要做了什么（演进路线）

从简单到复杂，大致走了这些步（对应 `docs/` 与 `backtest_trend_xs_*.py`）：

| 阶段 | 内容 | 代表入口 / 文档 |
|--|--|--|
| 数据 | 用 AKShare 拉新浪财经主力连续日线，扩到约 40 商品（另有部分金融） | `download_akshare_*.py` |
| 单品种趋势 | 唐奇安等经典通道想法 | `backtest_donchian.py`、`strategies/donchian_channel.py` |
| 趋势门控 + 截面 | Donchian 决定多空资格，池内用动量等因子选股 | `docs/trend_gated_xs_multifactor.md` |
| 假突破过滤 | 实体/ATR + 成交量确认，只挡新开 | `docs/trend_gated_xs_ew_filter.md` |
| 扩池 + ADX | 40 商品；因子加入 Wilder ADX(14) | `docs/trend_gated_xs_adx.md` |
| 组合风控 | 波动目标、总敞口上限、回撤熔断 | `docs/trend_gated_xs_adx_risk.md` |
| 风控网格 | 固定信号，搜风控参数 → `search_best` | `docs/trend_gated_xs_adx_risk_search.md` |
| 信号网格 | 固定 `search_best`，搜通道/调仓/过滤/因子 → `signal_best` | `docs/trend_gated_xs_signal_search.md`、**`docs/trend_gated_xs_signal_best.md`** |

另有 XGBoost 尝试文档（`trend_gated_xs_xgb*.md`），**当前推荐主线仍是规则多因子 + 风控**，不是 ML 主路径。

**当前最佳组合（样本内）：**

```text
python backtest_trend_xs_adx_risk.py --profile search_best --signal-profile signal_best
```

---

## 3. 数据从哪里来

### 3.1 来源与接口

- 库：**AKShare**  
- 接口：`ak.futures_zh_daily_sina(symbol=...)`（新浪财经期货日线；主力连续常用如 `RB0`、`AG0`）  
- 下载脚本示例：
  - `download_akshare_rb.py` —— 单品种试拉  
  - `download_akshare_multi.py` / `download_akshare_commodity_expand20.py` / `expand40.py` —— 扩商品池  
  - `download_akshare_financial.py` —— 部分金融期货（策略主宇宙会排除）

落盘位置：`data/<SYMBOL>_daily_main_sina.csv`（本地约有 **48** 个该类文件；策略主回测用其中 **40** 个商品）。

### 3.2 字段（CSV 表头）

```text
datetime, open, high, low, close, volume, open_interest, settle
```

策略主要用：OHLC、成交量、持仓量（`open_interest`）。

### 3.3 策略用的商品宇宙（40，无金融）

排除股指 / 国债等：`IF, IH, IC, IM, T, TF, TS, TL`。

当前最优回测宇宙（来自结果 `summary.json`）：

`A, AG, AL, AU, B, BU, C, CF, CS, CU, EB, EG, FG, FU, HC, I, J, JD, JM, L, M, MA, NI, OI, P, PB, PP, RB, RM, RU, SA, SC, SN, SP, SR, TA, UR, V, Y, ZN`

区间（`signal_best` 结果）：**2011-09-28 → 2026-10-27**，共 **3671** 个交易日。

### 3.4 数据局限（务必读）

这是本仓库**最大的硬伤之一**，也是后续优先要改的方向：

1. **主力连续合约拼接**  
   新浪 / AKShare 给出的是「主力连续」序列，不是你在某一时刻真实可交易的具体合约。换月如何跳接、是否复权、跳空如何处理，**本地没有严格建模**。

2. **跨月 / 换月成本未计入**  
   真实 CTA 在换月时有价差、滑点、移仓规则；在连续价上算动量与突破，和「拿真实合约滚动交易」不是一回事。用户侧共识：**数据质量和跨月处理是很大的问题，后续需要换质量更好的数据**。

3. **简化交易成本**  
   回测里大致是：佣金 = 名义 × `0.0001`，滑点 = 1 个最小变动价位；按**信号日收盘价**成交。无保证金约束、无涨跌停无法成交、无夜盘分段。

4. **样本内搜参偏乐观**  
   风控网格、信号网格都在全样本上选「夏普最好」，存在挑选偏差；样本外很可能变差。

**结论**：当前 CSV 适合「把管道跑通、理解规则、对比想法」；**不适合**当作上实盘前的最终验证数据。换数据时应优先考虑：明确合约规则的连续序列或可复现的换月日历、可核对的复权/未复权选择、以及更贴近实盘的成本假设。

---

## 4. 当前方案详解（`signal_best` + `search_best`）

完整说明见 [`docs/trend_gated_xs_signal_best.md`](docs/trend_gated_xs_signal_best.md)。这里是压缩版。

### 4.1 四层结构

```text
日线 OHLC + 量 + 持仓量
        |
        v
① 唐奇安趋势门（允许多 / 允许空 / 平仓）
        |
        v
② 假突破过滤（实体/ATR + 成交量）——只挡新开
        |
        v
③ 截面六因子打分 → 多空各选约 25% → 等权手数
        |
        v
④ 组合风控（波动缩放 × 杠杆帽 × 回撤倍数）
```

风控**只缩放或阻断仓位**，不改信号层。

### 4.2 信号层真参数（`signal_best`）

| 参数 | 值 |
|--|--|
| 唐奇安 `entry_window` | **40** |
| 选股比例 `select_pct` | **0.25** |
| 调仓 `rebalance_every_n_days` | **10** |
| 假突破 `body_atr_min` | **0.25**（\|实体\|/ATR） |
| 量能过滤 | **开**（量 > 先验 20 日均量） |
| 因子 | `mom_20, mom_60, mom_120, low_vol, oi_chg_20, adx`（等权 robust-z） |
| 仓位意图 | 等权名义；单品种最多 50 手；再乘风控有效毛敞口 |

要点直觉：

- **40 日通道**：比 20 日更少假突破，信号更稀。  
- **假突破过滤**：弱实体或无放量则不新开；出场仍只看唐奇安门。  
- **截面因子**：同向池里比「谁更值得做」；空头侧对动量/OI 的 z 取反，ADX 与低波两侧都正向偏好「强趋势 + 相对低波」。  
- **10 日调仓**：与长通道搭配，降低换手（开仓约 275 次 vs 基线约 721）。

### 4.3 风控层真参数（`search_best`）

| 参数 | 值 |
|--|--|
| 波动目标年化 | **15%**（回看 20 日权益收益，不含当日） |
| `vol_scale` 上下限 | **0.40 ~ 1.50** |
| 总杠杆上限 | **0.80**（名义/权益） |
| 回撤半仓 / 空仓 | DD > **15%** / **25%** |
| 恢复滞回 | FLAT→HALF ≤15%；HALF→NORMAL ≤10% |

本方案样本内 HALF/FLAT 天数均为 **0**；平均毛杠杆约 **0.06**（仓位被波动目标压得很克制）。

### 4.4 代码位置

| 文件 | 作用 |
|--|--|
| `backtest_trend_xs_adx_risk.py` | 回测入口（`--profile` / `--signal-profile`） |
| `strategies/trend_xs_adx.py` | 门控、过滤、因子、选股、`SIGNAL_PROFILES` |
| `strategies/trend_xs_adx_risk.py` | 风控与 `RISK_PROFILES` |
| `backtest_trend_xs_signal_search.py` | 信号参数网格 |
| `backtest_trend_xs_adx_risk_search.py` | 风控参数网格 |

---

## 5. 回测结果（样本内，勿当实盘保证）

数字来源：`data/trend_xs_signal_signal_best_results/summary.json`、`data/trend_xs_signal_search/best_config.json`。

### 5.1 当前最优 `signal_best` + `search_best`

| 指标 | 数值 |
|--|--|
| 夏普 | **0.4728** |
| 年化 | **2.8221%** |
| 总收益 | **49.9925%** |
| 最大回撤 | **−11.484%** |
| 期末权益（本金 100 万） | 1,499,925.36 |
| 开仓 / 胜率 | 275 / 42.49% |
| 平均 / 最大毛杠杆 | 0.0622 / 0.8061 |

### 5.2 与基线对比

基线 = 同一风控 `search_best` + 信号 entry**20** / 调仓**5** 日（网格中的 `baseline`）：

| 方案 | 夏普 | 年化% | 最大回撤% | 总收益% |
|--|--|--|--|--|
| **signal_best** | **0.4728** | **2.8221** | **−11.484** | **49.9925** |
| 基线 entry20+rebal5 | 0.1442 | 0.7549 | −17.4845 | 11.5789 |

夏普从约 **0.14 → 0.47**，回撤变浅，但仍 **明显低于 0.6**。信号网格显示：再拧 Donchian / 选股 / 调仓，天花板大约就在 0.45–0.48；关掉量能过滤会变差甚至为负。

**提醒**：全是**样本内**优选；连续合约 + 收盘成交 + 简化成本 → 数字**偏乐观**。

更多表格与邻近组：`docs/trend_gated_xs_signal_best.md`、`data/trend_xs_signal_search/search_summary.csv`。

---

## 6. 当前问题与后续方向

### 6.1 已经暴露的问题

1. **数据质量与跨月处理（最大问题）**  
   主力连续拼接方式不透明；换月价差、移仓规则、真实可交易合约序列都未建模。这会直接污染趋势门、动量因子和回测盈亏。  
   **后续必须换质量更好、规则更清晰的数据**（原则：可复现的换月日历、明确复权/未复权、能量化移仓成本；具体供应商需自行调研与合规使用，本 README 不做承诺）。

2. **成本与成交假设过简**  
   固定费率 + 1 tick 滑点 + 收盘成交，偏乐观。

3. **样本内网格过拟合风险**  
   `search_best` / `signal_best` 都是全样本按夏普（再比回撤、收益）选的；邻近组夏普接近，说明「唯一最优」并不尖锐。

4. **夏普天花板**  
   在同一骨架上拧开关，样本内最好约 0.47，到不了 0.6；继续穷举这几个旋钮收益有限。

5. **学习仓库 ≠ 生产系统**  
   合约乘数/最小变动为代码内常用默认；无完整风控中台、无合规与运维。

### 6.2 建议的后续（原则）

- 先换/校准数据与换月处理，再谈调参；  
- 换数据后应用**冻结参数**或样本外 / walk-forward 重估，而不是在新数据上立刻重新网格「刷夏普」；  
- 成本模型向真实佣金、滑点、保证金靠拢；  
- 文档与代码保持「数字可溯源到 CSV/JSON」。

---

## 7. 怎么跑

### 7.1 环境说明

- 本机可有 `.venv/`、内嵌 `python/` / `python313/`——**已在 `.gitignore` 中排除**，不会也不应整包推进 GitHub。  
- 环境安装备忘仍写在根目录 **`README.txt`**（Python 3.13、vnpy 4.5.0、vnpy_ctp、清华源、SimNow 连接步骤等）。  
- 适合进仓库的是：**代码 + `docs/` + `data/`（日线与回测结果）+ 本 README**。

激活示例（PowerShell）：

```powershell
C:\Users\Administrator\Desktop\vnpy\.venv\Scripts\Activate.ps1
cd C:\Users\Administrator\Desktop\vnpy
```

或不激活，直接：

```powershell
C:\Users\Administrator\Desktop\vnpy\.venv\Scripts\python.exe ...
```

### 7.2 复现当前最优回测

```bat
cd C:\Users\Administrator\Desktop\vnpy
.\.venv\Scripts\python.exe backtest_trend_xs_adx_risk.py --profile search_best --signal-profile signal_best
```

输出目录：`data\trend_xs_signal_signal_best_results\`  
（另有别名目录 `data\trend_xs_signal_entry_40_rebal_10_results\`）

可选：重跑信号网格（较慢）

```bat
.\.venv\Scripts\python.exe backtest_trend_xs_signal_search.py
```

### 7.3 重新拉数据（可选）

按需运行 `download_akshare_*.py`。注意接口与网络限制；拉完请核对 CSV 行数与日期连续性，**不要默认「下完就等于高质量」**。

### 7.4 SimNow（可选，仿真）

凭证填在 `simnow_ctp_setting.json`（勿提交真实账号密码）。连接脚本：`connect_simnow_ctp.py`。细节见 `README.txt`。仿真连通 ≠ 策略已可实盘。

---

## 8. 目录结构（简图）

```text
vnpy/
├── README.md                 # 本文件（仓库主入口）
├── README.txt                # 本机 venv / vnpy_ctp / SimNow 安装备忘
├── .gitignore                # 忽略 .venv、内嵌 python、缓存、密钥等
├── download_akshare_*.py     # 数据下载
├── backtest_*.py             # 各类回测入口
├── connect_simnow_ctp.py     # SimNow CTP 连接示例
├── subscribe_simnow_tick.py
├── simnow_ctp_setting.json   # 本地凭证（勿提交隐私）
├── strategies/               # 策略与因子 / 风控模块
│   ├── trend_xs_adx.py
│   ├── trend_xs_adx_risk.py
│   ├── trend_xs_multifactor.py
│   └── ...
├── docs/                     # 中文实验记录（推荐从 signal_best 读起）
│   ├── trend_gated_xs_signal_best.md
│   ├── trend_gated_xs_signal_search.md
│   ├── trend_gated_xs_adx_risk_search.md
│   └── ...
└── data/
    ├── *_daily_main_sina.csv           # 日线
    ├── trend_xs_signal_search/         # 信号网格汇总
    ├── trend_xs_signal_signal_best_results/
    └── ...                             # 各阶段回测结果
```

本地还会有 `.venv/`、`python313/` 等，体积大且已忽略，**不必也不应**当作仓库主体推送。

---

## 9. 文档导航

| 想了解… | 打开 |
|--|--|
| **当前最优方案（原理→实现→数字）** | [`docs/trend_gated_xs_signal_best.md`](docs/trend_gated_xs_signal_best.md) |
| 信号参数网格短笔记 | `docs/trend_gated_xs_signal_search.md` |
| 风控网格与 `search_best` | `docs/trend_gated_xs_adx_risk_search.md` |
| 风控层原理 | `docs/trend_gated_xs_adx_risk.md` |
| 40 商品 + ADX（无风控） | `docs/trend_gated_xs_adx.md` |
| 更早的多因子教程向说明 | `docs/trend_gated_xs_multifactor.md` |
| 本机 vnpy / SimNow 安装 | `README.txt` |

---

## 10. 免责声明

- 本仓库用于编程与量化研究学习。  
- 所有回测指标仅对应当前脚本、当前 CSV 与当前成本假设。  
- **不保证**实盘可盈利；**不提供**投资顾问服务。  
- 使用期货仿真或实盘前，请自行确认合规要求、资金风险与数据授权。

---

*指标核对：`data/trend_xs_signal_search/best_config.json`（Sharpe 0.4728 / 年化 2.8221% / DD −11.484% / 总收益 49.9925%）；详述见 `docs/trend_gated_xs_signal_best.md`。*
