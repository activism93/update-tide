#!/usr/bin/env python3
import importlib.util
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('server', ROOT / 'server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
KST = server.KST
NOW = datetime(2026, 8, 10, 20, 28, 0, tzinfo=KST)

def row(train, direction, line, msg, station, recptn, code='99'):
    return {
        'updnLine': direction,
        'trainLineNm': line,
        'arvlMsg2': msg,
        'arvlMsg3': station,
        'arvlCd': code,
        'barvlDt': '0',
        'btrainNo': train,
        'recptnDt': recptn,
        'bstatnNm': line.split('행', 1)[0] if '행' in line else '',
        'statnNm': '월곶',
    }

def candidates(rows):
    arrivals, debug = server.parse_subway_arrivals(debug=True, now=NOW, rows_override=rows)
    return arrivals, debug

# Case 1: fresh 송도 7번째 전역 keeps ~14 min.
a, d = candidates([row('6938','상행','오이도행 - 달월방면','[7]번째 전역 (송도)','송도','2026-08-10 20:27:00')])
assert a[0]['trainNo'] == '6938' and 12 <= a[0]['minutes'] <= 14, a

# Case 2: stale 6805 removed; fallback may remain but train candidate is rejected.
a, d = candidates([row('6805','하행','인천행 - 소래포구방면','[2]번째 전역 (오이도)','오이도','2026-08-10 20:23:00')])
assert any(x['trainNo']=='6805' and x['candidateStatus']=='rejected' and x['freshnessValidation']=='STALE_POSITION_REJECTED' for x in d), d
assert not any(x.get('trainNo')=='6805' for x in a), a

# Case 3: stale 6589 removed.
a, d = candidates([row('6589','하행','인천행 - 소래포구방면','[11]번째 전역 (야목)','야목','2026-08-10 20:20:00')])
assert any(x['trainNo']=='6589' and x['candidateStatus']=='rejected' for x in d), d

# Case 4: fresh far train can pass validation and sort later.
a, d = candidates([row('6591','하행','인천행 - 소래포구방면','[23]번째 전역 (기흥)','기흥','2026-08-10 20:28:00')])
assert any(x.get('trainNo')=='6591' and x.get('predictionSource')=='POSITION_REALTIME' for x in a), a

# Case 5: timestamp correction subtracts 20s from 300s remaining.
r = row('T5','하행','인천행 - 소래포구방면','[2]번째 전역 (오이도)','오이도','2026-08-10 20:27:40')
c, info = server.build_subway_candidate(r, NOW, 0)
assert 270 <= c['etaSeconds'] <= 285, c

# Case 6: 5 min old and 5 min remaining is not shown as 5 min; stale rejected.
r = row('T6','하행','인천행 - 소래포구방면','[2]번째 전역 (오이도)','오이도','2026-08-10 20:23:00')
c, info = server.build_subway_candidate(r, NOW, 0)
assert c is None and info['freshnessValidation'] == 'STALE_POSITION_REJECTED', info

# Case 7: target already passed in current direction is rejected.
r = row('T7','하행','인천행 - 소래포구방면','[3]번째 전역 (소래포구)','소래포구','2026-08-10 20:27:50')
c, info = server.build_subway_candidate(r, NOW, 0)
assert c is None and info['routeValidation'] == 'INVALID_ROUTE_REJECTED', info

# Case 8: terminal before target rejected.
r = row('T8','하행','오이도행 - 정왕방면','[3]번째 전역 (정왕)','정왕','2026-08-10 20:27:50')
c, info = server.build_subway_candidate(r, NOW, 0)
assert c is None and info['routeValidation'] == 'INVALID_ROUTE_REJECTED', info

# Case 9: no exact timetable trainNo dataset yet: validation is marked heuristic, not silently claimed exact.
r = row('T9','상행','오이도행 - 달월방면','[7]번째 전역 (송도)','송도','2026-08-10 20:27:00')
c, info = server.build_subway_candidate(r, NOW, 0)
assert info['timetableMatch'] == 'heuristic_headway', info

# Case 10: no realtime candidates => timetable fallback, no stale train.
a, d = candidates([])
assert any(x['predictionSource']=='TIMETABLE_ONLY' for x in a), a

# Case 11: target-station arrival within 60s keeps the 곧 도착 label.
r = row('T11','하행','인천행 - 소래포구방면','월곶 도착','월곶','2026-08-10 20:27:10', code='1')
c, info = server.build_subway_candidate(r, NOW, 0)
assert c is not None and not c['positionOnly'] and c['displayTime'] == '곧 도착', (c, info)

# Case 11b: target-station arrival past the 60s label window is hidden from arrival cards,
# but retained as a realtime-map position while still fresh.
r = row('T11B','하행','인천행 - 소래포구방면','월곶 도착','월곶','2026-08-10 20:26:00', code='1')
c, info = server.build_subway_candidate(r, NOW, 0)
assert c is not None and c['positionOnly'] and c['displayTime'] == '' and c.get('trainPosition'), (c, info)

# Case 11c: truly stale station arrival event should not stay on the map either.
r = row('T11C','하행','인천행 - 소래포구방면','월곶 도착','월곶','2026-08-10 20:24:00', code='1')
c, info = server.build_subway_candidate(r, NOW, 0)
assert c is None and info['freshnessValidation'] == 'STALE_STATION_EVENT_REJECTED', info

# Case 12: previous-station entering is not target-station immediate.
r = row('T12','하행','인천행 - 소래포구방면','전역 진입','달월','2026-08-10 20:27:00', code='4')
c, info = server.build_subway_candidate(r, NOW, 0)
assert c is not None and c['displayTime'] != '곧 도착' and c['minutes'] >= 1, (c, info)

print('subway ETA tests passed:', len(a), 'fallback/current candidates checked')
