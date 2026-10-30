# -*- coding: utf-8 -*-
r"""
Чтение MAX на сервере (GitHub Actions) — без компьютера владельца.

Как работает:
  * берёт токен сессии из переменных окружения MAX_AUTH и MAX_DEVICE_ID
    (это содержимое localStorage web.max.ru: __oneme_auth и __oneme_device_id);
  * запускает Chromium (Playwright) с постоянным профилем в каталоге из MAX_PROFILE_DIR,
    чтобы со второго раза не требовался новый вход;
  * подставляет токен в localStorage, открывает канал, читает «N followers»;
  * кладёт скриншот и значение в collect/authorized_values.json.

Первый вход регистрируется в MAX как новое устройство — это ожидаемо один раз.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

CHANNEL_URL = os.environ.get('MAX_CHANNEL_URL', 'https://web.max.ru/-73961623255779')
OUT_DIR = os.path.join('_доказательства', 'authorized')
VALUES = os.path.join('collect', 'authorized_values.json')


def main():
    auth = os.environ.get('MAX_AUTH', '').strip()
    device = os.environ.get('MAX_DEVICE_ID', '').strip()
    if not auth:
        print('MAX_AUTH не задан — пропускаем MAX')
        return 0
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('playwright не установлен — пропускаем MAX')
        return 0

    profile = os.environ.get('MAX_PROFILE_DIR', './max_profile')
    os.makedirs(profile, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    with sync_playwright() as p:
        launch_kw = dict(
            headless=True,
            viewport={'width': 1440, 'height': 900},
            locale='ru-RU',
            timezone_id='Europe/Moscow',
            user_agent=('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                        '(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36'),
            args=['--no-sandbox', '--disable-dev-shm-usage',
                  '--disable-blink-features=AutomationControlled'],
        )
        # Настоящий Chrome (channel='chrome') даёт тот же отпечаток, что у владельца.
        # Если его нет — откатываемся на встроенный Chromium.
        try:
            ctx = p.chromium.launch_persistent_context(profile, channel='chrome', **launch_kw)
        except Exception as exc:
            print('Chrome недоступен, берём Chromium:', str(exc)[:120])
            ctx = p.chromium.launch_persistent_context(profile, **launch_kw)
        page = ctx.new_page()
        page.goto('https://web.max.ru/', wait_until='domcontentloaded', timeout=60000)

        # токен ставим в localStorage того же origin и перезагружаем
        page.evaluate("""([auth, dev]) => {
            localStorage.setItem('__oneme_auth', auth);
            if (dev) localStorage.setItem('__oneme_device_id', dev);
        }""", [auth, device])
        page.goto(CHANNEL_URL, wait_until='domcontentloaded', timeout=60000)

        text = ''
        deadline = time.time() + 150
        while time.time() < deadline:
            text = page.inner_text('body')
            if re.search(r'\d[\d\s]*\s*followers', text, re.I):
                break
            time.sleep(3)

        if not re.search(r'\d[\d\s]*\s*followers', text, re.I):
            try:
                page.get_by_text('ТехноРеалист', exact=False).first.click(timeout=15000)
                time.sleep(10)
                text = page.inner_text('body')
            except Exception as exc:
                print('клик по каналу не удался:', str(exc)[:80])

        m = re.search(r'(\d[\d\s]*)\s*followers', text, re.I)
        title = ''
        mm = re.search(r'([^\n]+)\n\s*\d[\d\s]*\s*followers', text)
        if mm:
            title = mm.group(1).strip()

        png = os.path.join(OUT_DIR, 'max-rilltech.png')
        page.screenshot(path=png)
        open(os.path.join(OUT_DIR, 'max-rilltech.txt'), 'w', encoding='utf-8').write(
            'URL: %s\nКанал: %s\n\n%s' % (CHANNEL_URL, title, text[:4000]))
        ctx.close()

    if not m:
        print('MAX: число не найдено. Первые строки страницы:')
        print(text[:400])
        return 1

    subs = int(re.sub(r'\D', '', m.group(1)))
    tz = timezone(timedelta(hours=3))
    entry = {
        'subscribers': subs,
        'at': datetime.now(tz).strftime('%d.%m.%Y %H:%M'),
        'source': 'серверное чтение MAX (GitHub Actions, Chromium Playwright): ' + CHANNEL_URL,
        'status_text': 'по браузеру (сервер)',
        'note': ('канал «%s»' % title) if title else '',
        'screenshot': '_доказательства/authorized/max-rilltech.png',
        'dom': '_доказательства/authorized/max-rilltech.txt',
    }
    old = {}
    if os.path.exists(VALUES):
        try:
            old = json.load(open(VALUES, encoding='utf-8-sig')) or {}
        except Exception:
            old = {}
    old['max-rilltech'] = entry
    json.dump(old, open(VALUES, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('MAX:', title or '(без названия)', '| подписчиков:', subs)
    return 0


if __name__ == '__main__':
    sys.exit(main())
