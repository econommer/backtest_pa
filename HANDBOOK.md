<!-- Generated from ../wiki/handbook.md (canonical). Edit that file, then regenerate. -->
> **Canonical 版本：** `../wiki/handbook.md`（Obsidian，會 wikilink 入 brain）。
> 本檔係 code repo 的鏡像，連結已改為相對路徑；改內容請改 canonical 再重生。


# VCP 策略研究手冊 (Handbook)

> 用途：**一站式速讀 / 定期溫習**。把散落喺 brain（`../wiki/`）同回測框架（本 repo 根）嘅重點，濃縮成一份可以隔一段時間翻睇嘅手冊。
> 內容 = 綜合 + 交叉引用；深度細節請跟連結入返原頁（呢度唔重複貼晒 evidence 表）。
> ⚠️ **研究文件，非投資建議。** 只做記錄、分析、回測；唔落單、唔搬錢、唔畀買賣建議。

**點用本手冊**
- 想快速掌握全局 → 睇 §0 一頁摘要。
- 想溫 VCP 規則 → §1（速查表可直接對照落單思路，但只做研究）。
- 想知數據點嚟、有幾可信 → §2。
- 想理解「點解個數可信 / 有咩 bias 防衛」→ §3。
- 想知宜家做到邊、下一步 → §4 + §5。
- 想親手跑 → §6 指令。

---

## §0 一頁摘要 (TL;DR)

| 面向 | 一句話 |
|---|---|
| **策略** | Mark Minervini 嘅 **VCP（波幅收縮形態突破）**：上升趨勢整固末段、波幅+成交量逐步收縮後，突破 pivot 買入。屬 [momentum-trend-trading-system](../wiki/playbooks/momentum-trend-trading-system.md) 核心 setup。 |
| **選股** | RS（相對強度）最強嘅第二階段領先股（[relative-strength](../wiki/concepts/relative-strength.md)）；回測用**全域 ROC 排名 ≥70 百分位**近似。 |
| **風險** | 每注固定風險（1%），止損 = 支持位 − N×ATR（=1R），一律用 **R 單位**衡量（[initial-stop-and-r-multiple](../wiki/concepts/initial-stop-and-r-multiple.md)、[expectancy-and-position-sizing](../wiki/concepts/expectancy-and-position-sizing.md)）。 |
| **數據** | Phase-1：免費 yfinance，人手揀、現存上市股（**有倖存者偏差**）。Phase-2：**Bloomberg PIT S&P 500，827 成員含退市，2010–2025，無倖存者偏差**（快照已齊）。 |
| **引擎** | 自建輕量 event-driven（``，btf）。鐵律 **Strategy ⟂ Engine**：引擎唔識「VCP」，只餵數據、收信號、模擬成交同記賬。 |
| **可信度防衛** | 無 look-ahead（結構性）、無倖存者偏差（Phase-2）、抗過擬合（IS/OOS + walk-forward + 參數敏感度）、真實成本（滑點+佣金+gap-through 止損）。 |
| **現況（2026-07-04）** | Phase-1 expectancy **+0.42R**（n=73）、M5 三項防衛通過；Phase-2 **暫定 +0.18R**（n=428，倖存者偏差剃頭）；**快照已齊，待跑正式 `--validate` 出可信版**。 |
| **下一步** | M6 正式報告 → 回填 [vcp-breakout](../wiki/setups/vcp-breakout.md) Evidence；之後 M7 加 [pocket-pivot-buy](../wiki/setups/pocket-pivot-buy.md)、[buyable-gap-up-entry](../wiki/setups/buyable-gap-up-entry.md) 同場比較。 |

**結論一句：** VCP 喺真數據上 expectancy 仍為正、形狀典型（低勝率、大贏小輸），但樣本 + 市況覆蓋有限，**未算 validated edge**；框架已足以誠實量度，宜家爭一份齊數據嘅正式報告。

---

## §1 VCP 策略

### 定位（4 元素框架）
交易策略 = **市場結構 → area of value → trigger → 離場計劃**（[2020-08-23-four-elements-trading-strategy](../wiki/sources/2020-08-23-four-elements-trading-strategy.md)）。VCP 係其中一個 **trigger**，唔係聖杯；明白 price action 原理 > 死記形態。詳見 setup 主頁 [vcp-breakout](../wiki/setups/vcp-breakout.md)。

### 規則速查（濃縮自 [vcp-breakout](../wiki/setups/vcp-breakout.md)）
| 環節 | 規則 |
|---|---|
| **Context** | 明確上升趨勢（Stan Weinstein 第二階段，收 > SMA150 且線向上）；最好大市同向 + RS 領先股。順勢系統，最怕無趨勢/whipsaw。 |
| **Trigger** | 整固期波幅 **2–4 段逐步收縮**（如 27%→17%→8%），成交量同步收縮（[volatility-contraction](../wiki/concepts/volatility-contraction.md)）；末段緊貼阻力嘅 build-up 最理想；喺最窄一段向上突破 pivot（阻力位），突破日放量佳。 |
| **Entry** | 到價突破即買（貼近 [area-of-value](../wiki/concepts/area-of-value.md)，波幅越窄買點越近支持越好）。 |
| **Stop** | 支持位 **− N×ATR**（volatility stop，唔正放支持位，留空間畀假突破）；避開業績前買入（[gap-risk](../wiki/concepts/gap-risk.md)）。 |
| **Target/Exit** | 中線 50 天線 ±ATR、短線 20 天線做 trailing（[trailing-stops](../wiki/concepts/trailing-stops.md)）；連跌多日大成交 = 派貨，考慮減。 |
| **Sizing** | R 與部位公式（[expectancy-and-position-sizing](../wiki/concepts/expectancy-and-position-sizing.md)）；波幅窄→止損窄→R:R 較佳。 |
| **Confluence** | RS 高 + 強行業 + 貼 area of value + build-up + 大市順勢（[situation-awareness](../wiki/concepts/situation-awareness.md)）。 |
| **Failure modes** | 唔係聖杯（Minervini 自己 ~50–60% 勝率）；SMA50/200 之下、whipsaw 市、業績裂口、追「完美形態」機會太少；「lower lows into support」（圖 B）偏熊唔應買升。 |

### 機械化映射（brain 規則 → 程式碼）
規則實作：`src/btf/strategies/vcp.py`；跑法：`scripts/run_vcp.py` 或 config 版 `scripts/run_config.py`。

| Brain 規則 | 機械化實作 |
|---|---|
| 第二階段趨勢 | 收 > SMA150 且 SMA150 上升 |
| RS 領先股（[relative-strength](../wiki/concepts/relative-strength.md)） | 全 universe **ROC 排名 ≥ 70 百分位**（point-in-time；行業 RS 留待 Phase-2+） |
| 波幅/量收縮（[volatility-contraction](../wiki/concepts/volatility-contraction.md)） | 兩步收縮偵測 + 突破日放量門檻 |
| Pivot 突破 | 突破 base-window 高位 |
| 初始止損（[initial-stop-and-r-multiple](../wiki/concepts/initial-stop-and-r-multiple.md)） | build-up 低位 − 1×ATR(14) = 1R |
| 離場（[trailing-stops](../wiki/concepts/trailing-stops.md)） | 收 < SMA50 離場；硬止損由 broker gap-through sweep（[gap-risk](../wiki/concepts/gap-risk.md)） |
| 成交假設 | 收市確認 → **翌日開市 MARKET fill**，佣金 0.005/股、滑點 0.05% |

---

## §2 數據宇宙 (Data Universe)

### 兩個 Phase
| | **Phase-1（原型，有偏）** | **Phase-2（可信，無倖存者偏差）** |
|---|---|---|
| 來源 | yfinance / Stooq（免費，復權日線） | **Bloomberg** 日線（PIT 成員 + bars） |
| Universe | 人手揀、**現存上市** 30 隻跨行業股（+ ETF/商品籃子） | **S&P 500 point-in-time，827 成員含退市**，2010–2025 |
| Bias | **倖存者/選擇偏差大**（無退市名、贏家事後可見）→ expectancy 上偏 | 無倖存者偏差（成員按當時歷史計、含已退市） |
| Benchmark | SPY | SPX |
| Config | `config/vcp_phase1.yaml` | `config/vcp_phase2_bloomberg.yaml` |

### Phase-2 快照詳情
- **827** 個 PIT S&P 500 成員（含退市）；**826 隻有 Bloomberg 日線**（一隻退市 stub `1844053D` 無數據）。
- 成員名單：`config/universe_spx_2010_2025.txt`（由 fetch 腳本生成，勿手改）。
- **成員粒度：月度**（每月一個成員快照）——係已知近似，唔係逐日精確。
- **點建立**：`scripts/fetch_bloomberg_snapshot.py`，兩階段、有預算保護：
  1. `--stage membership`：抓月度成員快照（≈1 unique security）+ SPX benchmark，寫 universe 檔。
  2. `--stage bars`：按名單逐隻抓 bars，**每日額度上限 + dry-run 預設**，用 `UsageLedger` 記賬避免撞 Bloomberg unique-security cap；可分日續抓、可 resume。
- 快照喺 **2026-07-04 齊**（分兩日抓：07-03 抓 300 + 07-04 抓 528）。
- ⚠️ 跑 Bloomberg 腳本要用 `.venv/Scripts/python.exe`（有 `blpapi`；系統/conda python 無）。

### 已知限制
- 月度成員粒度（非逐日）；1 隻缺 bars；月中加入/剔除嘅短暫成員可能漏。
- Bloomberg 需 Terminal 登入 + 有額度；離線後 provider **只讀 cache、永不上網**（一個 cache miss 會報錯叫你補抓，唔會靜靜偷偷去 network 用額度）。

---

## §3 方法論 (Methodology)

### 鐵律：Strategy ⟂ Engine
引擎（btf）**唔識任何策略名**。每根 bar：畀策略一個「截至今日」嘅 `Context` → 收策略嘅 **意圖（`Signal`，只講買/賣乜、唔講價同注碼）** → PositionSizer 換算成 R-sized order → Broker 喺 **t+1 開市**成交（滑點/佣金/gap-through）→ Portfolio 記賬 → 出 `BacktestResult`（含 R 指標、regime 分解、benchmark overlay）。換策略或換數據供應商，另一邊唔使改。

```
DataProvider → Context(≤今日) → Strategy.on_bar() → [Signals]
            → PositionSizer(R) → Broker(t+1 open) → Portfolio → BacktestResult
```

### R 單位與 metrics
一律用 **R = 初始風險**（[initial-stop-and-r-multiple](../wiki/concepts/initial-stop-and-r-multiple.md)）。
**Expectancy = 勝率 × 平均贏R − 敗率 × 平均輸R**（[expectancy-and-position-sizing](../wiki/concepts/expectancy-and-position-sizing.md)）。
報告指標：勝率、平均贏/輸 R、expectancy、profit factor、最大連敗、最大回撤（R 同 %）、曝險、regime 分解、benchmark 對比。**n < 30 一律標 `!`**（軼事，非證據）。

### 四大偏差防衛（brain 堅持）
1. **無 look-ahead（結構性，非靠自律）**：策略喺 bar *t* 收市決策，order 喺 *t+1* 開市成交；`Context` 只見 ≤ 今日資料；RS/regime 皆 point-in-time。由 `tests/test_no_lookahead.py` 守。
2. **無倖存者偏差**：Phase-1 喺每份報告**大聲標明**偏差；Phase-2 換 delisted-inclusive universe 修正（見 §2）。
3. **抗過擬合**：in-sample/out-of-sample 切分、walk-forward、參數敏感度（`btf.validation`，M5）。
4. **真實成本**：滑點 + 佣金 + **gap-through 止損**（裂口可跳過止損 → 以開市價成交，唔係止損價）。

### Config 驅動 + 驗證協定
**一個 YAML = 一個完整定義嘅 run**（universe/期間/成本/風險/參數/驗證協定）——同一 config + 同一 data snapshot ⇒ **同一結果**。
`--validate` 跑 YAML 定義嘅防衛：**IS/OOS 切分**（`oos_start`）、**walk-forward**（`walk_forward_windows`）、**參數敏感度**（`sensitivity`，一次郁一個，睇 expectancy 係咪平滑下降、基線隔離有冇斷崖）。

### 快速迭代工具（M6 輔助）
- ⚠️ **Phase-2 base run ≈ 48 分鐘**；`--validate` 全套 ≈ **26×（~21 鐘頭）**（框架效能已知瓶頸，係 VCP 全 universe scan）。
- `scripts/vcp_fast_m6.py`：**淨 base run + coverage**，跳過 validation 套餐，快速睇數；可 `--html` 出報告。
- `scripts/verify_vcp_fast.py`：**信心閘**——完整性檢查（PIT universe、benchmark、coverage、bar、equity、metrics 恆等式、trade R）+ `--repro` 重現性（跑兩次要一模一樣）。跑正式數之前用嚟 go/no-go。

---

## §4 現況與結果 (Results so far)

> 詳細 evidence 表全部喺 [vcp-breakout](../wiki/setups/vcp-breakout.md) 的 Evidence 一節；呢度只擺結論。

| 里程 | 條件 | 結果 |
|---|---|---|
| **M4 首份報告**（2026-07-01） | Phase-1 股票 30 隻，2015–2025 | **+0.42R**，n=73，勝率 38%，PF 1.96，回撤 10%。形狀典型：低勝率、平均贏 ≈ 3–4× 平均輸。 |
| **M5 偏差防衛**（2026-07-02） | 同一 YAML，三項防衛 | 基線完全重現 M4；OOS 不遜 IS；walk-forward **4/5 窗為正**（2017–18 負窗 = whipsaw 死穴實證）；16 個敏感度掃描點**全部為正**、基線隔離冇斷崖 → **無過擬合特徵**。 |
| **M6 Phase-2 暫定**（2026-07-03） | PIT 含退市，~35%/月子樣本 | **+0.18R**，n=428，勝率 40%，PF 1.43，回撤 19%。**倖存者偏差剃頭真實：+0.42R → +0.18R**；但 edge 未死（walk-forward 5/5 窗正；唯一負 regime 係 range/whipsaw）。 |

**現況（2026-07-04）：** 快照**已齊**（826/827）。暫定報告 `reports/vcp_phase2_tentative_2026-07-03.html` 係**部分數據**上手砌嘅，**要對齊完整快照重跑正式 `--validate` 全套**先算數，然後回填 [vcp-breakout](../wiki/setups/vcp-breakout.md)。

**要記住嘅誠實話：** expectancy 為正 ≠ 跑贏大市。每注 1% 風險 → 長期持大量現金，Phase-1 絕對回報（股票 +29%）**遠低於 buy&hold SPY（+240%）**。呢個係**每注優勢**，唔係資金曲線最優。

---

## §5 路線圖 (Roadmap)

| | 里程 | 狀態 |
|---|---|---|
| **M0** | 凍結介面（DataProvider / Strategy / Engine / Broker / Signal / Context） | ✅ |
| **M1** | 骨架 + 假數據，引擎行 buy-and-hold，賬目對得平 | ✅ |
| **M2** | Phase-1 數據 — yfinance/Stooq adapter、parquet cache、pinned universe | ✅ |
| **M3** | Metrics — R 統計/expectancy/回撤/regime 分解 + benchmark | ✅ |
| **M4** | VCP 策略 — 機械化規則 + 首份報告（偏差標明） | ✅ |
| **M5** | 偏差防衛 — walk-forward、OOS、參數敏感度 + config-YAML runs | ✅ |
| **M6** | **Phase-2 數據 — 無倖存者偏差 provider + 可信報告** | ⏭ **進行中**（快照已齊，待正式報告） |
| **M7** | 更多策略 — [pocket-pivot-buy](../wiki/setups/pocket-pivot-buy.md)、[buyable-gap-up-entry](../wiki/setups/buyable-gap-up-entry.md) 同一引擎比較（[setup-scorecard](../wiki/comparisons/setup-scorecard.md)） | ⬜ |

**即時下一步：** 對齊完整快照跑 `run_config.py config/vcp_phase2_bloomberg.yaml --validate` → 產出可信版報告 → 回填 [vcp-breakout](../wiki/setups/vcp-breakout.md) Evidence + `log.md` 加 `backtest` 條目 → 收 M6。

---

## §6 快速上手 (指令)

```bash
# 位置：C:\Project\AI\brains\pa-strategy-brain\code
# 一律用 venv python（有 blpapi / btf）：  .venv\Scripts\python.exe

# Phase-1（快、免費、離線 cache）
python scripts/run_config.py config/vcp_phase1.yaml            # base run
python scripts/run_config.py config/vcp_phase1.yaml --validate # + 偏差防衛

# Phase-2（Bloomberg PIT，慢：base ~48 分鐘）
python scripts/vcp_fast_m6.py --html reports/vcp_phase2_fast.html  # 快速睇數 + 報告
python scripts/verify_vcp_fast.py --repro                          # 信心閘（跑正式數前）
python scripts/run_config.py config/vcp_phase2_bloomberg.yaml --validate  # 正式全套（~21h）

# 抓 Bloomberg 快照（需 Terminal 登入）
python scripts/fetch_bloomberg_snapshot.py --stage membership --confirm
python scripts/fetch_bloomberg_snapshot.py --stage bars --confirm   # 逐日續抓
```

---

## §7 交叉引用

**Brain（`../wiki/`）**
- 高層綜合：[overview](../wiki/overview.md)｜端到端系統：[momentum-trend-trading-system](../wiki/playbooks/momentum-trend-trading-system.md)
- Setup：[vcp-breakout](../wiki/setups/vcp-breakout.md)（本手冊主角）、[pocket-pivot-buy](../wiki/setups/pocket-pivot-buy.md)、[buyable-gap-up-entry](../wiki/setups/buyable-gap-up-entry.md)、[false-breakouts](../wiki/concepts/false-breakouts.md)｜對照：[setup-scorecard](../wiki/comparisons/setup-scorecard.md)
- 概念：[relative-strength](../wiki/concepts/relative-strength.md)、[volatility-contraction](../wiki/concepts/volatility-contraction.md)、[initial-stop-and-r-multiple](../wiki/concepts/initial-stop-and-r-multiple.md)、[expectancy-and-position-sizing](../wiki/concepts/expectancy-and-position-sizing.md)、[trailing-stops](../wiki/concepts/trailing-stops.md)、[gap-risk](../wiki/concepts/gap-risk.md)、[situation-awareness](../wiki/concepts/situation-awareness.md)、[market-structure](../wiki/concepts/market-structure.md)、[area-of-value](../wiki/concepts/area-of-value.md)、[risk-management-vs-setup](../wiki/concepts/risk-management-vs-setup.md)
- 人物：[mark-minervini](../wiki/entities/mark-minervini.md)、[william-oneil](../wiki/entities/william-oneil.md)、[chris-kacher](../wiki/entities/chris-kacher.md)、[van-tharp](../wiki/entities/van-tharp.md)、[stan-weinstein](../wiki/entities/stan-weinstein.md)
- 來源：[2020-07-30-vcp](../wiki/sources/2020-07-30-vcp.md)、[2020-08-23-four-elements-trading-strategy](../wiki/sources/2020-08-23-four-elements-trading-strategy.md)、[2020-10-09-relative-strength-stock-selection](../wiki/sources/2020-10-09-relative-strength-stock-selection.md)

**Code（本 repo 根）**
- 設計文件：`BACKTESTING_PLAN.md`（權威）、`README.md`（架構 + worked example + roadmap）、`CLAUDE.md`
- 規則實作：`src/btf/strategies/vcp.py`｜引擎：`src/btf/engine/`｜驗證：`src/btf/validation/`
- Config：`config/vcp_phase1.yaml`、`config/vcp_phase2_bloomberg.yaml`
- 工具：`scripts/vcp_fast_m6.py`、`scripts/verify_vcp_fast.py`、`scripts/fetch_bloomberg_snapshot.py`

_本手冊係綜合頁，會隨 brain / code 演進更新；權威細節以連結原頁為準。_
