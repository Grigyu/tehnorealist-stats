#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка web/index.html из web/data/stats.json и web/template.html.

Только стандартная библиотека Python. Запуск:

    python build.py

Скрипт читает JSON с данными, проверяет его по схеме, экранирует опасные
последовательности и вшивает объект в шаблон вместо маркера
__STATISTICS_JSON__. Никаких внешних зависимостей и сетевых запросов.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "template.html"
DATA = ROOT / "data" / "stats.json"
OUTPUT = ROOT / "index.html"
TOKEN = "__STATISTICS_JSON__"

# Консоль Windows может быть в cp1251/cp866; принудительно UTF-8,
# чтобы русские сообщения читались в любой среде.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

STATUSES = {"ok", "partial", "noaccess", "missing", "nodata"}
METRIC_FIELDS = ("subscribers", "publications", "views")


def fail(message: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"[build] ошибка: {message}", file=sys.stderr)
    raise SystemExit(1)


def warn(message: str) -> None:
    print(f"[build] предупреждение: {message}", file=sys.stderr)


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_metric(where: str, value: object) -> None:
    if value is None:
        return
    if not is_number(value):
        fail(f"{where}: ожидается число или null, получено {value!r}")
    if value < 0:
        fail(f"{where}: отрицательное значение {value!r}")


def load_data() -> dict:
    if not DATA.exists():
        fail(f"нет файла данных: {DATA}")

    try:
        raw = DATA.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        fail(f"{DATA.name}: файл не в UTF-8 ({exc})")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"{DATA.name}: строка {exc.lineno}, столбец {exc.colno}: {exc.msg}")

    if not isinstance(data, dict):
        fail("stats.json: ожидается объект в корне")

    for key in ("schema", "meta", "groups", "totals", "resources"):
        if key not in data:
            fail(f"stats.json: нет обязательного поля «{key}»")

    if data["schema"] != 1:
        fail(f"stats.json: schema={data['schema']!r}, поддерживается только 1")

    meta = data["meta"]
    if not isinstance(meta, dict):
        fail("stats.json: meta должен быть объектом")
    records = meta.get("records")
    if records is not None and not (is_number(records) and records >= 0):
        fail(f"stats.json: meta.records должен быть неотрицательным числом, получено {records!r}")

    groups = data["groups"]
    if not isinstance(groups, list) or not groups:
        fail("stats.json: groups должен быть непустым массивом")
    group_ids = set()
    for index, group in enumerate(groups):
        where = f"groups[{index}]"
        if not isinstance(group, dict):
            fail(f"{where}: ожидается объект")
        gid, title = group.get("id"), group.get("title")
        if not isinstance(gid, str) or not gid:
            fail(f"{where}: нужен непустой строковый id")
        if gid in group_ids:
            fail(f"{where}: повторяется id «{gid}»")
        group_ids.add(gid)
        if not isinstance(title, str) or not title:
            fail(f"{where}: нужен непустой title")

    resources = data["resources"]
    if not isinstance(resources, list):
        fail("stats.json: resources должен быть массивом")
    seen_ids = set()
    for index, res in enumerate(resources):
        where = f"resources[{index}]"
        if not isinstance(res, dict):
            fail(f"{where}: ожидается объект")
        rid = res.get("id")
        if not isinstance(rid, str) or not rid:
            fail(f"{where}: нужен непустой строковый id")
        if rid in seen_ids:
            fail(f"{where}: повторяется id «{rid}»")
        seen_ids.add(rid)
        if res.get("group") not in group_ids:
            fail(f"{where} ({rid}): группа {res.get('group')!r} не описана в groups")
        if not isinstance(res.get("title"), str) or not res.get("title"):
            fail(f"{where} ({rid}): нужен непустой title")
        if not isinstance(res.get("url"), str) or not res["url"]:
            fail(f"{where} ({rid}): нужен непустой url")
        if res.get("status") not in STATUSES:
            fail(f"{where} ({rid}): status={res.get('status')!r}, допустимо: {', '.join(sorted(STATUSES))}")
        if res.get("status_text") is not None and not isinstance(res["status_text"], str):
            fail(f"{where} ({rid}): status_text должен быть строкой")
        for field in METRIC_FIELDS:
            if field not in res:
                fail(f"{where} ({rid}): нет поля «{field}» (число или null)")
            check_metric(f"{where} ({rid}).{field}", res[field])
        last_known = res.get("last_known")
        if last_known is not None:
            if not isinstance(last_known, dict):
                fail(f"{where} ({rid}): last_known должен быть объектом")
            if last_known.get("at") is not None and not isinstance(last_known["at"], str):
                fail(f"{where} ({rid}): last_known.at должен быть строкой даты")
            for field in METRIC_FIELDS:
                if field in last_known:
                    check_metric(f"{where} ({rid}).last_known.{field}", last_known[field])

    totals = data["totals"]
    if not isinstance(totals, dict):
        fail("stats.json: totals должен быть объектом")
    for field in ("resources",) + METRIC_FIELDS:
        value = totals.get(field)
        if value is None:
            continue
        if not is_number(value) or value < 0:
            fail(f"stats.json: totals.{field} должен быть неотрицательным числом или null")

    history = data.get("history", [])
    if not isinstance(history, list):
        fail("stats.json: history должен быть массивом")
    for index, point in enumerate(history):
        where = f"history[{index}]"
        if not isinstance(point, dict):
            fail(f"{where}: ожидается объект")
        if not isinstance(point.get("at"), str) or not point["at"]:
            fail(f"{where}: нужен строковый at (ISO 8601)")
        for field in ("subscribers", "views"):
            check_metric(f"{where}.{field}", point.get(field))

    if is_number(totals.get("resources")) and totals["resources"] != len(resources):
        warn(
            "totals.resources="
            f"{totals['resources']}, а в resources {len(resources)} записей — "
            "поправьте totals.resources или список ресурсов"
        )

    return data


def build_payload(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # «<» внутри JSON всегда находится в строке: экранируем, чтобы данные
    # не могли закрыть <script> или открыть HTML-комментарий.
    payload = payload.replace("<", "\\u003c")
    # Разделители строк U+2028/U+2029 формально допустимы в JSON, но ломают JS.
    payload = payload.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return payload


def main() -> None:
    data = load_data()

    if not TEMPLATE.exists():
        fail(f"нет шаблона: {TEMPLATE}")

    template = TEMPLATE.read_text(encoding="utf-8")
    found = template.count(TOKEN)
    if found != 1:
        fail(f"template.html: маркер {TOKEN} должен встречаться ровно один раз (найдено {found})")

    html = template.replace(TOKEN, build_payload(data))
    remote_file = ROOT / "remote_url.txt"
    if remote_file.exists():
        remote_url = remote_file.read_text(encoding="utf-8").strip()
        html = html.replace("__REMOTE_STATS_URL__", remote_url)
        print(f"[build] живые данные: {remote_url}")
    else:
        html = html.replace("__REMOTE_STATS_URL__", "")

    if TOKEN in html:
        fail("index.html: маркер данных не заменён")

    with OUTPUT.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(html)

    history_count = len(data.get("history") or [])
    snapshot = (data.get("meta") or {}).get("snapshot_human") or "—"
    size_kb = OUTPUT.stat().st_size / 1024
    print(
        f"[build] данные: {len(data['groups'])} групп(ы), {len(data['resources'])} ресурсов, "
        f"история: {history_count}"
    )
    print(f"[build] снимок: {snapshot}")
    print(f"[build] записан {OUTPUT} ({size_kb:.1f} КБ)")


if __name__ == "__main__":
    main()
