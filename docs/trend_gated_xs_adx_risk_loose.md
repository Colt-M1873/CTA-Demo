# 趋势门控 + 假突破过滤 + 截面等权（含 ADX）+ 组合风控层（**松**参数）

> 记录日期：2026-10-28（Asia/Shanghai）  
> 代码入口：`Desktop\vnpy\backtest_trend_xs_adx_risk.py --profile loose`  
> 策略模块：`Desktop\vnpy\strategies\trend_xs_adx_risk.py`（`RISK_PROFILES["loose"]` / `apply_risk_profile`）  
> 回测结果：`Desktop\vnpy\data\trend_xs_adx_risk_loose_results\`  
> 对照：无风控 `data\trend_xs_adx_results\`；紧风控 `data\trend_xs_adx_risk_results\`  
> 信号层（门控 / ADX 打分 / 假突破过滤 / 选股）不变，只放宽风控缩放与熔断。

---

## 1. 松版相对紧版改了什么

| 参数 | 紧（tight，默认） | **松（loose）** |
|--|--|--|
| `VOL_TARGET_ANNUAL` | 0.10 | **0.12** |
| `VOL_SCALE_MIN` | 0.10 | **0.25**（提高地板，少把仓压穿） |
| `GROSS_LEVERAGE_CAP` | 0.70 | **0.80** |
| `DD_HALF_THRESHOLD` | 0.10 | **0.15** |
| `DD_FLAT_THRESHOLD` | 0.15 | **0.25** |
| `DD_RECOVERY_THRESHOLD`（HALF→NORMAL） | 0.05 | **0.10** |
| `DD_FLAT_RECOVER_THRESHOLD`（FLAT→HALF） | 0.10 | **0.15** |

有效毛敞口公式不变：

\[
\text{eff\_gross} = \min(\text{RISK\_BASE\_GROSS}\times\text{vol\_scale},\;\text{GROSS\_LEVERAGE\_CAP}) \times \text{dd\_mult}
\]

---

## 2. 复现

```text
C:\Users\Administrator\Desktop\vnpy\.venv\Scripts\python.exe backtest_trend_xs_adx_risk.py --profile loose
C:\Users\Administrator\Desktop\vnpy\.venv\Scripts\python.exe backtest_trend_xs_adx_risk.py --profile tight
```

紧版仍写到 `data\trend_xs_adx_risk_results\`；松版写到 `data\trend_xs_adx_risk_loose_results\`。

---

## 3. 三方对比（同宇宙 40，2011-09-28 → 2026-10-27，3671 日）

| 指标 | ADX+40 无风控 | 紧风控 | **松风控** |
|--|--|--|--|
| 总收益 | **11.8913%** | −2.0182% | 7.9872% |
| 年化 | **0.7743%** | −0.1399% | 0.5289% |
| 最大回撤 | −24.0852% | **−15.1360%** | −19.5083% |
| 夏普 | **0.1256** | −0.0031 | 0.1107 |
| 期末权益 | 1,118,913 | 979,818 | 1,079,872 |
| 开/平仓 | 749 / 747 | 688 / 688 | 723 / 721 |
| 胜率（平仓） | 40.03% | 40.12% | 40.22% |
| HALF / FLAT 天数 | — | 2215 / 105 | **1231 / 0** |
| 平均 / 最大毛杠杆 | ~1.0 意图 | 0.09 / 0.73 | **0.13 / 0.86** |

**解读（简）：**

- 松版相对紧版：HALF 天数约减半，FLAT 天数为 0；平均毛杠杆从 ~0.09 提到 ~0.13；收益转正、夏普接近无风控。
- 相对无风控：回撤浅约 4.6 个百分点（−19.5% vs −24.1%），收益/夏普略低——仍是「少亏一点敞口换浅一点回撤」。
- 波动目标 + 杠杆帽仍是平均仓位偏低的主因；若还要抬敞口，可再试更高 `VOL_TARGET` 或关掉/放宽 vol floor。

---

## 4. 注意

- 新浪主力连续；换月/跳空未建模。  
- 波动缩放用调仓前历史权益收益，不含当日。  
- `RISK_PROFILES` / `apply_risk_profile` 可切换紧松，勿改信号参数。  
- 历史回测 ≠ 未来收益。
