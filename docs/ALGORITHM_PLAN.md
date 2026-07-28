# 演算法執行順序

## Stage 0：共用可行性核心（已開始）

- 船舶／泊位／受損事件／安全窗口資料模型；
- 尺寸、吃水、用途、軍方保留、受損區間硬限制；
- 軍事 deadline 優先 + 商船 FCFS 規則基準；
- 窗口內逐艘 release 與 channel headway；
- 可解釋 reason codes。

執行：

```bash
PYTHONPATH=src python3 -m port_resilience.demo
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Stage 1：資料 adapter

從 `ua1008l.sqlite` 取 34 日進港事件，以 GT、泊位、過港／靠泊／離泊時間建立可重現的
72 小時 case。LOA、吃水與船種缺值必須標為 estimated；不可從未來離泊時間洩漏到線上基準。

## Stage 2：CP-SAT oracle

先做 8–20 艘、3–6 泊位的小型 instance：optional interval、no-overlap、alternative berth、
安全窗口與軍事 deadline。輸出 exact objective 或 optimality gap，作為共用硬限制的驗證器。

## Stage 3：NSGA-II

染色體同時編碼船序、窗口與泊位；repair operator 只修復可修復的表示問題，真正安全限制
仍由共用 feasibility checker 驗證。三目標為軍事排程偏離、商船等待與 makespan。

## Stage 4：配對比較

同一 case／seed 比較 FCFS、公開優先規則、VTS 仿真、NSGA-II 與縮小 CP-SAT。回報 Pareto
hypervolume、等待、服務船次、constraint violations、求解時間與 paired bootstrap CI。
