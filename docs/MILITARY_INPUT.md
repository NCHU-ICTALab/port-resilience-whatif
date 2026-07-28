# 軍事任務情境輸入

軍事任務只接受情境擁有者明確提供的 JSON。求解器不會推測任務，也不允許商船目標取消、
延後或降低已輸入的軍事 deadline。

目前建議使用 `resilience.military-input.v2`。它同時承載軍事任務、人工核定狀態與分時泊位
管制；舊的 v1 任務檔仍可載入。先複製
[`examples/military_tasks.template.json`](../examples/military_tasks.template.json)，再填入：

```json
{
  "schema_version": "resilience.military-input.v2",
  "authority": {
    "status": "draft_preview",
    "reference": null
  },
  "missions": [
    {
      "ship_id": "M001",
      "eta_hour": 5.0,
      "ready_hour": 5.0,
      "service_hours": 4.0,
      "loa_m": 180.0,
      "draft_m": 8.0,
      "ship_type": "container",
      "original_berth": "1069",
      "deadline_hour": 7.5,
      "planned_start_hour": 6.0,
      "allowed_terminals": ["CT3"]
    }
  ],
  "port_controls": [
    {
      "control_id": "R001",
      "mode": "military_exclusive",
      "berth_codes": ["1069"],
      "start_hour": 6.0,
      "end_hour": 12.0,
      "allow_current_vessel_to_finish": true,
      "clear_before_start": false
    }
  ]
}
```

上例只示範格式，不代表真實軍事船舶、泊位或任務。所有時間是相對於 case `observed_at` 的
小時數。`ship_type` 必須能與目前泊位用途分類相容；若任務沒有任何相容泊位，載入時會直接
拒絕，而不是放寬限制。

`authority.status` 可為：

- `draft_preview`：未核准的 what-if；
- `human_approved_scenario`：情境擁有者核准用於比較；
- `exercise_input`：演習輸入，`reference` 應填演習識別資料。

目前可執行的泊位控制為：

- `military_priority`：軍事任務維持硬優先，但不封鎖剩餘商用容量；
- `military_exclusive`：指定時段只阻擋商船，軍事船舶仍可使用；
- `closed`：指定時段同時阻擋軍商船。

第一版只支援泊位層級、100% 專用或關閉。terminal 百分比保留、拖船／引水配額與基本民生
最低服務量尚未實作，不會用假的精度代替。

人工提供檔案不應提交公開 Git；建議放在已被忽略的 `data/` 或 `out/` 下。執行後，review
packet 只會標示這些欄位為 `scenario_input`。
