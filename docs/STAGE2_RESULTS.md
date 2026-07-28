# Stage 2：CP-SAT oracle 實跑結果

資料與 Stage 1 相同：`2026-07-05 00:00` 起算 72 小時、貨櫃碼頭同 terminal 改泊、
`1068` 泊位於第 10–58 小時停用。所有比較都使用相同輸入、release slots 與硬限制。

## 8 艘小型 oracle case

CP-SAT 在 0.948 秒內證明 `OPTIMAL`：

| 指標 | 公開優先規則仿真 | CP-SAT |
|---|---:|---:|
| 完成船數 | 8 | 8 |
| 商船總等待 | 765 分鐘 | 765 分鐘 |
| 平均等待 | 1.594 小時 | 1.594 小時 |
| 排程結束時間 | 第 26.417 小時 | 第 25.933 小時 |
| 改泊數 | 2 | 2 |
| constraint violations | 0 | 0 |

在這個小案例，精確解沒有改善等待或完成船數，但將排程結束時間提前約 0.484 小時。
這是「相對於本專案的公開規則仿真」的結果，不代表優於真實港務排程。

## 20 艘壓力 case

30 秒上限內 CP-SAT 僅回傳 `FEASIBLE`，未證明最優。當時解的總等待為 7,080 分鐘，
略高於規則基準的 7,065 分鐘；objective bound 亦仍有距離。因此此結果只能用於檢查可行性與
求解規模，不能用來宣稱演算法改善。Stage 3 應以規則解作為 warm start／seed，確保任何時間
上限下至少不劣於已知基準，再由 NSGA-II 搜尋多目標候選。

## 重現方式

```bash
.venv/bin/python -m port_resilience.compare \
  --movements-db ../sdci_data/ua1008l.sqlite \
  --berth-specs ../sdci_data/berth_specs.json \
  --start 2026-07-05T00:00:00 --limit 8 --time-limit 30
```
