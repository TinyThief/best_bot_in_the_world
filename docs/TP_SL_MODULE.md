# Модуль TP/SL (src/utils/tp_sl.py)

Мощный модуль для расчёта уровней тейк-профита и стоп-лосса в бэктесте: фиксированные %, ATR-уровни, трейлинг-стоп, безубыток, композитные правила.

## Режимы

| Режим | Класс | Описание |
|-------|--------|----------|
| **fixed** | `FixedTPSL` | TP и SL в % от входа (по умолчанию 5% / 2%). |
| **atr** | `ATRBasedTPSL` | TP = entry + N×ATR, SL = entry − M×ATR (ATR на баре входа). По умолчанию N=2, M=1. |
| **trailing** | `TrailingStopTPSL` | Начальный SL в %; после триггера прибыли — перенос в безубыток; затем трейлинг (SL = high × (1 − trail_pct)). |
| **atr_trailing** | `ATRTrailingTPSL` | ATR-based начальные TP/SL; после движения в прибыль на 1×ATR — SL в безубыток, затем трейлинг от максимума (SL = high − trail_atr×ATR). |

## Использование в бэктесте

В коде: передать в `run_backtest(..., tp_sl_handler=handler)` из `src/utils/backtest_engine.py`. При заданном `tp_sl_handler` аргументы `tp_pct`/`sl_pct` не используются.

## Фабрики

- `make_fixed_handler(tp_pct=0.05, sl_pct=0.02)` — фиксированные %.
- `make_atr_handler(n_atr_tp=2.0, n_atr_sl=1.0, atr_period=14)` — ATR-уровни.
- `make_trailing_handler(initial_sl_pct, breakeven_trigger_pct, trail_trigger_pct, trail_pct, tp_pct)` — трейлинг с безубытком.
- `make_atr_trailing_handler(n_atr_tp, n_atr_sl, trail_trigger_atr, trail_atr, atr_period)` — ATR + трейлинг.

## Интерфейс handler

Любой handler реализует метод:

```python
def get_levels(
    self,
    entry_price: float,
    entry_bar_index: int,
    current_bar_index: int,
    candles: list[dict],
    state: dict,
) -> tuple[float, float]:  # (tp_price, sl_price)
```

`state` — общий словарь на одну позицию; при входе движок передаёт пустой dict, при выходе сбрасывает. В нём можно хранить, например, `_sl_level` для трейлинга или `_atr_entry` для ATR.

## Подбор параметров

Для ATR/Trailing можно менять множители в коде или вынести в аргументы CLI/конфиг. Рекомендуется прогнать несколько вариантов (fixed, atr, trailing, atr_trailing) за год и сравнить PnL и просадку.
