# -*- coding: utf-8 -*-
"""
Сбор статистики ресурсов проекта «ТехноРеалист / Архитектор Резонанса».

Запуск:
    python collect_stats.py            # снять снимок и записать в базу + data/stats.json
    python collect_stats.py --dry      # только показать, не писать

Что делает:
 1. Обходит ресурсы из списка RESOURCES (публичные API и открытые страницы).
 2. Пишет снимок в SQLite (db/stats.db): таблицы resources, snapshots, readings.
 3. Пересобирает data/stats.json для страницы статистики.
 4. Печатает сводку.

Принципы (зафиксированы в методике на странице):
 - только публично доступные показатели;
 - закрытые метрики не оцениваются и не додумываются — status="noaccess";
 - у каждого значения есть источник и время проверки;
 - повторный запуск дописывает новый снимок (история растёт).

Запуск раз в час: см. README.md рядом.
"""
import argparse
import datetime as dt
import json
import os
import re
import socket
import sqlite3
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
DATA = os.path.join(ROOT, 'data')
DB = os.path.join(BASE, 'stats.db')
TZ = dt.timezone(dt.timedelta(hours=3))  # МСК

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0 Safari/537.36')
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------- сеть и прокси
def _load_proxy():
    """Прокси для площадок, закрытых по IP (Telegram).

    Порядок: файл collect/network.json → переменные окружения.
    Пример network.json:  {"proxy": "http://127.0.0.1:8080"}
    Если включён системный VPN (TUN), прокси не нужен — трафик идёт через него.
    """
    try:
        p = os.path.join(BASE, 'network.json')
        if os.path.exists(p):
            cfg = json.load(open(p, encoding='utf-8-sig'))
            if isinstance(cfg, dict) and cfg.get('proxy'):
                return cfg['proxy']
    except Exception:
        pass
    for k in ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy'):
        v = os.environ.get(k)
        if v:
            return v
    return None


PROXY = _load_proxy()
_handlers = [urllib.request.HTTPSHandler(context=CTX)]
if PROXY:
    _handlers.append(urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY}))
OPENER = urllib.request.build_opener(*_handlers)


# ---------------------------------------------------------------- источники
def _get(url, timeout=20, headers=None):
    h = {'User-Agent': UA, 'Accept-Language': 'ru-RU,ru;q=0.9'}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with OPENER.open(req, timeout=timeout) as r:
        return r.status, r.read()


def _vk_token():
    """Токен VK: сначала переменная окружения VK_TOKEN (для серверного запуска),
    затем файл проекта «ВК/!.txt». Сам токен не печатаем."""
    env = os.environ.get('VK_TOKEN') or ''
    if re.match(r'vk1\.a\.', env.strip()):
        return env.strip()
    d = BASE
    for _ in range(4):
        cand = os.path.join(d, 'ВК', '!.txt')
        if os.path.exists(cand):
            t = open(cand, encoding='utf-8', errors='replace').read().strip()
            if re.match(r'vk1\.a\.', t):
                return t
        d = os.path.dirname(d)
    return None


def vk_group(slug):
    tok = _vk_token()
    if not tok:
        return dict(status='noaccess', note='нет токена VK API')
    u = ('https://api.vk.com/method/groups.getById?group_id=' + slug +
         '&fields=members_count,counters,description&access_token=' + tok + '&v=5.199')
    st, b = _get(u)
    j = json.loads(b.decode('utf-8', 'replace'))
    if 'error' in j:
        return dict(status='noaccess', note='VK API: ' + j['error'].get('error_msg', '')[:60])
    g = j['response']['groups'][0]
    counters = g.get('counters') or {}
    return dict(status='ok',
                subscribers=g.get('members_count'),
                publications=counters.get('wall') if isinstance(counters, dict) else None,
                views=None,
                source='VK API groups.getById',
                note=(g.get('name') or '')[:60])


def vk_user(slug):
    tok = _vk_token()
    if not tok:
        return dict(status='noaccess', note='нет токена VK API')
    u = ('https://api.vk.com/method/users.get?user_ids=' + slug +
         '&fields=followers_count&access_token=' + tok + '&v=5.199')
    st, b = _get(u)
    j = json.loads(b.decode('utf-8', 'replace'))
    if 'error' in j or not j.get('response'):
        return dict(status='noaccess', note='VK API: нет данных')
    p = j['response'][0]
    return dict(status='ok',
                subscribers=p.get('followers_count'),
                publications=None, views=None,
                source='VK API users.get',
                note=(p.get('first_name', '') + ' ' + p.get('last_name', '')).strip())


def _dzen_walk(o):
    """Считает документы канала и сумму просмотров в ответе Дзена."""
    docs, views = 0, 0
    def rec(x):
        nonlocal docs, views
        if isinstance(x, dict):
            if 'vacuum_counter_id' in (x.get('source') or {}):
                docs += 1
            v = x.get('views')
            if isinstance(v, int) and 0 <= v < 10 ** 9:
                views += v
            for y in x.values():
                rec(y)
        elif isinstance(x, list):
            for y in x:
                rec(y)
    rec(o)
    return docs, views


def dzen(channel_id=None, channel_name=None):
    if channel_id:
        u = 'https://dzen.ru/api/v3/launcher/export?channel_id=' + channel_id
    else:
        u = 'https://dzen.ru/api/v3/launcher/export?channel_name=' + urllib.parse.quote(channel_name)
    st, b = _get(u, timeout=25)
    j = json.loads(b.decode('utf-8', 'replace'))
    src = (((j.get('channel') or {}).get('source')) or {})
    subs = src.get('subscribers')
    title = src.get('title')
    docs, views = _dzen_walk(j)
    if subs is None:
        return dict(status='noaccess', note='Дзен: нет данных о канале')
    return dict(status='ok', subscribers=subs, publications=docs or None,
                views=views or None,
                source='Дзен, публичный API канала',
                note=(title or '')[:60])


def tenchat(uid):
    """TenChat: подписчики видны на публичной странице профиля."""
    st, b = _get('https://tenchat.ru/%s/subscribers' % uid, timeout=25)
    t = b.decode('utf-8', 'replace')
    m = (re.search(r'в TenChat:\s*(\d[\d\s]*)', t)
         or re.search(r'>(\d[\d\s]*)</p><!--\]--><!--\[--><p[^>]*data-cy="unit">подписчик', t)
         or re.search(r'(\d[\d\s]*)\s*подписчик', t))
    if not m:
        return dict(status='noaccess', note='TenChat: число подписчиков не найдено на странице')
    n = int(re.sub(r'\s+', '', m.group(1)))
    return dict(status='ok', subscribers=n, publications=None, views=None,
                source='TenChat, публичная страница профиля',
                note='профиль участника команды')


def telegram_page(channel):
    """Telegram: публичная превью-страница отдаёт число подписчиков без входа.

    Работает тогда, когда сеть до t.me доступна — то есть при включённом
    системном VPN/прокси: запросы с этой машины пойдут через него сами,
    без ручных действий.
    """
    err = ''
    for url in ('https://t.me/s/' + channel, 'https://t.me/' + channel,
                'https://telegram.me/' + channel):
        try:
            st, b = _get(url, timeout=15)
        except Exception as e:
            err = type(e).__name__
            continue
        t = b.decode('utf-8', 'replace')
        m = (re.search(r'([\d\s\u00a0]{1,12})\s*(?:subscribers|подписчик)', t, re.I)
             or re.search(r'og:description"\s+content="([^"]*)"', t))
        if m:
            digits = re.sub(r'\D', '', m.group(1))
            if digits:
                return dict(status='ok', subscribers=int(digits), publications=None, views=None,
                            source='t.me, публичная страница канала', note='@' + channel)
    return dict(status='noaccess',
                note='сеть до t.me недоступна' + ((' (%s)' % err) if err else '') + '; нужен VPN/прокси')


def rutube_person(pid):
    u = 'https://rutube.ru/api/video/person/%s/?limit=100&format=json' % pid
    st, b = _get(u, timeout=25)
    j = json.loads(b.decode('utf-8', 'replace'))
    res = j.get('results') or []
    views = sum((r.get('hits') or 0) for r in res)
    return dict(status='ok', subscribers=None, publications=len(res),
                views=views if res else None,
                source='Rutube API video/person',
                note='видео в канале')


def http_page(url):
    """Живость страницы: код ответа, заголовок, размер."""
    try:
        st, b = _get(url, timeout=20)
        t = b.decode('utf-8', 'replace')
        title = (re.findall(r'<title[^>]*>(.*?)</title>', t, re.S) or [''])[0]
        title = re.sub(r'\s+', ' ', title).strip()[:80]
        return dict(status='ok', subscribers=None, publications=None, views=None,
                    source='HTTP-запрос, публичная страница',
                    note=(('HTTP %s · ' % st) + title)[:90])
    except urllib.error.HTTPError as e:
        return dict(status='partial', note='HTTP %s' % e.code)
    except Exception as e:
        return dict(status='missing', note=type(e).__name__ + ': ' + str(e)[:60])


# ---------------------------------------------------------------- реестр
TEAM_NOTE = 'Площадки команды «ТехноРеалист» — трек «Промышленность», ТопБЛОГ, при кураторстве Минпромторга.'
MINE_NOTE = 'Ресурсы «Архитектора Резонанса»: сайт, каналы, медиа и площадки проекта.'

RESOURCES = [
    # --- команда
    dict(id='vk-rilltech', group='team', platform='VK', title='ТехноРеалист',
         handle='vk.com/rilltech', url='https://vk.com/rilltech',
         method=lambda: vk_group('rilltech')),
    dict(id='max-rilltech', group='team', platform='MAX', title='ТехноРеалист',
         handle='max.ru/id772328908979_biz', url='https://max.ru/id772328908979_biz',
         method=lambda: dict(http_page('https://max.ru/id772328908979_biz'),
                             status_text='счётчик не публикуется',
                             note='профиль доступен, но число подписчиков площадка публично не показывает')),
    dict(id='dzen-rilltech', group='team', platform='Дзен', title='ТехноРеалист',
         handle='dzen.ru/id/625404029e…', url='https://dzen.ru/id/625404029e04a968abdb6fcf',
         method=lambda: dzen(channel_id='625404029e04a968abdb6fcf')),
    dict(id='tenchat-galina', group='team', platform='TenChat', title='Галина Емельянова',
         handle='tenchat.ru/2206304', url='https://tenchat.ru/2206304',
         method=lambda: tenchat('2206304')),
    # --- мои
    dict(id='site-gromrez', group='mine', platform='Сайт', title='gromrez.ru · дом проекта',
         handle='gromrez.ru', url='https://gromrez.ru/', method=lambda: http_page('https://gromrez.ru/')),
    dict(id='site-syncmusic', group='mine', platform='Сайт', title='syncmusic.ru · услуги и заявки',
         handle='syncmusic.ru', url='https://syncmusic.ru/', method=lambda: http_page('https://syncmusic.ru/')),
    dict(id='site-topblog', group='mine', platform='Сайт', title='Конкурсная страница ТопБЛОГ',
         handle='syncmusic.ru/topblog/', url='https://syncmusic.ru/topblog/',
         method=lambda: http_page('https://syncmusic.ru/topblog/')),
    dict(id='site-buhanochka', group='mine', platform='Сайт', title='Фестиваль «Буханочка»',
         handle='фестиваль-буханочка.рф', url='https://фестиваль-буханочка.рф/',
         method=lambda: http_page('https://' + 'фестиваль-буханочка.рф'.encode('idna').decode('ascii') + '/')),
    dict(id='rutube-channel', group='mine', platform='Rutube', title='Игорь Громушкин · Архитектор Резонанса',
         handle='rutube.ru/channel/56517933', url='https://rutube.ru/channel/56517933/',
         method=lambda: rutube_person('56517933')),
    dict(id='tg-way', group='mine', platform='Telegram', title='Путь в Альфу',
         handle='t.me/The_way_to_alpha', url='https://t.me/The_way_to_alpha',
         method=lambda: telegram_page('The_way_to_alpha'),
         last_known=dict(subscribers=344, at='16.10.2026')),
    dict(id='tg-rezonans', group='mine', platform='Telegram', title='Громушкин · Резонанс',
         handle='t.me/gromushkin_resonance', url='https://t.me/gromushkin_resonance',
         method=lambda: telegram_page('gromushkin_resonance'),
         last_known=dict(subscribers=3, at='07.10.2026')),
    dict(id='vk-rezonans', group='mine', platform='VK', title='Громушкин · Резонанс',
         handle='vk.com/gromushkin_resonance', url='https://vk.com/gromushkin_resonance',
         method=lambda: vk_group('gromushkin_resonance')),
    dict(id='vk-igor', group='mine', platform='VK', title='Игорь Громушкин · личная страница',
         handle='vk.com/gromushkin_igor', url='https://vk.com/gromushkin_igor',
         method=lambda: vk_user('gromushkin_igor')),
    dict(id='dzen-mine', group='mine', platform='Дзен', title='Игорь Громушкин · Архитектор Резонанса',
         handle='dzen.ru/gromushkin_resonance', url='https://dzen.ru/gromushkin_resonance',
         method=lambda: dzen(channel_name='gromushkin_resonance')),
    dict(id='site-nota', group='mine', platform='Сайт', title='Реп-база «Нота»',
         handle='nota-music-studio.ai.studio', url='https://nota-music-studio.ai.studio/',
         method=lambda: http_page('https://nota-music-studio.ai.studio/')),
]


# ---------------------------------------------------------------- база
SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
    id TEXT PRIMARY KEY, grp TEXT, platform TEXT, title TEXT, handle TEXT, url TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at_iso TEXT NOT NULL,
    records INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS readings (
    snapshot_id INTEGER NOT NULL,
    resource_id TEXT NOT NULL,
    subscribers INTEGER, publications INTEGER, views INTEGER,
    status TEXT, note TEXT, source TEXT,
    PRIMARY KEY (snapshot_id, resource_id)
);
"""


STATUS_TEXT = {'ok': 'доступно', 'partial': 'частично', 'noaccess': 'нет доступа',
               'nodata': 'нет данных', 'missing': 'не найдено', 'error': 'ошибка'}

MANUAL_FILE = os.path.join(BASE, 'manual_counts.json')


def load_manual():
    """Ручные и «браузерные» значения для площадок, которые не отдают цифры анонимно.

    Два файла, оба опциональны:
      manual_counts.json     — снято со скриншота владельцем;
      authorized_values.json — снято браузером с профилем, где владелец авторизован
                               (пишет _tools\\collect_authorized.ps1).

    Значение применяется, только если автоматический способ не дал числа.
    """
    out = {}
    for name in ('manual_counts.json', 'authorized_values.json'):
        p = os.path.join(BASE, name)
        if not os.path.exists(p):
            continue
        try:
            data = json.load(open(p, encoding='utf-8-sig'))
            if isinstance(data, dict):
                out.update(data)
        except Exception:
            pass
    return out


def snapshot():
    at = dt.datetime.now(TZ)
    manual = load_manual()
    out = []
    for r in RESOURCES:
        try:
            res = r['method']()
        except Exception as e:
            res = dict(status='error', note=type(e).__name__ + ': ' + str(e)[:70])
        item = {k: r.get(k) for k in ('id', 'group', 'platform', 'title', 'handle', 'url')}
        status = res.get('status', 'error')
        item.update(dict(subscribers=res.get('subscribers'),
                         publications=res.get('publications'),
                         views=res.get('views'),
                         status=status,
                         status_text=res.get('status_text') or STATUS_TEXT.get(status, status),
                         note=res.get('note', ''),
                         source=res.get('source', ''),
                         checked_at=at.strftime('%d.%m.%Y %H:%M')))
        if r.get('last_known'):
            item['last_known'] = r['last_known']
        m = manual.get(r['id'])
        if m and item['subscribers'] is None and m.get('subscribers') is not None:
            item['subscribers'] = m['subscribers']
            item['status'] = 'ok'
            item['status_text'] = m.get('status_text') or 'по скриншоту'
            item['source'] = m.get('source', 'ручное снятие со скриншота')
            item['note'] = m.get('note', '')
            if m.get('at'):
                item['checked_at'] = m['at']
            if m.get('screenshot'):
                item['evidence'] = m['screenshot']
        out.append(item)
    return at, out


def save(at, items, dry=False):
    if dry:
        return None
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    for r in RESOURCES:
        conn.execute('INSERT OR REPLACE INTO resources (id, grp, platform, title, handle, url) '
                     'VALUES (?,?,?,?,?,?)',
                     (r['id'], r['group'], r['platform'], r['title'], r['handle'], r['url']))
    cur = conn.execute('INSERT INTO snapshots (at_iso, records) VALUES (?,?)',
                       (at.isoformat(), len(items)))
    sid = cur.lastrowid
    for it in items:
        conn.execute('INSERT INTO readings (snapshot_id, resource_id, subscribers, publications, '
                     'views, status, note, source) VALUES (?,?,?,?,?,?,?,?)',
                     (sid, it['id'], it['subscribers'], it['publications'], it['views'],
                      it['status'], it['note'], it['source']))
    conn.commit()
    conn.close()
    return sid


def build_json(at, items, sid=None):
    def total(key, grp=None):
        vals = [i[key] for i in items if i[key] is not None and (grp is None or i['group'] == grp)]
        return sum(vals) if vals else None

    groups = [
        dict(id='team', title='Площадки команды «ТехноРеалист»', note=TEAM_NOTE),
        dict(id='mine', title='Ресурсы «Архитектора Резонанса»', note=MINE_NOTE),
    ]
    hist = []
    if os.path.exists(DB):
        conn = sqlite3.connect(DB)
        rows = conn.execute(
            'SELECT s.at_iso, SUM(r.subscribers), SUM(r.views) FROM snapshots s '
            'JOIN readings r ON r.snapshot_id = s.id GROUP BY s.id ORDER BY s.id').fetchall()
        conn.close()
        for a, subs, views in rows:
            hist.append(dict(at=a, subscribers=subs, views=views))

    stats = dict(
        schema=1,
        meta=dict(
            snapshot_at=at.isoformat(),
            snapshot_human=at.strftime('%d.%m.%Y, %H:%M').replace('.', '.') + ' МСК',
            next_human=(at + dt.timedelta(hours=1)).strftime('%H:%M') + ' МСК',
            cadence_minutes=60,
            records=(sid or 0),
            collector_version='1.0',
            db='stats.db',
        ),
        groups=groups,
        totals=dict(resources=len(items),
                    team_resources=sum(1 for i in items if i['group'] == 'team'),
                    mine_resources=sum(1 for i in items if i['group'] == 'mine'),
                    subscribers=total('subscribers'),
                    publications=total('publications'),
                    views=total('views')),
        resources=items,
        history=hist,
    )
    os.makedirs(DATA, exist_ok=True)
    p = os.path.join(DATA, 'stats.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    # витрина для страницы: web/build.py читает именно этот файл
    web_data = os.path.join(ROOT, 'web', 'data', 'stats.json')
    if os.path.isdir(os.path.dirname(web_data)):
        with open(web_data, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=1)
    return p


def probe():
    """Проверка сети: какие площадки доступны с этой машины прямо сейчас."""
    print('Прокси:', PROXY or 'не задан (системный VPN, если включён, работает сам)')
    tests = [
        ('Telegram (t.me)', 'https://t.me/s/durov'),
        ('Telegram API', 'https://api.telegram.org/'),
        ('VK API', 'https://api.vk.com/method/utils.getServerTime?v=5.199'),
        ('Дзен', 'https://dzen.ru/'),
        ('Rutube', 'https://rutube.ru/'),
        ('TenChat', 'https://tenchat.ru/'),
        ('Max', 'https://max.ru/'),
    ]
    for name, url in tests:
        t0 = dt.datetime.now()
        try:
            st, b = _get(url, timeout=12)
            ms = int((dt.datetime.now() - t0).total_seconds() * 1000)
            print('  OK   %-16s %s  %d Б  %d мс' % (name, st, len(b), ms))
        except Exception as e:
            print('  FAIL %-16s %s' % (name, type(e).__name__ + ': ' + str(e)[:70]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--probe', action='store_true', help='проверить доступность площадок и выйти')
    a = ap.parse_args()
    if a.probe:
        probe()
        return
    at, items = snapshot()
    sid = save(at, items, a.dry)
    p = build_json(at, items, sid)
    print('Снимок:', at.strftime('%d.%m.%Y %H:%M'), '| ресурсов:', len(items), '| id:', sid)
    for i in items:
        print('  %-16s %-9s %-28s subs=%-6s pub=%-4s views=%-6s %s' % (
            i['id'], i['platform'], i['title'][:28], i['subscribers'],
            i['publications'], i['views'], i['status']))
    print('JSON:', p)
    print('БД  :', DB)


if __name__ == '__main__':
    main()
