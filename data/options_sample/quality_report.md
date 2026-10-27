AKShare 期权链样例数据质量报告
生成时间: 2026-10-27 (Asia/Shanghai)
akshare 版本: 1.19.3
输出目录: C:\Users\Administrator\Desktop\vnpy\data\options_sample
复现脚本: C:\Users\Administrator\Desktop\vnpy\fetch_option_chain_sample.py

================================================================
一、结论摘要
================================================================
1) 沪深300：能拉到当日/近期期权链快照，适合学习链结构；上交所 300ETF 单合约可拿到希腊值+隐含波动率。
2) 商品（黄金/沪铜/螺纹钢）：新浪链表可作快照；上期所可给某交易日全合约日统计，以及「合约系列」隐含波动率。
3) 波动率套利原型：整体不够。缺按行权价可回放的长期 IV 曲面与完整历史链；单合约日线历史极浅；SHFE 的 IV 是系列级不是 strike 级。
4) 学习/演示够用；正经 vol arb 回测不够，建议 RQData/券商数据。

================================================================
二、沪深300 / 金融期权 —— 成功样例
================================================================
API: option_cffex_hs300_list_sina() + option_cffex_hs300_spot_sina(symbol='io2611')
  文件: option_cffex_hs300_spot_sina_symbol-io2611.csv
  行数: 30  列数: 17
  列: ['看涨合约-买量', '看涨合约-买价', '看涨合约-最新价', '看涨合约-卖价', '看涨合约-卖量', '看涨合约-持仓量', '看涨合约-涨跌', '行权价', '看涨合约-标识', '看跌合约-买量', '看跌合约-买价', '看跌合约-最新价', '看跌合约-卖价', '看跌合约-卖量', '看跌合约-持仓量', '看跌合约-涨跌', '看跌合约-标识']
  字段: 行权价=有；看涨/看跌分列=有；最新/买/卖/量/持仓=有；IV=无；希腊值=无
  空值率: 关键价量列本次抽查基本无空
  质量: 可用于链快照；不可直接做 IV 曲面

API: option_finance_board(symbol='沪深300股指期权', end_month='2511')
  文件: option_finance_board_symbol-沪深300股指期权_end_month-2511.csv
  行数: 60  列: ['instrument', 'position', 'volume', 'lastprice', 'updown', 'bprice', 'bamount', 'sprice', 'samount']
  字段: instrument 含 C/P+行权价；last/bid/ask/volume/OI=有；IV=无
  质量: 月度链快照，学习够用（同接口 2512/2601/2603 亦成功）

API: option_finance_board(symbol='华泰柏瑞沪深300ETF期权', end_month='2511')
  文件: option_finance_board_symbol-华泰柏瑞沪深300ETF期权_end_month-2511.csv
  行数: 28  列: ['日期', '合约交易代码', '当前价', '涨跌幅', '前结价', '行权价', '数量']
  字段: 合约代码含 C/P；行权价；当前价；无完整买卖分档、无IV
  质量: ETF 期权链快照可用；华夏沪深300ETF期权同接口本次多次为空

API: option_cffex_hs300_daily_sina(symbol=...)
  文件: option_cffex_hs300_daily_sina_symbol-io2611C3600.csv
  行数: 2  列: ['date', 'open', 'high', 'low', 'close', 'volume']
  质量: 仅 OHLC+volume，历史极浅（本次约 2 根），不能当研究级历史深度

API: option_sse_list_sina / option_sse_codes_sina / option_sse_greeks_sina / option_sse_spot_price_sina
  文件: option_sse_greeks_sina_10012661.csv
  形态: 字段-值两列竖表
  字段名预览: ['期权合约简称', '成交量', 'Delta', 'Gamma', 'Theta', 'Vega', '隐含波动率', '最高价', '最低价', '交易代码', '行权价', '最新价', '理论价值']
  质量: 单合约含 Delta/Gamma/Theta/Vega/隐含波动率；拼整条链需对每个代码循环，不是一次返回全链 IV

失败/不可用:
- option_current_em: ProxyError（东财接口被代理拦住）
- option_finance_board('华夏沪深300ETF期权', ...): 多次 empty

================================================================
三、商品期货期权 —— 成功样例
================================================================
API: option_commodity_contract_sina('黄金期权') + option_commodity_contract_table_sina(..., 'au2612')
  文件: option_commodity_contract_table_sina_symbol-黄金期权_contract-au2612.csv
  行数: 88  列: ['看涨合约-买量', '看涨合约-买价', '看涨合约-最新价', '看涨合约-卖价', '看涨合约-卖量', '看涨合约-持仓量', '看涨合约-涨跌', '行权价', '看涨合约-看涨期权合约', '看跌合约-买量', '看跌合约-买价', '看跌合约-最新价', '看跌合约-卖价', '看跌合约-卖量', '看跌合约-持仓量', '看跌合约-涨跌', '看跌合约-看跌期权合约']
  字段: 行权价=有；看涨/看跌分列=有；买/卖/最新/量/持仓=有；IV=无
  看跌侧空值率: {'看跌合约-买量': '1.1%', '看跌合约-买价': '1.1%', '看跌合约-最新价': '1.1%', '看跌合约-卖价': '1.1%', '看跌合约-卖量': '1.1%', '看跌合约-持仓量': '1.1%', '看跌合约-涨跌': '1.1%', '看跌合约-看跌期权合约': '0.0%'}
  质量: 商品链快照好用；无现成 IV 列

API: option_commodity_contract_table_sina('沪铜期权', ...)
  文件: option_commodity_contract_table_sina_symbol-沪铜期权_contract-cu2612.csv  行数: 27
  质量: 同黄金，链快照可用，无IV

API: option_commodity_contract_table_sina('螺纹钢期权', ...)
  文件: option_commodity_contract_table_sina_symbol-螺纹钢期权_contract-rb2701.csv  行数: 16
  质量: 同黄金，链快照可用，无IV

注意: 新浪商品接口铜的 symbol 是「沪铜期权」，不是「铜期权」（后者 KeyError）。上期所 hist/vol 则用「铜期权」。

API: option_hist_shfe(symbol='黄金期权', trade_date='20261027')
  文件: option_hist_shfe_symbol-黄金期权_trade_date-20261027.csv
  行数: 776  列: ['合约代码', '开盘价', '最高价', '最低价', '收盘价', '前结算价', '结算价', '涨跌1', '涨跌2', '成交量', '持仓量', '持仓量变化', '成交额', '德尔塔', '行权量']
  关键空值率: {'开盘价': '65.2%', '最高价': '65.2%', '最低价': '65.2%', '收盘价': '0.0%', '结算价': '0.0%', '持仓量': '0.0%', '成交量': '0.0%'}
  字段: 合约代码可解析 C/P+行权；结算/持仓有；开高低大量为空（约65%）；IV=无
  质量: 某日全市场截面日统计可用；长历史需按日循环，且仍缺 strike 级 IV

API: option_vol_shfe(symbol='黄金期权', trade_date='20261027')
  文件: option_vol_shfe_symbol-黄金期权_trade_date-20261027.csv
  行数: 7  列: ['合约系列', '成交量', '持仓量', '持仓量变化', '成交额', '行权量', '隐含波动率']
  隐含波动率空值率: 14.3%
  质量: 有 IV，但是「合约系列」一层（如 au2612），不是每个 strike 的 IV 曲面

API: option_hist_shfe('铜期权','20261027') 行数=378；option_vol_shfe 同期亦成功（系列IV）

API: option_commodity_hist_sina  示例: option_commodity_hist_sina_symbol-au2612C648.csv 行数=12 列=['date', 'open', 'high', 'low', 'close', 'volume']
  质量: 单合约日线，深度很浅（黄金样例约十几根/甚至1根），研究级历史不够

================================================================
四、字段齐备性对照
================================================================
用途 | 沪深300 | 商品(金/铜/螺纹)
当日链快照(行权价+C/P+价量) | 够用(CFFEX板/新浪spot/ETF板) | 够用(新浪table)
买卖价 | 股指板/新浪有 | 新浪有
持仓量 | 有 | 有
单点 IV / 希腊值 | SSE greeks 单合约有 | SHFE vol 仅系列级IV
按行权价的历史 IV 曲面 | 无 | 无
长历史可回放全链 | 无 | 无（可按日爬 SHFE 截面，仍无 strike IV）

================================================================
五、对波动率套利够不够？
================================================================
不够作为完整 vol arb 回测数据栈，原因：
- 公开源以当日/近期快照为主；历史要么极浅（新浪日线），要么是按日截面且缺 strike 级 IV（上期所）。
- 金融侧单合约可取到隐含波动率与希腊值，但拼全链+长时间序列成本高、稳定性差。
- 商品侧 option_vol_shfe 的 IV 是合约系列汇总，做不了垂直价差/曲面套利的精细回测。
够用的场景：认清期权链字段、做当日截面演示、用标的价格粗算历史波动率作对比实验。
下一步若要认真做：RQData / 券商期权行情与 IV。

================================================================
六、本次产出文件
================================================================
- fetch_results.json  (23782 bytes)
- option_cffex_hs300_daily_sina_symbol-io2611C3600.csv  (114 bytes)
- option_cffex_hs300_list_sina_dict.json  (122 bytes)
- option_cffex_hs300_spot_sina_symbol-io2611.csv  (3063 bytes)
- option_commodity_contract_sina_symbol-沪铜期权.csv  (119 bytes)
- option_commodity_contract_sina_symbol-螺纹钢期权.csv  (58 bytes)
- option_commodity_contract_sina_symbol-黄金期权.csv  (68 bytes)
- option_commodity_contract_table_sina_symbol-沪铜期权_contract-cu2612.csv  (3126 bytes)
- option_commodity_contract_table_sina_symbol-螺纹钢期权_contract-rb2701.csv  (1856 bytes)
- option_commodity_contract_table_sina_symbol-黄金期权_contract-au2612.csv  (8642 bytes)
- option_commodity_contract_table_sina_symbol-黄金期权_contract-au2702.csv  (6250 bytes)
- option_commodity_hist_sina_symbol-au2612C648.csv  (520 bytes)
- option_commodity_hist_sina_symbol-au2702C680.csv  (74 bytes)
- option_finance_board_symbol-华泰柏瑞沪深300ETF期权_end_month-2511.csv  (1778 bytes)
- option_finance_board_symbol-华泰柏瑞沪深300ETF期权_end_month-2512.csv  (2260 bytes)
- option_finance_board_symbol-华泰柏瑞沪深300ETF期权_end_month-2603.csv  (2010 bytes)
- option_finance_board_symbol-沪深300股指期权_end_month-2511.csv  (2960 bytes)
- option_finance_board_symbol-沪深300股指期权_end_month-2512.csv  (3125 bytes)
- option_finance_board_symbol-沪深300股指期权_end_month-2601.csv  (2032 bytes)
- option_finance_board_symbol-沪深300股指期权_end_month-2603.csv  (1818 bytes)
- option_hist_shfe_symbol-铜期权_trade_date-20261027.csv  (30414 bytes)
- option_hist_shfe_symbol-黄金期权_trade_date-20261027.csv  (55377 bytes)
- option_sse_codes_sina_看涨期权_202611_510300.csv  (197 bytes)
- option_sse_codes_sina_看跌期权_202611_510300.csv  (197 bytes)
- option_sse_greeks_sina_1.csv  (36 bytes)
- option_sse_greeks_sina_10012661.csv  (273 bytes)
- option_sse_list_sina_300ETF.csv  (42 bytes)
- option_sse_spot_price_sina_1.csv  (24 bytes)
- option_sse_spot_price_sina_10012661.csv  (817 bytes)
- option_vol_shfe_symbol-铜期权_trade_date-20261027.csv  (512 bytes)
- option_vol_shfe_symbol-黄金期权_trade_date-20261027.csv  (367 bytes)
- quality_report.md  (19040 bytes)
- quality_report.txt  (19040 bytes)