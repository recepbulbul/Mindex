# Baseline sonuçları · validation

Dönem: 2025-10-01 → 2026-03-31 · %0,1 komisyon + 5 bp kayma, t kapanışında karar, t+1 açılışında yürütme · başlangıç 10 000 USDT

| Ajan | Tür | Getiri | Sharpe | MDD | İşlem | Komisyon (USDT) | Değişiklik yok (gün) |
|---|---|--:|--:|--:|--:|--:|--:|
| buy-hold-btc | rule | -42.5 % | -1.95 | 49.5 % | 1 | 9.99 | 180/181 |
| equal-weight | rule | -50.6 % | -1.94 | 57.5 % | 33 | 11.70 | 174/181 |
| ma-cross | rule | -21.8 % | -1.88 | 26.3 % | 61 | 62.10 | 158/181 |
| llm-momentum | llm | -42.9 % | -2.60 | 48.1 % | 557 | 512.42 | 0/181 |

Sürü korelasyonu (yatırılan ağırlığın günlük değişimi, ortalama Pearson): 0.259

## Nicel hedeflerle karşılaştırma

| Hedef (öneri formu) | Ölçülen | Durum |
|---|---|---|
| C3 LLM ortalama Sharpe'ı C0'a göre ≥ %15 yüksek | Hafıza ve forum P5-P6'da; bu koşu yalnızca C0 baseline | ölçülmedi |
| En iyi LLM ajanının MDD'si BTC al-ve-tut'tan ≥ %30 düşük | llm-momentum: MDD %48.1 vs %49.5 → %2.9 düşük | karşılanmadı |
| Karar çağrısı p95 < 10 sn | p95 5.26 sn (n = 30) | karşılandı |
