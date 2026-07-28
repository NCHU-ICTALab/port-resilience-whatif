# Local data

資料檔不納入 Git。建議在本機以 symbolic link 或指令列路徑引用：

| 檔案 | 角色 | 是否為 MVP 必要 |
|---|---|---|
| `ua1008l.sqlite` | 34 日進／出／移泊紀錄；校準 GT、到港、等待與服務時間 | 是 |
| `sdci.sqlite` | 7 日、278 次輪詢的多報表快照；研究預報修訂與即時 adapter | 否，第二階段 |
| `berth_specs.json` | 泊位長度與水深 | 是 |
| `berth_names.json` | 泊位用途／名稱 | 是 |
| `berths-khh.json` | 官方 marker feed 累積出的 72 個泊位中點／角度 | 展示需要 |
| `osm-khh.json` | 港區岸線、碼頭、錨地與防波堤 | 展示需要 |

資料來源、授權、欄位、雜湊與可公開性應在發布任何衍生資料前另行確認。原始 SQLite、
AIS 軌跡、船名、簽證號與代理資訊不可直接提交。
