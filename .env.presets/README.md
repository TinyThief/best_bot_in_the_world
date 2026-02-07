# Пресеты параметров песочницы

Пресеты для быстрого переключения между вариантами настроек при итеративной оптимизации.

## Использование

1. Скопировать нужный пресет в `.env`:
   ```bash
   # Windows PowerShell
   Copy-Item .env.presets\sandbox_variant1_sl_tp.env .env -Force
   
   # Или вручную скопировать содержимое пресета в .env
   ```

2. Запустить бэктест:
   ```bash
   python bin/backtest_sandbox.py --from 2023-01-01 --to 2025-12-31 --force
   ```

3. Снять отчёт:
   ```bash
   python bin/sandbox_backtest_report.py --db --years 2023,2024,2025
   ```

4. Записать результаты в `docs/SANDBOX_BACKTEST_RESULTS.md` и сравнить с baseline.

## Пресеты

- **sandbox_baseline.env** — текущие настройки (baseline, net PnL -$214.26, win rate 27.3%)
- **sandbox_variant1_sl_tp.env** — вариант 1: включение защиты по цене (SL 2%, TP 1.5%, breakeven 0.5%, trailing)

## Добавление нового пресета

1. Создать файл `.env.presets/sandbox_variantN_name.env`
2. Указать в комментарии гипотезу и изменения
3. Добавить описание в `docs/SANDBOX_ITERATIONS.md`
4. После тестирования записать результаты в `docs/SANDBOX_BACKTEST_RESULTS.md`
