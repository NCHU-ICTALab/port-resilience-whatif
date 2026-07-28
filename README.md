# Port Resilience What-if

高雄港全災害產能衝擊與商船重分配決策支援 PoC。第一個 preset 是戰時港口設施徵用／
產能受損，但模型不預測攻擊或軍方會徵用何處；徵用組態由使用者輸入，系統只回答商船
如何重分配、代價多大，以及何時跨過港口韌性的膝點。

> 本專案是公開資料上的 what-if 研究工具，不是港務、VTS 或軍事作業系統。未取得港方
> 戰時規則、資源狀態與真實案例前，不得宣稱「優於高雄港戰時排程」。

## 已確認的開發範圍

現在可做：

- 高雄港 72 小時單港情境；
- 安全窗口 convoy/batch 放行：批次選船、窗口內進港順序、泊位與資源聯合排程；
- 作業時窗、護航批次、泊位容量損失、需求倍率與修復曲線；
- 泊位長度／水深相容、船舶 GT、歷史等待與靠泊服務時間校準；
- FCFS、優先權規則、官方公開 VTS 規則仿真三種基準；
- NSGA-II Pareto 候選、縮小實例 CP-SAT 交叉驗證；
- 確定性排程與事件日誌 JSON，供 iMarine-FrontEnd 播放。

尚不能當成真實資料宣稱：

- 高雄、台中、基隆三港的跨港容量與聯合排程；
- 軍事適用性、軍方優先排程或真實徵用需求；
- 起重機、堆場、鐵公路集疏運、引水與拖船的完整班表；
- 港方未公開的戰時 SOP 與現行戰時演算法績效；
- 精確貨櫃量／TEU（現有資料主要提供船次、GT 與停時）。

完整判定見 [資料可用性](docs/DATA_READINESS.md) 與
[比較與驗證規約](docs/COMPARISON_PROTOCOL.md)。正式產品定義與第一版驗收情境見
[系統規格](docs/SYSTEM_SPEC.md)，演算法落地順序見
[演算法計畫](docs/ALGORITHM_PLAN.md)。
公開制度如何轉成軍事優先、分時專用與徵用生命週期，見
[戰時港口徵用研究](docs/WARTIME_PORT_REQUISITION.md)。

## 人工評估

目前已可產生通過模型硬限制檢查的 NSGA-II 候選與 `resilience.human_review.v1` 評估封包：

```bash
.venv/bin/python -m port_resilience.review \
  --movements-db ../sdci_data/ua1008l.sqlite \
  --berth-specs ../sdci_data/berth_specs.json \
  --start 2026-07-05T00:00:00 --limit 20 \
  --population 80 --generations 80 --seed 42 \
  --output examples/human_review_packet.json
```

範例輸出見 [human_review_packet.json](examples/human_review_packet.json)。目前歷史資料沒有軍事
任務，因此正式商軍 Pareto 評估前，情境擁有者需依[軍事任務輸入格式](docs/MILITARY_INPUT.md)
提供 deadline、預定時程、尺寸與可用 terminal。系統不會自行生成軍事需求。

## 與既有專案的關係

```text
iMarine-FrontEnd
  └─ provider 呼叫 HTTP API，接收 Pareto 排程與事件日誌，只負責播放

port-resilience-whatif（本專案）
  ├─ 公開資料 adapter／校準
  ├─ 情境與硬限制
  ├─ FCFS／官方規則仿真／NSGA-II／CP-SAT
  └─ API + deterministic event log
```

整合方式沿用 `typhoon-evacuation-rl` 的「獨立 Python 後端 + 無狀態 JSON 契約 + 前端
provider」模式，但本問題是一次性離線規劃，主求解器使用 NSGA-II，不沿用 RL。

## 資料體檢

體檢器只用 Python 標準函式庫，SQLite 以 read-only mode 開啟：

```bash
python3 -m port_resilience.audit \
  --movements-db ../sdci_data/ua1008l.sqlite \
  --snapshots-db ../sdci_data/sdci.sqlite \
  --berth-specs ../sdci_data/berth_specs.json \
  --berth-markers ../iMarine-FrontEnd/src/screens/twin/data/berths-khh.json
```

安裝開發環境後可使用：

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,optimizer]'
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## 預定目錄

```text
src/port_resilience/   資料體檢、情境、求解器與 API
tests/                 單元與契約測試
docs/                  資料、比較、前端契約與研究邊界
examples/              可直接使用的情境與事件日誌
data/                  本機資料說明；資料本身不進 Git
out/                   求解與評估輸出，不進 Git
```
