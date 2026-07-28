# 軍事任務情境輸入

軍事任務只接受情境擁有者明確提供的 JSON。求解器不會推測任務，也不允許商船目標取消、
延後或降低已輸入的軍事 deadline。

先複製 [`examples/military_tasks.template.json`](../examples/military_tasks.template.json)，再為每個
任務填入：

```json
{
  "schema_version": "resilience.military-input.v1",
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
  ]
}
```

上例只示範格式，不代表真實軍事船舶、泊位或任務。所有時間是相對於 case `observed_at` 的
小時數。`ship_type` 必須能與目前泊位用途分類相容；若任務沒有任何相容泊位，載入時會直接
拒絕，而不是放寬限制。

人工提供檔案不應提交公開 Git；建議放在已被忽略的 `data/` 或 `out/` 下。執行後，review
packet 只會標示這些欄位為 `scenario_input`。
