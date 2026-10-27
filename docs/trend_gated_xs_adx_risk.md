# 趋势门控 + 假突破过滤 + 截面等权（含 ADX）+ 组合风控层

> 记录日期：2026-10-28（Asia/Shanghai）  
> 代码入口：`Desktop\vnpy\backtest_trend_xs_adx_risk.py`  
> 策略模块：`Desktop\vnpy\strategies\trend_xs_adx_risk.py`（信号复用 `trend_xs_adx`）  
> 回测结果：`Desktop\vnpy\data\trend_xs_adx_risk_results\`  
> 对照：`Desktop\vnpy\data\trend_xs_adx_results\`（同 40 商品、ADX、过滤、等权，**无**风控层）  
> **不含 XGBoost**；风控只缩放/阻断仓位，不改门控、ADX 打分、假突破过滤与选股。

---

## 1. 相对 ADX+40 版加了什么

| 项 | ADX+40（对照） | 本版 |
|--|--|--|
| 宇宙 / 因子 / 过滤 / 调仓 | 40 商品；六因子等权；假突破过滤；每 5 日 | **不变** |
| 底仓 | 等权，`GROSS_LEVERAGE=1.0` | 等权底仓意图相同，再套风控 |
| 组合波动目标 | 无 | **开**：目标年化约 **10%**，按 `target/realized` 缩放 |
| 总杠杆上限 | 名义约 1.0 | **开**：名义/权益 **≤ 0.70** |
| 回撤熔断 | 无 | **开**：见下节滞回规则 |

---

## 2. 风控参数与开关（均可在 `trend_xs_adx_risk.py` 改）

| 开关 / 参数 | 默认 | 含义 |
|--|--|--|
| `ENABLE_VOL_TARGET` | True | 组合波动目标 |
| `VOL_TARGET_ANNUAL` | 0.10 | 目标年化波动 ~10% |
| `VOL_LOOKBACK` | 20 | 用**过去**权益日收益估实现波动（不含当日，防前视） |
| `VOL_SCALE_MIN` / `MAX` | 0.10 / 1.50 | 缩放上下限 |
| `ENABLE_GROSS_LEVERAGE_CAP` | True | 总杠杆帽 |
| `GROSS_LEVERAGE_CAP` | **0.70** | 落在建议的 0.6–0.8 区间 |
| `RISK_BASE_GROSS` | 1.0 | 风控前底仓毛敞口意图 |
| `ENABLE_DD_CIRCUIT` | True | 回撤熔断 |
| `DD_HALF_THRESHOLD` | 0.10 | 峰回撤 >10% → 半仓 |
| `DD_FLAT_THRESHOLD` | 0.15 | 峰回撤 >15% → 空仓且禁止新开 |
| `DD_RECOVERY_THRESHOLD` | 0.05 | 半仓回到正常的恢复线 |

**有效毛敞口公式（调仓日）：**

\[
\text{eff\_gross} = \min(\text{RISK\_BASE\_GROSS}\times\text{vol\_scale},\;\text{GROSS\_LEVERAGE\_CAP}) \times \text{dd\_mult}
\]

再把 `eff_gross` 传入原来的 `equal_weight_lots(..., gross_leverage=eff_gross)`。实现波动不足样本时 `vol_scale=1.0`。

---

## 3. 回撤熔断与恢复（滞回）

状态机：`NORMAL`（倍数 1.0）→ `HALF`（0.5）→ `FLAT`（0）。

**升级（立即）：**

- 峰回撤 \(DD > 10\%\)：进入 `HALF`
- \(DD > 15\%\)：进入 `FLAT`——**强制平掉全部持仓**，且调仓日 `target` 为空（不开新仓）

**降级（滞回，避免在阈值附近抖动）：**

- `FLAT` → `HALF`：当 \(DD \le 10\%\)
- `HALF` → `NORMAL`：当 \(DD \le 5\%\)（`DD_RECOVERY_THRESHOLD`）

进入 `FLAT` 当日若已有仓会记 `dd_flat_force_close`；若本来已空仓则只保持空仓。恢复到 `HALF`/`NORMAL` 后须等下一次调仓才会重新开仓。

---

## 4. 复现

```text
C:\Users\Administrator\Desktop\vnpy\.venv\Scripts\python.exe backtest_trend_xs_adx_risk.py
```

输出：

- `data\trend_xs_adx_risk_results\summary.json`
- `equity_curve.csv`（含 `dd_state` / `gross_leverage`）
- `trades.csv` / `risk_rebalance_log.csv` / `report.txt`

---

## 5. 回测结果对比（同宇宙 40）

跑批时间：2026-10-28（Asia/Shanghai）。区间均为 2011-09-28 → 2026-10-27（3671 日）。

| 指标 | ADX+40 等权（无风控） | **本版 + 风控** |
|--|--|--|
| 总收益 | **11.8913%** | −2.0182% |
| 年化 | **0.7743%** | −0.1399% |
| 最大回撤 | −24.0852% | **−15.1360%** |
| 夏普 | **0.1256** | −0.0031 |
| 期末权益 | 1,118,913 | 979,818 |
| 开/平仓 | 749 / 747 | 688 / 688 |
| 胜率（平仓） | 40.03% | 40.12% |
| 调仓次数 | 735 | 735 |
| 过滤挡下 | 1195 | 1195（信号层相同） |
| HALF / FLAT 天数 | — | 2215 / 105 |
| 强制平仓笔数 | — | 0（FLAT 时账面多已空） |
| 平均 / 最大毛杠杆 | ~名义 1.0 意图 | **0.09 / 0.73** |

**解读（简）：**

- 风控按设计把最大回撤压到约 **−15%**（贴近 15% 空仓线），平均毛杠杆被压到约 **0.09**（波动目标 + 杠杆帽 + 长期 HALF 叠加）。
- 收益与夏普明显差于无风控对照：当前信号本身边沿偏弱，再大幅降仓后，成本与错过趋势占主导，净值略亏。
- 过滤拒绝次数与对照相同，说明信号层未改；差异来自仓位缩放与熔断。
- 若要在控回撤的同时少伤收益，可试：提高 `VOL_TARGET`、放宽 `GROSS_LEVERAGE_CAP`、或减弱 HALF 滞留（例如恢复线更松 / 半仓阈值提高）——需单独开关对照，本版先按约定默认跑通。

---

## 6. 注意

- 新浪主力连续；换月/跳空未建模。  
- 波动缩放用调仓前历史权益收益，不含当日。  
- 杠杆帽在 vol_scale 之后、DD 倍数最后乘。  
- 历史回测 ≠ 未来收益。

---

## 7. 参数化 profile

自本轮起，strategies\trend_xs_adx_risk.py 提供 RISK_PROFILES（	ight / loose）与 pply_risk_profile()。本文件描述的是 **tight**（默认）。松参数与三方对比见 docs\trend_gated_xs_adx_risk_loose.md；复现：acktest_trend_xs_adx_risk.py --profile tight|loose。

## 参数搜索更新
见 docs/trend_gated_xs_adx_risk_search.md。推荐 profile：search_best (vol15%/floor0.4/cap0.8/DD15-25)，样本内夏普约 0.14，仍远低于 0.6。
