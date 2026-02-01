# Как придумать стратегию, используя аналитический блок бота

Краткое руководство: какие данные даёт аналитика, как из них собрать стратегию и как проверить её в бэктесте.

---

## 1. Что даёт аналитический блок

Вся аналитика живёт в **`src/analysis/`**. Для стратегии полезны:

### Тренд (`market_trend.py`)

- **`detect_trend(candles, lookback, timeframe=...)`**  
  Возвращает: **direction** (`"up"` | `"down"` | `"flat"`), **strength** (0..1), **trend_unclear**, **secondary_direction**, **strength_gap**.
- **`detect_regime(candles, ...)`** — режим рынка: **trend** / **range** / **surge** (по ADX, ATR, ширине BB).
- **`detect_momentum(candles, ...)`** — импульс: **momentum_state** (strong/fading/neutral), **momentum_direction**, **rsi**, **return_5**.

Использование: фильтр «в какую сторону торговать», подтверждение входа (тренд в нужную сторону, не «всплеск»).

### Фазы рынка (`market_phases.py`)

- **`detect_phase(candles, lookback, timeframe=...)`**  
  Возвращает: **phase** (accumulation, markup, distribution, markdown, capitulation, recovery), **phase_ru**, **score**, **phase_unclear**, **score_gap**, **secondary_phase**.
- Константы: **`BULLISH_PHASES`** (markup, recovery, capitulation), **`BEARISH_PHASES`** (markdown, distribution).

Использование: вход в лонг только в бычьих фазах, выход при смене на медвежью; фильтр «фаза готова к решению» (устойчивость, разрыв score).

### Торговые зоны (`trading_zones.py`)

- **`detect_trading_zones(candles, ...)`**  
  Возвращает: **levels** (уровни с ролями support/resistance и переворотами), **nearest_support** / **nearest_resistance**, **zone_low** / **zone_high**, **in_zone**, **at_support_zone** / **at_resistance_zone**, **distance_to_support_pct** / **distance_to_resistance_pct**, **recent_flips**.

Использование: вход у поддержки, выход у сопротивления; фильтр «есть запас до сопротивления» (min_distance_resistance_pct).

### МультиТФ-агрегат (`multi_tf.py`)

- **`analyze_multi_timeframe(db_conn=..., symbol=..., intervals=...)`**  
  Собирает по всем ТФ: quality, trend, phase, regime, momentum; считает **signals.direction** (long/short/none), **entry_score**, **confidence**, **phase_decision_ready**; добавляет **trading_zones** по старшему ТФ, **swing_low** / **swing_high**, **distance_to_support_pct** / **distance_to_resistance_pct**.

Использование: в реальном времени — один вызов даёт готовый сигнал и метрики; в бэктесте можно либо эмулировать этот вызов по историческим свечам, либо вызывать те же низкоуровневые функции (trend, phase, zones) по окну.

---

## 2. Контракт стратегии для бэктеста

Движок бэктеста: **`src/utils/backtest_engine.py`**.

- Сигнальная функция имеет вид:  
  **`(window, bar_index, candles, timeframe) -> "long" | "exit_long" | "none"`**
- **window** = `candles[bar_index - lookback : bar_index]` (история до текущего бара, текущий бар не входит).
- На каждом баре движок вызывает сигнальную функцию; при **position == 0** и сигнале **"long"** — вход по close; при **position == 1** сначала проверяются SL/TP, затем сигнал **"exit_long"** — выход по сигналу.

В стратегии вы **на каждом баре** по `window` (и при необходимости по `candles[bar_index]`) вызываете:

- `detect_trend(window, timeframe=timeframe)`
- `detect_phase(window, lookback=..., timeframe=timeframe)`
- `detect_trading_zones(window)` или `detect_trading_zones(window + [candles[bar_index]])` для учёта текущей цены

и по их результатам возвращаете **"long"** / **"exit_long"** / **"none"**.

---

## 3. Пошаговый процесс

### Шаг 1: Гипотеза

Сформулируйте правило в одну фразу, например:

- «Входим в лонг у поддержки, когда на старшем ТФ тренд вверх и бычья фаза; выходим у сопротивления или при смене фазы на медвежью».
- «Входим в лонг только когда мультиТФ даёт direction=long и confidence выше порога».
- «Входим в лонг при тренде вверх и фазе markup/recovery; выходим при тренде вниз или фазе distribution/markdown».

### Шаг 2: Выбор входов из аналитики

По гипотезе выберите, что нужно на вход:

| Нужно в стратегии          | Модуль / функция                          |
|---------------------------|-------------------------------------------|
| Направление тренда        | `market_trend.detect_trend` → direction   |
| Сила тренда, неясность     | `detect_trend` → strength, trend_unclear  |
| Фаза рынка                | `market_phases.detect_phase` → phase      |
| Бычья/медвежья фаза       | `BULLISH_PHASES`, `BEARISH_PHASES`        |
| Цена у поддержки/сопротивления | `trading_zones.detect_trading_zones` → at_support_zone, at_resistance_zone |
| Расстояние до уровней     | `detect_trading_zones` → distance_to_support_pct, distance_to_resistance_pct |
| Режим (тренд/флэт/всплеск)| `market_trend.detect_regime`              |
| Импульс, RSI              | `market_trend.detect_momentum`            |
| Готовность к решению (мультиТФ) | `multi_tf.analyze_multi_timeframe` → phase_decision_ready, entry_score |

### Шаг 3: Один ТФ или мультиТФ

- **Один ТФ:** на каждом баре по `window` (торговый ТФ) считаете trend, phase, zones и по ним даёте long/exit_long/none.
- **МультиТФ:** торговый ТФ — для зон и точки входа/выхода; старший ТФ — для фильтра «входить ли вообще» (тренд и фаза по старшему). На баре с временем `t` для старшего ТФ берите только свечи с `start_time <= t` и по ним считайте тренд/фазу.

### Шаг 4: Реализация сигнальной функции

- Файл стратегии — в **`strategies/`** (например `strategies/my_strategy.py`).
- Фабрика вида **`make_my_signal_fn(lookback, ...) -> SignalFn`**, внутри — функция `fn(window, bar_index, candles, timeframe)`:
  - по `window` (и при необходимости по `candles[bar_index]`) вызываете `detect_trend`, `detect_phase`, `detect_trading_zones`;
  - по флагам (тренд, фаза, зоны, пороги) решаете: вход в лонг, выход из лонга или ничего;
  - возвращаете **"long"** | **"exit_long"** | **"none"**.

Импорты из аналитики:

```python
from src.analysis.market_phases import BULLISH_PHASES, BEARISH_PHASES, detect_phase
from src.analysis.market_trend import detect_trend
from src.analysis.trading_zones import detect_trading_zones
```

### Шаг 5: Бэктест

- Скрипт бэктеста (например в **`src/scripts/`** + лаунчер в **`bin/`**) загружает свечи из БД, создаёт сигнальную функцию через вашу фабрику, вызывает **`run_backtest(candles, lookback, signal_fn, timeframe=..., tp_pct=..., sl_pct=...)`** из **`src/utils/backtest_engine.py`**.
- По результату смотрите: PnL, число сделок, просадку, выходы по TP/SL/сигналу. Дальше: подбор TP/SL, порогов (минимальный entry_score, минимальное расстояние до сопротивления и т.д.) и при необходимости — мультиТФ-фильтр по старшему ТФ.

### Шаг 6: Подключение к боту (по желанию)

- В реальном времени можно вызывать **`analyze_multi_timeframe()`** и по **signals.direction**, **entry_score**, **trading_zones** решать, показывать ли сигнал или открывать сделку (когда появится исполнение).
- Либо на каждом тике по свечам торгового ТФ вызывать те же **detect_trend**, **detect_phase**, **detect_trading_zones** и применять ту же логику, что и в сигнальной функции бэктеста — тогда поведение в бэктесте и в реале будет согласовано.

---

## 4. Принципы

1. **Одна и та же логика в бэктесте и в реале** — стратегия определяется только правилом «когда long / exit_long»; TP/SL и исполнение — отдельный слой.
2. **Не дублировать агрегацию** — мультиТФ-агрегат уже считает тренд/фазу по ТФ и даёт direction/entry_score; стратегия может опираться на них или на низкоуровневые вызовы по окну — но не смешивать без необходимости два разных определения «тренда».
3. **Сначала бэктест** — проверять идею на истории (один ТФ, потом при необходимости мультиТФ), только потом выносить в прод или в команды бота.
4. **Пороги выносить в параметры** — минимальный score фазы, минимальное расстояние до сопротивления, cooldown после выхода и т.д., чтобы их можно было подбирать и не хардкодить.

---

## 5. Где что лежит

| Что нужно | Файл / место |
|-----------|----------------|
| Тренд | `src/analysis/market_trend.py` — `detect_trend`, `detect_regime`, `detect_momentum` |
| Фазы | `src/analysis/market_phases.py` — `detect_phase`, `BULLISH_PHASES`, `BEARISH_PHASES` |
| Зоны | `src/analysis/trading_zones.py` — `detect_trading_zones` |
| МультиТФ-сигнал | `src/analysis/multi_tf.py` — `analyze_multi_timeframe` |
| Бэктест | `src/utils/backtest_engine.py` — `run_backtest`, контракт SignalFn |
| Стратегии | `strategies/` — сюда класть модули с `make_*_signal_fn` |
| Скрипты бэктеста | `src/scripts/` + лаунчеры в `bin/` |

Итого: придумать стратегию = сформулировать гипотезу → выбрать из аналитического блока тренд/фазу/зоны (и при необходимости мультиТФ) → реализовать сигнальную функцию в `strategies/` → прогонять через `backtest_engine.run_backtest` и итерировать по параметрам и условиям входа/выхода.
