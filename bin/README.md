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
```

В корне остаются только главные точки входа: `main.py`, `telegram_bot.py`, `check_all.py`, `release.py`.
