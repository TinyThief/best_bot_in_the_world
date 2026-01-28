"""
Скрипт версий и выгрузки в GitHub.
Создаёт тег (версию), при необходимости коммитит изменения и пушит ветку и теги в origin.
Откат: git checkout v1.0.0

Использование:
  python release.py 1.0.0          — создать версию v1.0.0, закоммитить, запушить + тег
  python release.py 1.0.1 --tag-only — только создать тег и запушить тег (без коммита)
  python release.py                — предложит ввести версию интерактивно
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def run(cmd: list[str], check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    out = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=capture,
        text=True,
        check=check,
    )
    return out


def run_allow_fail(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=capture, text=True)


def get_current_branch() -> str | None:
    r = run_allow_fail(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if r.returncode != 0:
        return None
    return (r.stdout or "").strip() or None


def has_changes() -> bool:
    r = run_allow_fail(["git", "status", "--short"])
    return bool((r.stdout or "").strip())


def has_remote() -> bool:
    r = run_allow_fail(["git", "remote", "get-url", "origin"])
    return r.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Версия и выгрузка в GitHub (тег + push)")
    parser.add_argument("version", nargs="?", help="Версия, например 1.0.0 (будет тег v1.0.0)")
    parser.add_argument(
        "--tag-only",
        action="store_true",
        help="Только создать и запушить тег, не коммитить текущие изменения",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Не пушить в origin (только локальный коммит и тег)",
    )
    args = parser.parse_args()

    version = (args.version or "").strip()
    if not version:
        version = input("Введите версию (например 1.0.0): ").strip()
    if not version:
        print("Версия не задана. Выход.")
        return 1

    # убираем ведущий 'v', если пользователь ввёл v1.0.0
    if version.lower().startswith("v"):
        version = version[1:]
    tag_name = f"v{version}"

    # проверки
    if run_allow_fail(["git", "rev-parse", "--git-dir"]).returncode != 0:
        print("Ошибка: не найден git-репозиторий. Запустите из корня проекта после git init.")
        return 1

    branch = get_current_branch()
    if not branch:
        print("Ошибка: не удалось определить текущую ветку.")
        return 1

    if not args.no_push and not has_remote():
        print("Ошибка: нет remote origin. Добавьте: git remote add origin <url>")
        return 1

    # коммит при наличии изменений и не --tag-only
    if not args.tag_only and has_changes():
        run(["git", "add", "-A"])
        run(["git", "commit", "-m", f"Release {tag_name}"])
        print(f"Закоммичено: Release {tag_name}")
    elif not args.tag_only and not has_changes():
        print("Нет изменений в рабочей копии, коммит пропущен.")
    # тег (если уже есть — git вызовет ошибку, мы её покажем)
    run(["git", "tag", "-a", tag_name, "-m", f"Release {tag_name}"])
    print(f"Создан тег: {tag_name}")

    if not args.no_push:
        run(["git", "push", "origin", branch])
        run(["git", "push", "origin", tag_name])
        print(f"Запушено: ветка {branch}, тег {tag_name}")
    else:
        print("Push пропущен (--no-push). Чтобы отправить позже: git push origin " + branch + " && git push origin " + tag_name)

    print("\nОткат на эту версию: git checkout " + tag_name)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        print("Ошибка при выполнении:", e.cmd, file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
