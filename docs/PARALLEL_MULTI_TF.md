# Пункт 1: Параллельный расчёт по ТФ в multi_tf

## Что это будет

**Сейчас:** В `analyze_multi_timeframe()` по каждому таймфрейму (15, 60, 240) в **одном цикле по очереди** считаются:
- качество свечей (`validate_candles_quality`),
- тренд (`detect_trend`),
- фаза (`detect_phase`),
- режим (`detect_regime`),
- импульс (`detect_momentum`),
- устойчивость фазы/тренда (`_update_phase_stability`, `_update_trend_stability`),
- и собирается словарь `timeframes_report[tf]`.

Время одного тика = сумма времени по всем ТФ (последовательно).

**После изменения:** Тяжёлые расчёты по **разным ТФ выполняются параллельно** (несколько потоков или процессов). Итог одного тика = время самого долгого ТФ + небольшой накладной расход, а не сумма по всем.

---

## Что именно параллелим

По каждому ТФ независимо от других можно считать:
- `validate_candles_quality(candles_raw, timeframe=tf)`
- `detect_trend(candles, timeframe=tf)`
- `detect_phase(candles, timeframe=tf)` — **первый проход** (без контекста старшего ТФ)
- `detect_regime(candles, lookback=50)`
- `detect_momentum(candles)`

Данные для каждого ТФ уже есть в `data[tf]` (свечи загружаются один раз до цикла). Зависимостей между ТФ в этих вызовах нет — их можно выполнять в параллельных задачах.

---

## Что остаётся последовательным

1. **Загрузка данных** — один раз: `_load_candles_from_db` или `get_klines_multi_timeframe` по всем ТФ (как сейчас).
2. **Устойчивость фазы и тренда** — `_update_phase_stability(tf, phase)` и `_update_trend_stability(tf, trend)` обновляют общую историю (`_phase_history`, `_trend_history`). Их нужно вызывать в **фиксированном порядке** (например, по возрастанию ТФ), чтобы результат не зависел от порядка завершения потоков. Поэтому после сбора результатов по ТФ выполняем один последовательный проход: для каждого ТФ по порядку вызываем _update_phase_stability и _update_trend_stability и дополняем отчёт.
3. **Контекст старшего ТФ** — пересчёт фаз младших ТФ с учётом `higher_tf_phase` и `higher_tf_trend` (второй проход по младшим ТФ). Делается после того, как по старшему ТФ всё уже посчитано — последовательно.
4. **Зоны по старшему ТФ** — `detect_trading_zones(higher_tf_candles)` и расчёт confluence по другим ТФ. Выполняется после формирования `timeframes_report` по всем ТФ — последовательно.
5. **Агрегация сигнала** — direction, filters, entry_score, reason — считаются из уже готового `timeframes_report` и зон — последовательно.

Итого: параллелим только «по ТФ независимый» блок (quality + trend + phase без контекста + regime + momentum); загрузку, историю, контекст старшего ТФ, зоны и сигнал оставляем в одном потоке.

---

## Как это реализовать (схема)

1. **Подготовка данных** — без изменений: загружаем `data` по всем ТФ, `sorted_tfs`, `higher_tf`.
2. **Функция одной задачи по ТФ** — принимает `(tf, candles_raw)`. Внутри:
   - quality = validate_candles_quality(candles_raw, timeframe=tf)
   - candles = quality["filtered"] or candles_raw
   - trend_info = detect_trend(candles, timeframe=tf) при len(candles) >= 30, иначе default
   - phase_info = detect_phase(candles, timeframe=tf) при len(candles) >= 30, иначе default
   - regime_info = detect_regime(candles, ...), momentum_info = detect_momentum(candles, ...)
   - Возвращает `(tf, candles, quality_result, trend_info, phase_info, regime_info, momentum_info)` — **без** phase_stability/trend_stability (их нет в задаче).
3. **Пул** — `concurrent.futures.ThreadPoolExecutor` (или `ProcessPoolExecutor`, если GIL станет узким местом). Запускаем по одной задаче на каждый ТФ из `sorted_tfs`, подаём `(tf, data[tf])`.
4. **Сбор результатов** — ждём завершения всех задач, получаем список `(tf, candles, quality_result, trend_info, phase_info, regime_info, momentum_info)`.
5. **Последовательный проход по ТФ (в порядке sorted_tfs)** — для каждого ТФ:
   - взять результат по этому ТФ из собранного списка;
   - вызвать `_update_phase_stability(tf, phase_info["phase"])` и `_update_trend_stability(tf, trend_info["direction"])`;
   - собрать `timeframes_report[tf]` (как сейчас), подставив phase_stability и trend_stability из только что вычисленных.
6. **Дальше без изменений** — контекст старшего ТФ (пересчёт фаз младших), зоны по старшему ТФ, confluence, фильтры, direction, entry_score, return.

В итоге «тяжёлый» цикл по ТФ заменён на параллельный запуск задач и один последовательный проход для истории и сборки отчёта.

---

## Что получим

- **Ускорение тика** при 3+ таймфреймах: вместо T1+T2+T3 по времени — примерно max(T1,T2,T3) + небольшой оверхед (пул, сбор, один последовательный проход).
- **Поведение** (сигналы, direction, зоны, фильтры) остаётся тем же: те же вызовы, тот же порядок обновления истории, та же логика агрегации.
- **Риски:** общая память (данные, отчёты) — при использовании потоков (ThreadPoolExecutor) разделяемые структуры те же; блокировки не нужны, так как историю обновляем только в главном потоке после join. При переходе на ProcessPoolExecutor нужно будет передавать результаты без общих мутабельных объектов.

---

## Итог одним предложением

**Пункт 1 — это параллельный расчёт по каждому ТФ (quality, trend, phase без контекста, regime, momentum) в пуле потоков/процессов с сохранением текущей последовательной логики загрузки данных, обновления истории устойчивости, контекста старшего ТФ, зон и агрегации сигнала; цель — ускорить один тик при нескольких таймфреймах.**
