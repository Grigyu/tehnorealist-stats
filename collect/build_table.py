# -*- coding: utf-8 -*-
"""
Итоговая таблица ресурсов для отчёта в «Сенеж» + лист показателей пилота.
Собирается из data/stats.json (результат collect_stats.py) и справочных данных команды.

Запуск: python build_table.py
Результат: ИТОГ_СТАТИСТИКА_30.10.2026.xlsx в корне папки финала.
"""
import datetime as dt
import json
import os

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
SRC = os.path.join(ROOT, 'data', 'stats.json')
OUT = os.path.join(ROOT, 'ИТОГ_СТАТИСТИКА_30.10.2026.xlsx')

NAVY = '16233D'
OCHRE = 'C08A2E'
PAPER = 'F7F8FA'
CANVAS = 'EDF0F5'
LINE = 'DCE1E8'
INK = '1C2430'
DUST = '6B7686'
BRICK = 'A4472B'

THIN = Side(style='thin', color=LINE)
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FONT = 'Arial'
SERIF = 'Georgia'


def cell(ws, r, c, v, bold=False, size=10, color=INK, fill=None, font=FONT,
         align='left', wrap=False, border=True, numfmt=None, italic=False):
    x = ws.cell(row=r, column=c, value=v)
    x.font = Font(name=font, bold=bold, size=size, color=color, italic=italic)
    x.alignment = Alignment(horizontal=align, vertical='center', wrap_text=wrap)
    if fill:
        x.fill = PatternFill('solid', fgColor=fill)
    if border:
        x.border = BOX
    if numfmt:
        x.number_format = numfmt
    return x


def title_block(ws, ncols, title, subtitle, meta):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    cell(ws, 1, 1, title, bold=True, size=16, color=NAVY, font=SERIF, border=False)
    ws.row_dimensions[1].height = 26
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
    cell(ws, 2, 1, subtitle, size=11, color=DUST, border=False)
    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=ncols)
    cell(ws, 3, 1, meta, size=9, color=DUST, italic=True, border=False)
    ws.row_dimensions[3].height = 16


def main():
    data = json.load(open(SRC, encoding='utf-8'))
    meta = data['meta']
    res = data['resources']
    totals = data['totals']
    wb = Workbook()

    # ───────────────────────── лист 1: сводка
    ws = wb.active
    ws.title = 'Сводка'
    ws.sheet_view.showGridLines = False
    widths = [4, 26, 16, 12, 12, 12, 14, 16]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    title_block(ws, 8, 'ИТОГОВАЯ ТАБЛИЦА РЕСУРСОВ',
                'Медиапроект «ТехноРеалист» и измерительный контур «Архитектор Резонанса»',
                'Срез: %s · Трек «Промышленность» · ТопБЛОГ · при кураторстве Минпромторга России · '
                'финал в Мастерской управления «Сенеж», 30.10.2026' % meta['snapshot_human'])

    r = 5
    hdr = ['', 'Группа', 'Ресурсов', 'Подписчики', 'Публикации', 'Просмотры', 'Доля подписчиков', '']
    for i, h in enumerate(hdr, 1):
        cell(ws, r, i, h, bold=True, size=9, color='FFFFFF', fill=NAVY, align='center')
    ws.row_dimensions[r].height = 22

    groups = {g['id']: g for g in data['groups']}
    r = 6
    for gid in ('team', 'mine'):
        rows = [x for x in res if x['group'] == gid]
        subs = sum(x['subscribers'] or 0 for x in rows)
        pubs = sum(x['publications'] or 0 for x in rows)
        views = sum(x['views'] or 0 for x in rows)
        share = (subs / totals['subscribers']) if totals.get('subscribers') else None
        cell(ws, r, 2, groups[gid]['title'], size=10, wrap=True)
        cell(ws, r, 3, len(rows), align='center')
        cell(ws, r, 4, subs if subs else '—', align='right', numfmt='# ##0')
        cell(ws, r, 5, pubs if pubs else '—', align='right', numfmt='# ##0')
        cell(ws, r, 6, views if views else '—', align='right', numfmt='# ##0')
        cell(ws, r, 7, ('%.0f%%' % (share * 100)) if share is not None else '—', align='center')
        r += 1
    cell(ws, r, 2, 'ИТОГО', bold=True)
    cell(ws, r, 3, totals['resources'], align='center', bold=True)
    cell(ws, r, 4, totals['subscribers'], align='right', bold=True, numfmt='# ##0', fill=CANVAS)
    cell(ws, r, 5, totals['publications'], align='right', bold=True, numfmt='# ##0', fill=CANVAS)
    cell(ws, r, 6, totals['views'], align='right', bold=True, numfmt='# ##0', fill=CANVAS)
    cell(ws, r, 7, '100%', align='center', bold=True)

    r += 3
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=8)
    cell(ws, r, 2, 'ЖИВОЙ СНИМОК', bold=True, size=9, color=OCHRE, border=False)
    r += 1
    facts = [
        ('Снимков в базе', meta.get('records') or '—'),
        ('Периодичность сбора', 'каждый час'),
        ('Следующий снимок', meta.get('next_human', '—')),
        ('Ресурсов в мониторинге', totals['resources']),
        ('Суммарная аудитория', totals['subscribers']),
        ('Просмотров публикаций', totals['views']),
    ]
    for k, v in facts:
        cell(ws, r, 2, k, size=10)
        ws.merge_cells(start_row=r, start_column=3, end_row=r, end_column=5)
        cell(ws, r, 3, v, size=10, bold=True)
        r += 1

    r += 2
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=8)
    cell(ws, r, 2,
         'Методика: учитываются только публично доступные показатели (VK API, публичный API Дзена, Rutube API, '
         'HTTP-проверка страниц). Закрытые метрики не оцениваются. Telegram и MAX не отдают публичные счётчики — '
         'для них указано последнее известное значение с датой.', size=9, color=DUST, wrap=True, border=False)
    ws.row_dimensions[r].height = 30

    # ───────────────────────── лист 2: ресурсы
    ws2 = wb.create_sheet('Ресурсы')
    ws2.sheet_view.showGridLines = False
    cols = [('№', 4), ('Группа', 20), ('Площадка', 14), ('Ресурс', 34), ('Ссылка', 34),
            ('Подписчики', 12), ('Публикации', 12), ('Просмотры', 12),
            ('Статус', 12), ('Источник данных', 30), ('Проверено', 15), ('Примечание', 38)]
    for i, (_, w) in enumerate(cols, 1):
        ws2.column_dimensions[get_column_letter(i)].width = w

    title_block(ws2, len(cols), 'ПЕРЕЧЕНЬ РЕСУРСОВ',
                'Все площадки проекта: команда и личный контур. Значения — на момент снимка.',
                'Снимок: %s · запись в базу ведётся каждый час' % meta['snapshot_human'])
    r = 5
    for i, (h, _) in enumerate(cols, 1):
        cell(ws2, r, i, h, bold=True, size=9, color='FFFFFF', fill=NAVY, align='center')
    ws2.row_dimensions[r].height = 24

    status_map = {'ok': 'доступно', 'noaccess': 'нет доступа', 'nodata': 'нет данных',
                  'partial': 'частично', 'missing': 'не найдено', 'error': 'ошибка'}
    r = 6
    n = 0
    for gid in ('team', 'mine'):
        rows = [x for x in res if x['group'] == gid]
        for x in rows:
            n += 1
            st = x.get('status_text') or status_map.get(x['status'], x['status'])
            subs = x.get('subscribers')
            extra = ''
            if subs is None and x.get('last_known'):
                subs = x['last_known']['subscribers']
                extra = 'последнее известное на %s' % x['last_known']['at']
            fill = CANVAS if gid == 'mine' else None
            cell(ws2, r, 1, n, align='center', size=9, fill=fill)
            cell(ws2, r, 2, 'Команда' if gid == 'team' else 'Проект', size=9, fill=fill)
            cell(ws2, r, 3, x['platform'], size=10, fill=fill)
            cell(ws2, r, 4, x['title'], size=10, bold=True, wrap=True, fill=fill)
            cell(ws2, r, 5, x['url'], size=8.5, color='24406B', fill=fill, wrap=True)
            cell(ws2, r, 6, subs if subs is not None else '—', align='right', numfmt='# ##0', fill=fill)
            cell(ws2, r, 7, x.get('publications') if x.get('publications') is not None else '—',
                 align='right', numfmt='# ##0', fill=fill)
            cell(ws2, r, 8, x.get('views') if x.get('views') is not None else '—',
                 align='right', numfmt='# ##0', fill=fill)
            cell(ws2, r, 9, st, size=9, fill=fill,
                 color=BRICK if x['status'] in ('noaccess', 'missing') else INK)
            cell(ws2, r, 10, x.get('source', ''), size=8.5, color=DUST, wrap=True, fill=fill)
            cell(ws2, r, 11, x.get('checked_at', ''), size=8.5, color=DUST, fill=fill)
            note = x.get('note', '') or ''
            if note.strip().lower() == (x.get('title') or '').strip().lower():
                note = ''
            if extra:
                note = (note + '; ' if note else '') + extra
            cell(ws2, r, 12, note, size=8.5, color=DUST, wrap=True, fill=fill)
            ws2.row_dimensions[r].height = 26
            r += 1

    # ───────────────────────── лист 3: показатели пилота
    ws3 = wb.create_sheet('Показатели пилота')
    ws3.sheet_view.showGridLines = False
    for i, w in enumerate([4, 22, 14, 14, 14, 12, 12, 12], 1):
        ws3.column_dimensions[get_column_letter(i)].width = w

    title_block(ws3, 8, 'ПОКАЗАТЕЛИ ПИЛОТА ПО АВТОРАМ',
                '9 недель: 3 недели подготовки и 6 недель активного постинга',
                'Данные команды «ТехноРеалист» на 08.10.2026 · таблица команды от 25.10.2026')
    r = 5
    hdr = ['', 'Автор', 'Просмотры', 'Охват', 'Комментарии', 'Лайки', 'Репосты', 'ERR']
    for i, h in enumerate(hdr, 1):
        cell(ws3, r, i, h, bold=True, size=9, color='FFFFFF', fill=NAVY, align='center')
    ws3.row_dimensions[r].height = 22

    pilots = [
        ('Проект (коллективный)', 73533, None, 662, None, 96, '1,03%'),
        ('Иван', 260300, 256958, 447, 8531, 76, '3,54%'),
        ('Татьяна', 4100, 670, None, 10, None, '1,49%'),
        ('Галина', 67612, 61520, 36, 1017, 21, '1,74%'),
        ('Альбина', 1400, 923, 11, 86, 13, '11,91%'),
        ('Юлия', 2978, 2107, 11, 12, 6, '1,37%'),
    ]
    r = 6
    for row in pilots:
        cell(ws3, r, 2, row[0], size=10, bold=True)
        for i, v in enumerate(row[1:6], start=3):
            cell(ws3, r, i, v if v is not None else '—', align='right', numfmt='# ##0')
        cell(ws3, r, 8, row[6], align='center')
        r += 1
    cell(ws3, r, 2, 'ИТОГО', bold=True, fill=CANVAS)
    cell(ws3, r, 3, 409923, bold=True, align='right', numfmt='# ##0', fill=CANVAS)
    cell(ws3, r, 4, 322178, bold=True, align='right', numfmt='# ##0', fill=CANVAS)
    cell(ws3, r, 5, 1167, bold=True, align='right', numfmt='# ##0', fill=CANVAS)
    cell(ws3, r, 6, 9656, bold=True, align='right', numfmt='# ##0', fill=CANVAS)
    cell(ws3, r, 7, 212, bold=True, align='right', numfmt='# ##0', fill=CANVAS)
    cell(ws3, r, 8, '2,4%', bold=True, align='center', fill=CANVAS)

    r += 2
    cell(ws3, r, 2, 'Публикаций за пилот', size=10)
    cell(ws3, r, 3, 100, bold=True, align='right')
    r += 1
    cell(ws3, r, 2, 'Предприятий и проектов', size=10)
    cell(ws3, r, 3, 66, bold=True, align='right')

    r += 2
    ws3.merge_cells(start_row=r, start_column=2, end_row=r, end_column=8)
    cell(ws3, r, 2, 'Источник: таблица команды «ТехноРеалист» (скриншот от 25.10.2026, срез на 08.10.2026). '
                    'ERR — вовлечённость: реакции к просмотрам, по расчёту команды.', size=9, color=DUST,
         wrap=True, border=False)
    ws3.row_dimensions[r].height = 28

    # ───────────────────────── лист 4: методика
    ws4 = wb.create_sheet('Методика')
    ws4.sheet_view.showGridLines = False
    ws4.column_dimensions['A'].width = 4
    ws4.column_dimensions['B'].width = 30
    ws4.column_dimensions['C'].width = 92
    title_block(ws4, 3, 'МЕТОДИКА И ИСТОЧНИКИ',
                'Что именно измеряется и откуда берутся числа',
                'Документ описывает, как устроен сбор статистики проекта')
    r = 5
    rows = [
        ('Принцип', 'Только публично доступные показатели. Закрытые метрики не оцениваются и не додумываются.'),
        ('Периодичность', 'Один снимок в час. Снимок пишется в базу SQLite (stats.db) и публикуется на странице.'),
        ('VK', 'VK API, метод groups.getById (сообщества) и users.get (личные страницы). Подписчики — точное значение.'),
        ('Дзен', 'Публичный API канала Дзена: подписчики, число публикаций, просмотры материалов.'),
        ('Rutube', 'Rutube API: число видео в канале и суммарные просмотры.'),
        ('Сайты', 'HTTP-проверка доступности и заголовка страницы. Посещаемость не измеряется: счётчиков на сайтах нет.'),
        ('Telegram', 'Площадка не отдаёт публичные счётчики из среды сбора. В таблице — последнее известное значение с датой.'),
        ('MAX', 'Публичный профиль доступен, но счётчик подписчиков не отдаётся.'),
        ('Дзен (личный)', 'Канал создан, подписчиков 0 — это фактическое значение, а не отсутствие данных.'),
        ('Итоги', 'Суммы считаются по ресурсам, у которых есть значение; строки с «н/д» в сумму не входят.'),
    ]
    for k, v in rows:
        cell(ws4, r, 2, k, size=10, bold=True, wrap=True)
        cell(ws4, r, 3, v, size=10, wrap=True)
        ws4.row_dimensions[r].height = 30
        r += 1

    r += 1
    ws4.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
    cell(ws4, r, 2, 'Собрано автоматически: collect/collect_stats.py · база: collect/stats.db · '
                    'страница: web/index.html · снимок: %s' % meta['snapshot_human'],
         size=9, color=DUST, italic=True, border=False)

    # печать: A4 альбомная, вписать по ширине
    for sh in wb.worksheets:
        sh.page_setup.orientation = 'landscape'
        sh.page_setup.paperSize = sh.PAPERSIZE_A4
        sh.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
        sh.page_setup.fitToWidth = 1
        sh.page_setup.fitToHeight = 0
        sh.print_options.horizontalCentered = True
    wb['Ресурсы'].print_title_rows = '5:5'

    wb.save(OUT)
    print('OK', OUT)

if __name__ == '__main__':
    main()
