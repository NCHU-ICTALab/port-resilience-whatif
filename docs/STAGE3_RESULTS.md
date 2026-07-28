# Stage 3：NSGA-II 與人工評估閘門

## 已完成

- 染色體以每艘船三個 random keys 編碼船舶順序、安全窗口偏好與泊位偏好；
- decoder 只產生符合 ready time、deadline、適泊、受損區間、release slot 與泊位不重疊的安排；
- 每個輸出再交由獨立 `validate_schedule` 重算硬限制，不信任求解器自行回報；
- 公開優先規則方案作為 throughput acceptance floor，NSGA-II 候選不得少服務船舶；
- 相同三目標值的排程會合併，避免把泊位細節不同但目標完全相同的解冒稱不同 Pareto 取捨；
- review packet 含逐船排程、原因碼、KPI、相對基準差異、四種 profile 排序與人工核准欄位。

## 20 艘歷史案例

情境：2026-07-05 00:00 起 72 小時，1068 泊位第 10–58 小時停用；只允許同 terminal
改泊。NSGA-II 使用 population 80、generation 80、seed 42，共評估 6,400 次，所有保留
候選均通過獨立硬限制檢查。

| 指標 | 公開優先規則仿真 | NSGA-II P001 | 差異 |
|---|---:|---:|---:|
| 服務船數 | 20 | 20 | 0 |
| 商船總等待 | 117.750 h | 112.500 h | -5.250 h（-4.46%） |
| 商船平均等待 | 5.888 h | 5.625 h | -0.263 h |
| 商船 P90 等待 | 15.000 h | 15.050 h | +0.050 h |
| 排程完成時間 | 第 50.458 h | 第 45.000 h | -5.458 h（-10.82%） |
| 改泊數 | 2 | 3 | +1 |
| 模型硬限制違規 | 0 | 0 | 0 |

P001 改善總等待與排程完成時間，但 P90 略差且多一次改泊。這是相對於本專案公開規則
仿真的單一 seed 結果，不是對實際港方戰時作業的績效主張。

## 為何現在需要人工輸入

歷史 archive 沒有軍事任務。因而本次軍方排程偏離固定為 0，三目標實際退化成兩目標，
去除相同 objective vectors 後只剩一個 Pareto 點。要形成真正的商軍取捨，情境擁有者必須
提供軍事任務 overlay；系統不會自行假設任務、deadline 或保留泊位。

此外，下列項目仍需港務／VTS 人員確認：

1. `pilot_apply_time` 是否是可接受的當時已知 ready-time proxy；
2. 以真實 LOA、吃水與船貨類型取代 GT 推估；
3. operator、堆場與設備允許的跨 terminal 規則；
4. 引水、拖船、航道方向與各時段容量；
5. 偏好 profile 或正式核准權重。

完整機器可讀封包見 [`examples/human_review_packet.json`](../examples/human_review_packet.json)。

## 重現

```bash
.venv/bin/python -m port_resilience.review \
  --movements-db ../sdci_data/ua1008l.sqlite \
  --berth-specs ../sdci_data/berth_specs.json \
  --start 2026-07-05T00:00:00 --limit 20 \
  --population 80 --generations 80 --seed 42 \
  --output examples/human_review_packet.json
```

取得人工核准的軍事輸入後，加上：

```bash
  --military-input path/to/military_tasks.json
```
