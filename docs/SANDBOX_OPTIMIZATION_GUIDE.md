# Руководство по оптимизации песочницы до прода

Краткая инструкция для продолжения итеративной оптимизации параметров песочницы микроструктуры.

## Текущий статус

**Baseline выполнен:**
- Run ID: `backtest_BTCUSDT_2023-01-01_2025-12-31_1770386737`
- Net PnL: -$214.26 ❌
- Win rate: 27.3% ❌ (требуется ≥ 55%)
- Все выходы по причине "microstructure" (нет защиты по цене)

**Критерии приёмки НЕ выполнены.** Требуется итеративная оптимизация.

## Быстрый старт

### 1. Выбрать вариант для тестирования

Варианты описаны в `docs/SANDBOX_ITERATIONS.md`. Рекомендуется начать с **Варианта 1** (защита по цене).

### 2. Применить пресет

```bash
# Скопировать пресет в .env (Windows PowerShell)
Copy-Item .env.presets\sandbox_variant1_sl_tp.env .env -Force

# Или вручную скопировать нужные параметры из пресета в ваш .env
```

### 3. Запустить бэктест

```bash
python bin/backtest_sandbox.py --from 2023-01-01 --to 2025-12-31 --force
```

Сохранить **run_id** из вывода (или найти последний в БД).

### 4. Снять отчёт

```bash
# По run_id
python bin/sandbox_backtest_report.py --db --run-id <run_id>

# По годам (сводка)
python bin/sandbox_backtest_report.py --db --years 2023,2024,2025
```

### 5. Записать результаты

В `docs/SANDBOX_BACKTEST_RESULTS.md` добавить новый раздел "Вариант N" с метриками и сравнением с baseline.

### 6. Принять решение

- Если критерии выполнены → перейти к Шагу 4 (фиксация прод-пресета).
- Если улучшение есть, но критерии не выполнены → попробовать следующий вариант или комбинацию.
- Если ухудшение → откатить изменения и попробовать другой подход.

## Критерии приёмки

Песочница готова к проду, если выполнены **все** основные критерии:

1. ✅ Net PnL > 0 за весь период (2023–2025)
2. ✅ Win rate ≥ 55% при числе закрытий ≥ 50
3. ✅ Net PnL положительный хотя бы по двум из трёх лет

Дополнительно (опционально):
- Максимальная просадка ≤ 20%
- Разбивка по exit_reason показывает работу защиты по цене (take_profit, stop_loss, trailing_stop)

## Очистка бракованных и незавершённых прогонов

- **БД:** при каждом запуске бэктеста (`backtest_sandbox.py`) из БД удаляются все незавершённые прогоны (`source=backtest`, `finished_at_sec IS NULL`) и их сделки/пропуски.
- **Архивы CSV:** при создании песочницы (бэктест или основной бот) перед архивированием удаляются все старые файлы `sandbox_trades_archive_*.csv` и `sandbox_skips_archive_*.csv`. Остаётся только один свежий архив (текущий CSV переименовывается в архив с новым суффиксом).
- Лайв-прогоны (`source=live`) из БД не удаляются.

## Структура файлов

- `docs/SANDBOX_BACKTEST_RESULTS.md` — результаты всех вариантов (baseline + итерации)
- `docs/SANDBOX_ITERATIONS.md` — описание гипотез и вариантов настроек
- `docs/SANDBOX_ANALYSIS_AND_FIXES.md` — анализ и критерии приёмки
- `.env.presets/` — пресеты параметров для быстрого переключения
- `docs/SANDBOX_OPTIMIZATION_GUIDE.md` — этот файл (краткая инструкция)

## Полезные команды

```bash
# Проверить последний run_id в БД
python -c "from src.core.database import get_connection, get_sandbox_runs; conn = get_connection(); cur = conn.cursor(); runs = get_sandbox_runs(cur, source='backtest', limit=1); conn.close(); print(runs[0]['run_id'] if runs else 'No runs')"

# Список всех прогонов
python -c "from src.core.database import get_connection, get_sandbox_runs; conn = get_connection(); cur = conn.cursor(); runs = get_sandbox_runs(cur, limit=10); conn.close(); [print(f\"{r['run_id']}: {r['started_at_sec']}\") for r in runs]"
```

## Когда критерии выполнены

1. Зафиксировать прод-пресет: создать `.env.presets/sandbox_prod.env` с финальными параметрами.
2. Обновить `docs/SANDBOX_BACKTEST_RESULTS.md` — заполнить раздел "Прод-пресет".
3. Обновить `AGENT_CONTEXT.md` — перенести задачу из IN PROGRESS в DONE.
4. Опционально: создать релиз с тегом версии.
