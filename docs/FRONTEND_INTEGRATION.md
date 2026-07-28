# iMarine-FrontEnd 整合草案

沿用 `typhoon-evacuation-rl` 的獨立後端模式，但使用新的 namespace：

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/resilience/health` | 服務與 solver readiness |
| GET | `/api/resilience/capabilities` | 模型限制、資料版本、可用 baseline |
| POST | `/api/resilience/solve` | 回傳 NSGA-II Pareto 候選 |
| POST | `/api/resilience/replay` | 取得指定候選的事件日誌 |

前端設定建議新增 `twin.resilienceApiBase`／`VITE_RESILIENCE_API`，不要覆蓋既有
`twin.rlApiBase`。前端只顯示後端回傳的確定性排程；展示情境可事先計算並快取。

## 前端情境編輯器

泊位可單選、多選或依 CT 群組選取，並建立具未來生效時間的事件：

- 正常、商船占用、軍方占用、軍方保留、完全／部分受損、修復中；
- 開始、持續時間、容量損失；
- 是否立即清空、是否允許靠泊中船舶完成；
- 立即、分階段或未知修復。

時間軸需支援 72 小時、途中新增／解除事件，以及 FCFS、VTS 規則仿真與 NSGA-II
同一時鐘左右對照。船舶詳情顯示原／新泊位、延誤、狀態及結構化 reason codes。

批次放行畫面要區分 `convoy_ready` 與 `released`。同一窗口入選的船舶仍依
`release_order`／`channel_enter` 逐艘進港，不做同時進航道的動畫。

## 事件日誌

每個事件至少包含：

```json
{
  "t": 8100,
  "type": "berth",
  "ship_id": "V001",
  "berth_code": "1068",
  "source": "optimizer",
  "provenance": {
    "arrival": "observed",
    "service_time": "estimated"
  }
}
```

`type` 第一版支援：

- `scenario_started`
- `requisition_start`／`requisition_end`
- `capacity_loss`／`capacity_restore`
- `window_open`／`window_close`
- `arrive_anchorage`
- `convoy_release`
- `channel_enter`
- `berth_start`／`berth_end`
- `depart`
- `divert`／`divert_rejected`
- `berth_state_changed`
- `reoptimization_triggered`
- `assignment_changed`

泊位狀態應能由事件重建，不另維護一套相互矛盾的動畫狀態。時間 `t` 是相對
`scenario.observed_at` 的秒數。
