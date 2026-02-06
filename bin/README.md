# Скрипты (лаунчеры)

Запуск **из корня проекта**:

```bash
python bin/catch_up_db.py
python bin/fill_gap_db.py
python bin/refresh_db.py [--yes]
python bin/refill_tf_d.py
python bin/accumulate_db.py
python bin/full_backfill.py [--clear] [--extend]
python bin/backtest_phases.py [--tf 60] [--bars N] [--min-score 0.6]
python bin/backtest_phases.py --sweep-min-score --tf 60   # таблица точности по min_score
python bin/backtest_phases.py --tune --tf 60 --bars 10000 # подбор порогов и min_score
python bin/backtest_phases.py --train-ratio 0.7 --tf 60   # train/OOS: точность по OOS ближе к форварду (см. docs/BACKTEST_OOS.md)
python bin/backtest_trend.py
python bin/backtest_trend.py --train-ratio 0.7 --tf 60   # train/OOS для тренда
python bin/backtest_trade_2025.py [--year 2025] [--tf 60] [--tp-sl trailing|fixed|atr]   # сценарий управления сделкой на одном году (один ТФ)
python bin/backtest_trade_2025.py --all-tf --year 2025   # тот же сценарий по всем ТФ из TIMEFRAMES_DB за год, сводная таблица
python bin/compare_phase_methods.py
python bin/trend_daily_full.py [--output путь.png]
python bin/trend_backtest_report.py [--tf D] [--all]
python bin/test_run_once.py
python bin/test_zones.py
python bin/orderbook_ws_demo.py [--depth 50]   # стакан по WebSocket до Ctrl+C; --duration N с, --log путь
python bin/backtest_sandbox.py --from 2025-01-01 --to 2025-12-31 [--symbol BTCUSDT] [--tick-sec 15] [--window-sec 60] [--force]  # бэктест песочницы по тикам; пройденные диапазоны не повторяются (--force = запустить снова; --mark-done = только записать диапазон как пройденный)
python bin/sandbox_backtest_report.py [--year 2025] [--trades путь]   # отчёт по бэктесту за год
python bin/sandbox_backtest_report.py --all   # сводка за 2023, 2024 и 2025 (или --years 2023,2024,2025)
python bin/download_history.py                 # инструкции по загрузке исторических тиков Bybit
python bin/download_history.py --list          # список уже скачанных файлов по SYMBOL
python bin/download_history.py --mkdir        # создать каталог data/history/trades/{SYMBOL}/
python bin/download_history.py --organize-by-year [--symbol BTCUSDT]  # раскидать CSV по папкам года (2025/, 2024/, …)
python bin/download_history.py --download --from 2025-01-01 --to 2025-12-31 [--symbol BTCUSDT]  # скачать тики с public.bybit.com
```

### Исторические данные для бэктеста

Тики для replay/бэктеста песочницы: вручную со страницы Bybit [History Data](https://www.bybit.com/derivatives/en/history-data) (Derivatives → Linear Perpetual → Trades) или автоматически: `python bin/download_history.py --download --from YYYY-MM-DD --to YYYY-MM-DD`. Файлы сохраняются в **папку по году**: `data/history/trades/{SYMBOL}/{YEAR}/` (например `trades/BTCUSDT/2025/`) в формате `{SYMBOL}{YYYY-MM-DD}.csv`. Чтение поддерживает и плоскую раскладку (`trades/{SYMBOL}/*.csv`), и подпапки по году. Опции: `--list`, `--mkdir`, `--symbol`. Бэктест песочницы по этим тикам: `python bin/backtest_sandbox.py --from YYYY-MM-DD --to YYYY-MM-DD` (используются параметры песочницы из .env; стакан в реплее синтетический из дельты). Пройденные диапазоны сохраняются в `logs/sandbox_backtest_completed.json` — повторный запуск того же диапазона пропускается; для принудительного перезапуска укажи `--force`.

В корне остаются только главные точки входа: `main.py`, `telegram_bot.py`, `check_all.py`, `release.py`.
