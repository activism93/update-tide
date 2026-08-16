#!/usr/bin/env python3
import base64
import hashlib
import hmac
import html
import json
import os
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pymysql

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
SUBWAY_EVENT_LOG = DATA_DIR / 'subway_events.jsonl'
POST_WOLGOT_TRACKS_PATH = DATA_DIR / 'subway_post_wolgot_tracks.json'
VISIT_METRICS_PATH = DATA_DIR / 'visit_metrics.json'
GG_BASE_ARRIVAL = 'https://apis.data.go.kr/6410000/busarrivalservice/v2/getBusArrivalListv2'
GG_BASE_STATION = 'https://apis.data.go.kr/6410000/busstationservice/v2/getBusStationListv2'
GG_BASE_STATION_ROUTES = 'https://apis.data.go.kr/6410000/busstationservice/v2/getBusStationViaRouteListv2'
SEOUL_SUBWAY_ARRIVAL = 'http://swopenapi.seoul.go.kr/api/subway/{key}/json/realtimeStationArrival/0/5/{station}'
WINDY_POINT_FORECAST = 'https://api.windy.com/api/point-forecast/v2'
KMA_ULTRA_NCST = os.getenv('KMA_ULTRA_NCST_URL', 'https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getUltraSrtNcst')
KMA_ULTRA_FCST = os.getenv('KMA_ULTRA_FCST_URL', 'https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getUltraSrtFcst')
WEATHER_CACHE_TTL = int(os.getenv('WEATHER_CACHE_TTL_SECONDS', '1800'))
WOLGOT_LAT = float(os.getenv('WOLGOT_LAT', '37.39'))
WOLGOT_LON = float(os.getenv('WOLGOT_LON', '126.74'))
KMA_NX = os.getenv('KMA_NX', '56')
KMA_NY = os.getenv('KMA_NY', '123')
CACHE_TTL = int(os.getenv('BUS_CACHE_TTL_SECONDS', '30'))
SUBWAY_CACHE_TTL = int(os.getenv('SUBWAY_CACHE_TTL_SECONDS', '15'))
CACHE = {}
PORTAL_COOKIE_NAME = 'ire_resident_portal'
PORTAL_COOKIE_MAX_AGE = 60 * 60 * 24 * 30
DEFAULT_STATIONS = [
    {
        'mapNo': '1',
        'anchorId': 'stop-1',
        'stationId': '224000125',
        'stationName': '풍림아파트상가',
        'mobileNo': '25162',
        'direction': '하행 · 개봉/대야/인천 방면',
        'distance': '약 180m',
    },
    {
        'mapNo': '2',
        'anchorId': 'stop-2',
        'stationId': '224000096',
        'stationName': '풍림아파트상가',
        'mobileNo': '25164',
        'direction': '상행 · 배곧/오이도/강남 방면',
        'distance': '약 160m',
    },
]


def load_dotenv(path=BASE_DIR / '.env'):
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

def json_response(handler, payload, status=200):
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)

def fetch_json(url, params):
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f'{url}?{qs}',
        headers={'User-Agent': 'update-tide-resident-portal/1.0'}
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode('utf-8'))

def cached(key, factory, ttl=CACHE_TTL):
    now = time.time()
    hit = CACHE.get(key)
    if hit and now - hit['time'] < ttl:
        return hit['value']
    value = factory()
    CACHE[key] = {'time': now, 'value': value}
    return value

def listify(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]

def crowd_label(value):
    return {'1': '여유', '2': '보통', '3': '혼잡', '4': '매우 혼잡'}.get(str(value), '')

def parse_arrivals(station):
    key = os.getenv('GYEONGGI_BUS_API_KEY') or os.getenv('SEOUL_API_KEY')
    if not key:
        return {**station, 'arrivals': [], 'note': '버스 API 키가 설정되지 않았습니다.'}

    route_rows = []
    try:
        route_data = fetch_json(GG_BASE_STATION_ROUTES, {
            'serviceKey': key,
            'stationId': station['stationId'],
            'format': 'json'
        })
        route_body = route_data.get('response', {}).get('msgBody', {})
        route_rows = listify(route_body.get('busRouteList'))
    except Exception:
        route_rows = []

    data = fetch_json(GG_BASE_ARRIVAL, {
        'serviceKey': key,
        'stationId': station['stationId'],
        'format': 'json'
    })
    header = data.get('response', {}).get('msgHeader', {})
    body = data.get('response', {}).get('msgBody', {})
    rows = listify(body.get('busArrivalList'))

    routes = {}

    def ensure_route(route_name, row=None):
        route_name = str(route_name or '').strip()
        if not route_name:
            return None
        item = routes.setdefault(route_name, {
            'routeName': route_name,
            'destination': '',
            'routeTypeName': '',
            'staOrder': None,
            'predictions': [],
            'hasPrediction': False,
        })
        if row:
            item['destination'] = item['destination'] or str(row.get('routeDestName') or '')
            item['routeTypeName'] = item['routeTypeName'] or str(row.get('routeTypeName') or '')
            item['staOrder'] = item['staOrder'] if item['staOrder'] is not None else row.get('staOrder')
        return item

    for row in route_rows:
        ensure_route(row.get('routeName'), row)

    for row in rows:
        route = ensure_route(row.get('routeName') or row.get('routeId'), row)
        if not route:
            continue
        for order in (1, 2):
            predict = row.get(f'predictTime{order}')
            if predict in (None, '', 0, '0'):
                continue
            route['hasPrediction'] = True
            route['predictions'].append({
                'minutes': int(predict),
                'seconds': int(row.get(f'predictTimeSec{order}') or 0),
                'locationNo': row.get(f'locationNo{order}') or '',
                'plateNo': row.get(f'plateNo{order}') or '',
                'crowded': crowd_label(row.get(f'crowded{order}')),
                'lowPlate': str(row.get(f'lowPlate{order}')) == '1',
            })

    arrivals = []
    for route in routes.values():
        route['predictions'].sort(key=lambda x: (x['minutes'], x['seconds']))
        first = route['predictions'][0] if route['predictions'] else None
        second = route['predictions'][1] if len(route['predictions']) > 1 else None
        arrivals.append({
            'routeName': route['routeName'],
            'minutes': first['minutes'] if first else None,
            'seconds': first['seconds'] if first else None,
            'locationNo': first['locationNo'] if first else '',
            'plateNo': first['plateNo'] if first else '',
            'crowded': first['crowded'] if first else '',
            'destination': route['destination'],
            'routeTypeName': route['routeTypeName'],
            'staOrder': route['staOrder'],
            'lowPlate': first['lowPlate'] if first else False,
            'hasPrediction': bool(first),
            'statusText': '' if first else '도착 예정 없음',
            'nextMinutes': second['minutes'] if second else None,
        })

    arrivals.sort(key=lambda x: (x['minutes'] is None, x['minutes'] or 9999, str(x['routeName'])))
    return {
        **station,
        'arrivals': arrivals,
        'resultCode': header.get('resultCode'),
        'resultMessage': header.get('resultMessage'),
        'updatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }

def handle_bus_arrivals(handler):
    record_metric(handler, 'bus')
    def factory():
        stations = [parse_arrivals(s) for s in DEFAULT_STATIONS]
        return {
            'title': '이레하이니스 주변 버스 도착',
            'stations': stations,
            'source': '경기도 버스도착정보 API',
        }
    try:
        json_response(handler, cached('bus-arrivals-default', factory))
    except Exception as exc:
        json_response(handler, {
            'title': '이레하이니스 주변 버스 도착',
            'stations': [{**s, 'arrivals': []} for s in DEFAULT_STATIONS],
            'note': f'버스 정보를 불러오지 못했습니다: {exc}',
            'source': '경기도 버스도착정보 API',
        }, status=502)


KST = ZoneInfo('Asia/Seoul')
SUBWAY_FRESH_STRONG_SECONDS = 90
SUBWAY_FRESH_MAX_SECONDS = 180
SUBWAY_PASSED_GRACE_SECONDS = 30
POST_WOLGOT_TERMINAL_HOLD_SECONDS = 60
WOLGOT_ROUTE = ['청량리', '왕십리', '서울숲', '압구정로데오', '강남구청', '선정릉', '선릉', '한티', '도곡', '구룡', '개포동', '대모산입구', '수서', '복정', '가천대', '태평', '모란', '야탑', '이매', '서현', '수내', '정자', '미금', '오리', '죽전', '보정', '구성', '신갈', '기흥', '상갈', '청명', '영통', '망포', '매탄권선', '수원시청', '매교', '수원', '고색', '오목천', '어천', '야목', '사리', '한대앞', '중앙', '고잔', '초지', '안산', '신길온천', '정왕', '오이도', '달월', '월곶', '소래포구', '인천논현', '호구포', '남동인더스파크', '원인재', '연수', '송도', '인하대', '숭의', '신포', '인천']
WOLGOT_INDEX = WOLGOT_ROUTE.index('월곶')
DIRECTION_TERMINALS = {
    '상행': {'오이도', '왕십리', '청량리', '죽전', '고색'},
    '하행': {'인천', '오이도'},
}
POST_WOLGOT_TRACKS = {}


def load_post_wolgot_tracks():
    if POST_WOLGOT_TRACKS or not POST_WOLGOT_TRACKS_PATH.exists():
        return
    try:
        raw = json.loads(POST_WOLGOT_TRACKS_PATH.read_text(encoding='utf-8'))
        for key, track in raw.items():
            last_signal = parse_kst_timestamp(track.get('lastSignalAt'))
            if not last_signal:
                continue
            POST_WOLGOT_TRACKS[key] = {**track, 'lastSignalAt': last_signal}
    except Exception:
        POST_WOLGOT_TRACKS.clear()


def save_post_wolgot_tracks():
    try:
        DATA_DIR.mkdir(exist_ok=True)
        serializable = {}
        for key, track in POST_WOLGOT_TRACKS.items():
            item = dict(track)
            if hasattr(item.get('lastSignalAt'), 'isoformat'):
                item['lastSignalAt'] = item['lastSignalAt'].isoformat()
            serializable[key] = item
        POST_WOLGOT_TRACKS_PATH.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass



def wind_direction_label(degrees):
    labels = ['북풍', '북동풍', '동풍', '남동풍', '남풍', '남서풍', '서풍', '북서풍']
    return labels[int((degrees + 22.5) // 45) % 8]


def fetch_windy_weather():
    key = os.getenv('WINDY_API_KEY')
    if not key:
        raise RuntimeError('Windy API key is not configured')
    body = json.dumps({
        'lat': WOLGOT_LAT,
        'lon': WOLGOT_LON,
        'model': os.getenv('WINDY_MODEL', 'gfs'),
        'parameters': ['temp', 'wind', 'windGust', 'precip', 'rh', 'pressure', 'lclouds', 'mclouds', 'hclouds', 'ptype'],
        'levels': ['surface'],
        'key': key,
    }).encode('utf-8')
    req = urllib.request.Request(
        WINDY_POINT_FORECAST,
        data=body,
        headers={'Content-Type': 'application/json', 'User-Agent': 'update-tide-resident-portal/1.0'}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    ts = data.get('ts') or []
    if not ts:
        raise RuntimeError('Windy returned no forecast timestamps')
    now_ms = int(datetime.now(KST).timestamp() * 1000)
    idx = min(range(len(ts)), key=lambda i: abs(ts[i] - now_ms))
    temp_k = data.get('temp-surface', [None])[idx]
    u = data.get('wind_u-surface', [0])[idx] or 0
    v = data.get('wind_v-surface', [0])[idx] or 0
    wind_ms = (u ** 2 + v ** 2) ** 0.5
    # meteorological direction: where wind comes from
    import math
    wind_from_deg = (math.degrees(math.atan2(-u, -v)) + 360) % 360
    gust_ms = data.get('gust-surface', [None])[idx]
    precip_m = data.get('past3hprecip-surface', [0])[idx] or 0
    rh = data.get('rh-surface', [None])[idx]
    pressure_pa = data.get('pressure-surface', [None])[idx]
    low_clouds = data.get('lclouds-surface', [0])[idx] or 0
    mid_clouds = data.get('mclouds-surface', [0])[idx] or 0
    high_clouds = data.get('hclouds-surface', [0])[idx] or 0
    cloud_cover = max(low_clouds, mid_clouds, high_clouds)
    ptype = data.get('ptype-surface', [None])[idx]
    precip_mm = precip_m * 1000
    if precip_mm >= 0.2:
        condition = '비'
    elif cloud_cover >= 80:
        condition = '흐림'
    elif cloud_cover >= 45:
        condition = '구름 많음'
    elif cloud_cover >= 20:
        condition = '구름 조금'
    else:
        condition = '맑음'
    forecast_at = datetime.fromtimestamp(ts[idx] / 1000, tz=KST)
    return {
        'location': '월곶 이레하이니스',
        'model': os.getenv('WINDY_MODEL', 'gfs').upper(),
        'forecastAt': forecast_at.isoformat(),
        'temperatureC': round(temp_k - 273.15, 1) if temp_k is not None else None,
        'windSpeedMs': round(wind_ms, 1),
        'windSpeedKmh': round(wind_ms * 3.6, 1),
        'windDirectionDeg': round(wind_from_deg),
        'windDirection': wind_direction_label(wind_from_deg),
        'windGustMs': round(gust_ms, 1) if gust_ms is not None else None,
        'condition': condition,
        'cloudCover': round(cloud_cover),
        'precipType': ptype,
        'precipMm3h': round(precip_mm, 1),
        'humidity': round(rh) if rh is not None else None,
        'pressureHpa': round(pressure_pa / 100) if pressure_pa is not None else None,
        'source': 'Windy Point Forecast API',
        'updatedAt': datetime.now(KST).isoformat(),
    }



def kma_base_datetime(now=None):
    current = now or datetime.now(KST)
    # 초단기 실황/예보는 보통 매시 30~40분 이후 안정적으로 열립니다.
    base = current - timedelta(minutes=45)
    return base.strftime('%Y%m%d'), base.strftime('%H00')


def kma_request(url, params):
    key = os.getenv('KMA_API_KEY') or os.getenv('KMA_SERVICE_KEY')
    if not key:
        raise RuntimeError('KMA API key is not configured')
    query = urllib.parse.urlencode({
        'authKey': key,
        'pageNo': 1,
        'numOfRows': 1000,
        'dataType': 'JSON',
        'nx': KMA_NX,
        'ny': KMA_NY,
        **params,
    }, safe='%')
    req = urllib.request.Request(f'{url}?{query}', headers={'User-Agent': 'update-tide-resident-portal/1.0'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    header = data.get('response', {}).get('header', {})
    if header.get('resultCode') not in (None, '00'):
        raise RuntimeError(header.get('resultMsg') or 'KMA API error')
    return data.get('response', {}).get('body', {}).get('items', {}).get('item', [])


def kma_value_map(items, value_key='obsrValue'):
    values = {}
    for item in items:
        category = item.get('category')
        if category:
            values[category] = item.get(value_key)
    return values


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def kma_condition(pty, sky=None):
    pty_label = {
        '1': '비', '2': '비/눈', '3': '눈', '5': '빗방울', '6': '빗방울/눈날림', '7': '눈날림'
    }.get(str(pty))
    if pty_label:
        return pty_label
    return {'1': '맑음', '3': '구름 많음', '4': '흐림'}.get(str(sky), '맑음')


def fetch_kma_weather():
    base_date, base_time = kma_base_datetime()
    ncst_items = kma_request(KMA_ULTRA_NCST, {'base_date': base_date, 'base_time': base_time})
    ncst = kma_value_map(ncst_items, 'obsrValue')
    fcst_items = kma_request(KMA_ULTRA_FCST, {'base_date': base_date, 'base_time': base_time})
    forecasts = {}
    for item in fcst_items:
        key = (item.get('fcstDate'), item.get('fcstTime'))
        forecasts.setdefault(key, {})[item.get('category')] = item.get('fcstValue')
    forecast_key = min(forecasts.keys(), key=lambda k: abs(datetime.strptime(''.join(k), '%Y%m%d%H%M').replace(tzinfo=KST).timestamp() - datetime.now(KST).timestamp())) if forecasts else None
    fcst = forecasts.get(forecast_key, {}) if forecast_key else {}
    u = to_float(ncst.get('UUU'))
    v = to_float(ncst.get('VVV'))
    wind_ms = ((u or 0) ** 2 + (v or 0) ** 2) ** 0.5 if u is not None or v is not None else None
    import math
    wind_from_deg = (math.degrees(math.atan2(-(u or 0), -(v or 0))) + 360) % 360 if wind_ms is not None else None
    return {
        'location': '월곶동',
        'model': 'KMA',
        'forecastAt': datetime.strptime(base_date + base_time, '%Y%m%d%H%M').replace(tzinfo=KST).isoformat(),
        'temperatureC': to_float(ncst.get('T1H')),
        'windSpeedMs': round(wind_ms, 1) if wind_ms is not None else None,
        'windDirectionDeg': round(wind_from_deg) if wind_from_deg is not None else None,
        'windDirection': wind_direction_label(wind_from_deg) if wind_from_deg is not None else None,
        'windGustMs': None,
        'condition': kma_condition(ncst.get('PTY'), fcst.get('SKY')),
        'cloudCover': None,
        'precipType': ncst.get('PTY'),
        'precipMm1h': to_float(ncst.get('RN1')),
        'precipMm3h': to_float(ncst.get('RN1')),
        'humidity': round(to_float(ncst.get('REH'))) if to_float(ncst.get('REH')) is not None else None,
        'pressureHpa': None,
        'source': '기상청 초단기실황/초단기예보',
        'updatedAt': datetime.now(KST).isoformat(),
    }


def fetch_weather():
    try:
        kma = fetch_kma_weather()
    except Exception as exc:
        return {
            'location': '월곶동',
            'model': 'KMA',
            'isUnavailable': True,
            'condition': None,
            'temperatureC': None,
            'windSpeedMs': None,
            'windDirection': None,
            'windGustMs': None,
            'precipMm1h': None,
            'humidity': None,
            'source': '기상청 초단기실황/초단기예보',
            'note': f'현재 기상청 실시간 날씨 연결이 되지 않습니다: {exc}',
            'updatedAt': datetime.now(KST).isoformat(),
        }
    try:
        windy = fetch_windy_weather()
        if kma.get('windGustMs') is None:
            kma['windGustMs'] = windy.get('windGustMs')
        kma['secondarySource'] = 'Windy/GFS 돌풍만 보조'
        if kma.get('temperatureC') is not None and windy.get('temperatureC') is not None:
            diff = round(abs(kma['temperatureC'] - windy['temperatureC']), 1)
            if diff >= 3:
                kma['modelTemperatureDiffC'] = diff
    except Exception:
        pass
    return kma

def handle_weather(handler):
    record_metric(handler, 'ocean')
    try:
        json_response(handler, cached('weather-wolgot-kma', fetch_weather, WEATHER_CACHE_TTL))
    except Exception as exc:
        json_response(handler, {
            'location': '월곶 이레하이니스',
            'note': f'날씨 정보를 불러오지 못했습니다: {exc}',
            'source': 'Windy Point Forecast API',
        }, status=502)

def minutes_from_hhmm(value):
    hour, minute = [int(part) for part in value.split(':')[:2]]
    return hour * 60 + minute


def format_hhmm(total_minutes):
    total_minutes %= 24 * 60
    return f'{total_minutes // 60:02d}:{total_minutes % 60:02d}'


def format_display_minutes(minutes, prefix=''):
    if minutes <= 0:
        return '곧 도착' if not prefix else f'{prefix} 곧 도착'
    return f'{prefix}{minutes}분 후' if prefix else f'{minutes}분 후'


def parse_kst_timestamp(value, now=None):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(text[:19], fmt).replace(tzinfo=KST)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)
    except ValueError:
        return None


def wolgot_headway_minutes(minute_of_day, is_weekend):
    hour = minute_of_day // 60
    if is_weekend:
        if 7 <= hour < 21:
            return 12
        return 18
    if 7 <= hour < 9 or 17 <= hour < 20:
        return 8
    if 6 <= hour < 23:
        return 12
    return 18


def next_wolgot_schedule(direction, now=None, sequence=0):
    now = now or datetime.now(KST)
    weekend = now.weekday() >= 5
    if direction == '하행':
        first = minutes_from_hhmm('05:24' if not weekend else '05:28')
        last = minutes_from_hhmm('24:05')
        dest = '인천/오이도 방면'
    else:
        first = minutes_from_hhmm('05:53' if not weekend else '05:55')
        last = minutes_from_hhmm('23:26' if not weekend else '23:25')
        dest = '수원/왕십리 방면'
    current = now.hour * 60 + now.minute
    if current < first:
        next_min = first
    elif current > last:
        next_min = first + 24 * 60
    else:
        headway = wolgot_headway_minutes(current, weekend)
        steps = max(0, ((current - first) + headway - 1) // headway)
        next_min = first + steps * headway
        if next_min < current:
            next_min += headway
        next_min += max(0, sequence) * headway
        if next_min > last:
            next_min = first + 24 * 60
    diff = max(0, next_min - current)
    return {
        'time': format_hhmm(next_min),
        'minutes': diff,
        'arrivalAt': now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=next_min),
        'destination': dest,
        'basis': '시간표/배차 기준',
    }



SUBWAY_STATE_PROGRESS = {
    'STOPPED': 0.0,
    'ARRIVED': 0.0,
    'DEPARTING': 0.08,
    'DEPARTED': 0.14,
    'RUNNING': None,
    'ENTERING': 0.92,
    'UNKNOWN': 0.35,
}

def normalize_subway_state(code, message):
    code = str(code or '')
    message = str(message or '')
    if code == '1' or '도착' in message:
        return 'ARRIVED'
    if code == '2' or ('출발' in message and '전역' not in message):
        return 'DEPARTED'
    if code == '3' or '전역출발' in message:
        return 'DEPARTED'
    if code == '4' or '전역진입' in message:
        return 'ENTERING'
    if code == '5' or '진입' in message:
        return 'ENTERING'
    if '번째 전역' in message:
        return 'RUNNING'
    return 'UNKNOWN'

def adjacent_segment_seconds(start_station, end_station, direction):
    try:
        a = WOLGOT_ROUTE.index(start_station)
        b = WOLGOT_ROUTE.index(end_station)
    except ValueError:
        return 135 if direction == '하행' else 120
    west_side = max(a, b) >= WOLGOT_ROUTE.index('오이도')
    city_side = min(a, b) <= WOLGOT_ROUTE.index('수원')
    base = 150 if west_side else 125 if city_side else 135
    if direction == '상행':
        base = max(105, base - 8)
    return base

def infer_position_segment(direction, current_station, station_count, normalized_state):
    if current_station not in WOLGOT_ROUTE:
        return None
    idx = WOLGOT_ROUTE.index(current_station)
    if current_station == '월곶' or normalized_state in ('ARRIVED', 'STOPPED'):
        return current_station, current_station, 0.0, idx
    # Seoul API 월곶 station endpoint reports upstream stations approaching 월곶.
    step = -1 if direction == '상행' else 1
    next_idx = idx + step
    if next_idx < 0 or next_idx >= len(WOLGOT_ROUTE):
        return current_station, current_station, 0.0, idx
    return current_station, WOLGOT_ROUTE[next_idx], None, None

def build_train_position(candidate, debug, now, observed_at, station_count):
    current_station = candidate.get('currentStation') or ''
    direction = candidate.get('direction') or ''
    normalized = normalize_subway_state(candidate.get('arrivalCode'), candidate.get('arrivalMessage'))
    segment = infer_position_segment(direction, current_station, station_count, normalized)
    if not segment:
        debug['positionValidation'] = 'POSITION_REJECTED_NO_TOPOLOGY'
        return None
    start, end, forced_progress, forced_logical = segment
    start_idx = WOLGOT_ROUTE.index(start)
    end_idx = WOLGOT_ROUTE.index(end)
    duration = adjacent_segment_seconds(start, end, direction)
    elapsed = max(0, (now - observed_at).total_seconds())
    if forced_progress is not None:
        progress = forced_progress
    elif normalized == 'ENTERING':
        progress = SUBWAY_STATE_PROGRESS['ENTERING']
    elif normalized in ('DEPARTED', 'DEPARTING'):
        progress = max(SUBWAY_STATE_PROGRESS['DEPARTED'], min(0.9, elapsed / duration))
    elif normalized == 'RUNNING':
        progress = min(0.9, max(0.1, elapsed / duration))
    else:
        progress = max(0.05, min(0.9, elapsed / duration))
    logical = forced_logical if forced_logical is not None else start_idx + (end_idx - start_idx) * progress
    age = candidate.get('positionAgeSeconds')
    stale = age is not None and age > SUBWAY_FRESH_MAX_SECONDS
    route_ok, route_status, route_reason = route_validation(direction, current_station, candidate.get('destination'))
    validation = 'accepted' if route_ok and not stale else 'rejected'
    position = {
        'trainId': candidate.get('trainNo') or f"{direction}-{current_station}-{candidate.get('destination','')}",
        'trainNo': candidate.get('trainNo') or '',
        'direction': direction,
        'destination': candidate.get('destination') or '',
        'currentStation': current_station,
        'previousStation': start,
        'nextStation': end,
        'normalizedState': normalized,
        'rawState': candidate.get('trainState') or '',
        'rawArrivalCode': candidate.get('arrivalCode') or '',
        'positionTimestamp': observed_at.isoformat(),
        'serverTimestamp': now.isoformat(),
        'positionAgeSeconds': age,
        'segmentStartStation': start,
        'segmentEndStation': end,
        'segmentProgress': round(progress, 3),
        'estimatedSegmentTravelSeconds': duration,
        'elapsedSeconds': round(elapsed),
        'logicalPosition': round(logical, 3),
        'targetStation': '월곶',
        'etaSeconds': candidate.get('etaSeconds'),
        'etaLabel': candidate.get('displayTime'),
        'confidence': candidate.get('confidence'),
        'validationStatus': validation,
        'predictionSource': candidate.get('predictionSource'),
        'mapState': candidate.get('mapState') or 'REALTIME_TRACKED',
        'positionPrecision': candidate.get('positionPrecision') or 'realtime',
        'lastRealtimeStation': candidate.get('lastRealtimeStation') or '',
        'routeValidation': route_status,
        'routeReason': route_reason,
    }
    debug.update({
        'normalizedState': normalized,
        'segmentStart': start,
        'segmentEnd': end,
        'estimatedSegmentTravelSeconds': duration,
        'elapsedSeconds': round(elapsed),
        'calculatedProgress': round(progress, 3),
        'logicalPosition': round(logical, 3),
        'positionValidation': validation,
    })
    return position if validation == 'accepted' else None

def subway_state_label(code, message):
    code = str(code or '')
    message = str(message or '')
    if code == '1' or '도착' in message:
        return '정차/도착'
    if code == '2' or '출발' in message:
        return '출발'
    if code == '3' or '전역출발' in message:
        return '전역 출발'
    if code == '4' or '전역진입' in message:
        return '전역 진입'
    if code == '5' or '진입' in message:
        return '진입 중'
    if '번째 전역' in message:
        return '구간 이동 중'
    return '위치 확인 중'


def extract_destination(line):
    line = str(line or '')
    return line.split('행', 1)[0] + '행' if '행' in line else line


def terminal_name(destination):
    return str(destination or '').replace('행', '').strip()


def post_wolgot_step(direction):
    return -1 if direction == '상행' else 1


def post_wolgot_track_key(train_no, direction, destination):
    return f"{train_no or ''}|{direction or ''}|{terminal_name(destination) or destination or ''}"


def post_wolgot_route(direction, destination):
    dest = terminal_name(destination)
    if not dest or dest not in WOLGOT_ROUTE or direction not in ('상행', '하행'):
        return None
    terminal_idx = WOLGOT_ROUTE.index(dest)
    step = post_wolgot_step(direction)
    if (terminal_idx - WOLGOT_INDEX) * step < 0:
        return None
    return WOLGOT_ROUTE[WOLGOT_INDEX:terminal_idx + step:step]


def post_wolgot_segment_plan(direction, destination):
    route = post_wolgot_route(direction, destination)
    if not route:
        return None
    segments = []
    total = 0
    for start, end in zip(route, route[1:]):
        duration = adjacent_segment_seconds(start, end, direction)
        segments.append((start, end, duration, total))
        total += duration
    return {'route': route, 'segments': segments, 'totalSeconds': total}


def update_post_wolgot_track(candidate, observed_at):
    train_no = candidate.get('trainNo') or ''
    direction = candidate.get('direction') or ''
    destination = candidate.get('destination') or ''
    if not train_no or candidate.get('currentStation') != '월곶':
        return None
    key = post_wolgot_track_key(train_no, direction, destination)
    POST_WOLGOT_TRACKS[key] = {
        'key': key,
        'trainNo': train_no,
        'direction': direction,
        'destination': destination,
        'terminalStation': terminal_name(destination),
        'lastRealtimeStation': '월곶',
        'lastSignalAt': observed_at,
        'hasKnownTerminal': bool(post_wolgot_segment_plan(direction, destination)),
    }
    save_post_wolgot_tracks()
    return key


def build_estimated_after_wolgot_candidate(track, now):
    last_signal = track.get('lastSignalAt')
    if not last_signal:
        return None
    elapsed = max(0, (now - last_signal).total_seconds())
    direction = track.get('direction') or ''
    destination = track.get('destination') or ''
    train_no = track.get('trainNo') or ''
    plan = post_wolgot_segment_plan(direction, destination)
    progress = 0.0
    if not plan:
        if elapsed > SUBWAY_FRESH_MAX_SECONDS:
            return None
        logical = WOLGOT_INDEX
        segment_start = segment_end = '월곶'
        map_state = 'ESTIMATED_AFTER_WOLGOT'
        route_validation_status = 'ROUTE_UNKNOWN_TERMINAL_FALLBACK'
        route_reason = '종착역 미확인, fallback TTL 적용'
    else:
        total = plan['totalSeconds']
        terminal = plan['route'][-1]
        if elapsed > total + POST_WOLGOT_TERMINAL_HOLD_SECONDS:
            return None
        route_validation_status = 'ROUTE_OK'
        route_reason = '월곶 이후 종착역까지 추정 이동'
        if not plan['segments'] or elapsed >= total:
            logical = WOLGOT_ROUTE.index(terminal)
            segment_start = segment_end = terminal
            map_state = 'ARRIVED_AT_TERMINAL'
        else:
            map_state = 'ESTIMATED_AFTER_WOLGOT'
            segment_start, segment_end, duration, offset = plan['segments'][0]
            for start, end, seg_duration, seg_offset in plan['segments']:
                if elapsed < seg_offset + seg_duration:
                    segment_start, segment_end, duration, offset = start, end, seg_duration, seg_offset
                    break
            progress = min(1, max(0, (elapsed - offset) / max(1, duration)))
            start_idx = WOLGOT_ROUTE.index(segment_start)
            end_idx = WOLGOT_ROUTE.index(segment_end)
            logical = start_idx + (end_idx - start_idx) * progress
    position = {
        'trainId': train_no or f"{direction}-after-wolgot-{destination}",
        'trainNo': train_no,
        'direction': direction,
        'destination': destination,
        'currentStation': segment_start,
        'previousStation': segment_start,
        'nextStation': segment_end,
        'normalizedState': map_state,
        'rawState': '월곶 이후 추정 위치',
        'rawArrivalCode': '',
        'positionTimestamp': last_signal.isoformat(),
        'serverTimestamp': now.isoformat(),
        'positionAgeSeconds': round(elapsed),
        'segmentStartStation': segment_start,
        'segmentEndStation': segment_end,
        'segmentProgress': round(progress, 3),
        'estimatedSegmentTravelSeconds': adjacent_segment_seconds(segment_start, segment_end, direction),
        'elapsedSeconds': round(elapsed),
        'logicalPosition': round(logical, 3),
        'targetStation': '월곶',
        'etaSeconds': None,
        'etaLabel': '',
        'confidence': 'estimated',
        'validationStatus': 'accepted',
        'predictionSource': 'POST_WOLGOT_ESTIMATED',
        'mapState': map_state,
        'positionPrecision': 'estimated',
        'lastRealtimeStation': '월곶',
        'routeValidation': route_validation_status,
        'routeReason': route_reason,
    }
    return {
        'direction': direction,
        'destination': destination,
        'trainLineNm': destination,
        'arrivalMessage': '월곶 이후 추정 위치',
        'currentStation': segment_start,
        'arrivalCode': '',
        'trainState': '월곶 이후 추정 위치',
        'seconds': 0,
        'minutes': None,
        'etaSeconds': None,
        'displayTime': '',
        'hasExactEta': False,
        'stationCount': None,
        'scheduledTime': '',
        'predictedArrivalTime': '',
        'predictionSource': 'POST_WOLGOT_ESTIMATED',
        'confidence': 'estimated',
        'sourceLabel': '추정 위치',
        'positionAgeSeconds': round(elapsed),
        'positionEtaMinutes': None,
        'scheduleBasis': '월곶 마지막 실시간 신호 기반 추정',
        'trainNo': train_no,
        'terminalStation': track.get('terminalStation') or '',
        'updatedAt': last_signal.strftime('%Y-%m-%d %H:%M:%S'),
        'positionOnly': True,
        'mapState': map_state,
        'positionPrecision': 'estimated',
        'lastRealtimeStation': '월곶',
        'trainPosition': position,
    }


def prune_and_build_post_wolgot_positions(now, active_keys=None):
    active_keys = set(active_keys or [])
    candidates = []
    for key in list(POST_WOLGOT_TRACKS.keys()):
        if key in active_keys:
            continue
        candidate = build_estimated_after_wolgot_candidate(POST_WOLGOT_TRACKS[key], now)
        if candidate:
            candidates.append(candidate)
        else:
            POST_WOLGOT_TRACKS.pop(key, None)
    save_post_wolgot_tracks()
    return candidates


def estimate_remaining_seconds(direction, station_count, current_station=''):
    if station_count:
        seconds_per_station = 120 if direction == '상행' else 150
        return max(60, int(station_count) * seconds_per_station)
    current_station = str(current_station or '').strip()
    if current_station in WOLGOT_ROUTE:
        diff = abs(WOLGOT_ROUTE.index(current_station) - WOLGOT_INDEX)
        if diff:
            seconds_per_station = 120 if direction == '상행' else 150
            return diff * seconds_per_station
    return None


def route_validation(direction, current_station, destination):
    current_station = str(current_station or '').strip()
    dest = terminal_name(destination)
    if current_station and current_station in WOLGOT_ROUTE:
        cur_idx = WOLGOT_ROUTE.index(current_station)
        dest_idx = WOLGOT_ROUTE.index(dest) if dest in WOLGOT_ROUTE else None
        if direction == '상행' and cur_idx > WOLGOT_INDEX:
            if dest_idx is not None and dest_idx > WOLGOT_INDEX:
                return False, 'INVALID_ROUTE_REJECTED', '상행 종착역이 월곶 이전에 끝나지 않음'
            return True, 'ROUTE_OK', '현재역 이후 월곶 존재'
        if direction == '하행' and cur_idx < WOLGOT_INDEX:
            if dest_idx is not None and dest_idx < WOLGOT_INDEX:
                return False, 'INVALID_ROUTE_REJECTED', '하행 종착역이 월곶 이전이라 월곶까지 오지 않음'
            return True, 'ROUTE_OK', '현재역 이후 월곶 존재'
        if current_station == '월곶':
            return True, 'ROUTE_OK', '월곶역 도착/진입'
        return False, 'INVALID_ROUTE_REJECTED', '현재 진행방향 기준 월곶을 지났거나 반대편'
    # API's [n]번째 전역 for station arrival endpoint already means stations before target.
    return True, 'ROUTE_ASSUMED', '현재역 topology 미확인, 역도착 API 위치 정보로 가정'


def freshness_status(position_age_sec):
    if position_age_sec is None:
        return False, 'STALE_POSITION_REJECTED', 'position timestamp 없음'
    if position_age_sec <= SUBWAY_FRESH_STRONG_SECONDS:
        return True, 'FRESH_STRONG', 'fresh <=90s'
    if position_age_sec <= SUBWAY_FRESH_MAX_SECONDS:
        return True, 'FRESH_WEAK', 'usable <=180s'
    return False, 'STALE_POSITION_REJECTED', f'stale {round(position_age_sec)}s >180s'


def log_subway_events(rows):
    try:
        DATA_DIR.mkdir(exist_ok=True)
        now = datetime.now(KST).isoformat()
        with SUBWAY_EVENT_LOG.open('a', encoding='utf-8') as f:
            for row in rows:
                event = {
                    'loggedAt': now,
                    'trainNo': row.get('btrainNo') or '',
                    'station': row.get('statnNm') or '월곶',
                    'direction': row.get('updnLine') or '',
                    'line': row.get('trainLineNm') or '',
                    'message': row.get('arvlMsg2') or '',
                    'currentStation': row.get('arvlMsg3') or '',
                    'arrivalCode': row.get('arvlCd') or '',
                    'seconds': row.get('barvlDt') or '',
                    'receivedAt': row.get('recptnDt') or '',
                }
                f.write(json.dumps(event, ensure_ascii=False) + '\n')
    except Exception:
        pass


def build_subway_candidate(row, now, sequence=0):
    direction = str(row.get('updnLine') or '')
    line = str(row.get('trainLineNm') or '')
    destination = extract_destination(line)
    message = str(row.get('arvlMsg2') or '')
    current_station = row.get('arvlMsg3') or ''
    train_no = row.get('btrainNo') or ''
    arrival_code = row.get('arvlCd') or ''
    seconds = int(row.get('barvlDt') or 0)
    observed_at = parse_kst_timestamp(row.get('recptnDt'), now) or now
    age_sec = max(0, (now - observed_at).total_seconds())
    state = subway_state_label(arrival_code, message)
    station_match = re.search(r'\[(\d+)\]\s*번째 전역', message)
    station_count = int(station_match.group(1)) if station_match else None
    schedule = next_wolgot_schedule(direction, now=now, sequence=sequence)
    debug = {
        'trainNo': train_no,
        'currentStation': current_station,
        'direction': direction,
        'destination': destination,
        'terminalStation': row.get('bstatnNm') or '',
        'positionTimestamp': observed_at.isoformat(),
        'serverTimestamp': now.isoformat(),
        'positionAgeSeconds': round(age_sec),
        'targetStation': '월곶',
        'targetStationTimetableArrival': schedule['time'],
        'remainingStationCount': station_count,
        'arrivalCode': arrival_code,
        'message': message,
    }

    route_ok, route_status, route_reason = route_validation(direction, current_station, destination)
    debug.update({'routeValidation': route_status, 'routeReason': route_reason})
    if not route_ok:
        debug.update({'candidateStatus': 'rejected', 'rejectionReason': route_reason})
        return None, debug

    is_target_station_event = current_station == '월곶' or message.startswith('월곶')
    # Only target-station events are immediate. "전역 진입/도착" means the
    # previous station area, so estimate remaining travel from that station.
    is_immediate = seconds == 0 and is_target_station_event and any(word in message for word in ('도착', '진입')) and '번째 전역' not in message
    exact_eta_sec = seconds if seconds > 0 else (0 if is_immediate else None)

    position_only = False
    if exact_eta_sec is not None:
        # Split station-board wording freshness from realtime position freshness.
        # After the short label window, do not keep saying "곧 도착/도착", but
        # keep the train on the realtime map while the API position is still fresh.
        station_label_fresh_limit = 60 if is_immediate else SUBWAY_FRESH_MAX_SECONDS
        station_fresh_limit = SUBWAY_FRESH_MAX_SECONDS
        if age_sec > station_fresh_limit:
            debug.update({
                'estimatedRemainingTravelSeconds': exact_eta_sec,
                'predictedAbsoluteArrivalTime': observed_at.isoformat(),
                'currentEtaSeconds': round(-age_sec if is_immediate else exact_eta_sec - age_sec),
                'freshnessValidation': 'STALE_STATION_EVENT_REJECTED',
                'freshnessReason': f'station event stale {round(age_sec)}s >{station_fresh_limit}s',
                'timetableMatch': 'not_required_for_station_realtime',
                'candidateStatus': 'rejected',
                'rejectionReason': '오래된 도착/진입 이벤트',
            })
            return None, debug
        position_only = is_immediate and age_sec > station_label_fresh_limit
        predicted_arrival = now + timedelta(seconds=max(0, exact_eta_sec - age_sec if seconds > 0 else 0))
        source = 'STATION_REALTIME_POSITION_ONLY' if position_only else 'STATION_REALTIME'
        has_exact_eta = not position_only
        confidence = 'high'
        debug.update({
            'estimatedRemainingTravelSeconds': exact_eta_sec,
            'predictedAbsoluteArrivalTime': predicted_arrival.isoformat(),
            'currentEtaSeconds': round(max(0, exact_eta_sec - age_sec if seconds > 0 else 0)),
            'freshnessValidation': 'STATION_REALTIME_EVENT',
            'timetableMatch': 'not_required_for_station_realtime',
            'candidateStatus': 'accepted_position_only' if position_only else 'accepted',
            'rejectionReason': '',
        })
    else:
        fresh_ok, fresh_status, fresh_reason = freshness_status(age_sec)
        debug.update({'freshnessValidation': fresh_status, 'freshnessReason': fresh_reason})
        if not fresh_ok:
            debug.update({'candidateStatus': 'rejected', 'rejectionReason': fresh_reason})
            return None, debug
        remaining_sec = estimate_remaining_seconds(direction, station_count, current_station)
        debug['estimatedRemainingTravelSeconds'] = remaining_sec
        if remaining_sec is None:
            debug.update({'candidateStatus': 'rejected', 'rejectionReason': '남은 이동시간 계산 불가'})
            return None, debug
        predicted_arrival = observed_at + timedelta(seconds=remaining_sec)
        eta_sec = (predicted_arrival - now).total_seconds()
        debug.update({
            'predictedAbsoluteArrivalTime': predicted_arrival.isoformat(),
            'currentEtaSeconds': round(eta_sec),
            'timetableMatch': 'heuristic_headway',
        })
        if eta_sec < -SUBWAY_PASSED_GRACE_SECONDS:
            debug.update({'candidateStatus': 'rejected', 'rejectionReason': f'예상 도착시각 경과 {round(eta_sec)}s'})
            return None, debug
        source = 'POSITION_REALTIME' if fresh_status == 'FRESH_STRONG' else 'HYBRID_REALTIME_TIMETABLE'
        has_exact_eta = False
        confidence = 'high' if fresh_status == 'FRESH_STRONG' else 'medium'
        debug.update({'candidateStatus': 'accepted', 'rejectionReason': ''})

    eta_sec = max(0, (predicted_arrival - now).total_seconds())
    minutes = max(0, round(eta_sec / 60))
    if position_only:
        display_time = ''
    elif state in ('진입 중', '정차/도착') and eta_sec <= 60:
        display_time = '곧 도착'
    else:
        # Keep source details in predictionSource/debug; user-facing ETA should stay simple.
        display_time = format_display_minutes(minutes)
    candidate = {
        'direction': direction,
        'destination': destination,
        'trainLineNm': line,
        'arrivalMessage': message,
        'currentStation': current_station,
        'arrivalCode': arrival_code,
        'trainState': state,
        'seconds': seconds,
        'minutes': minutes,
        'etaSeconds': round(eta_sec),
        'displayTime': display_time,
        'hasExactEta': has_exact_eta,
        'stationCount': station_count,
        'scheduledTime': schedule['time'],
        'predictedArrivalTime': predicted_arrival.strftime('%H:%M:%S'),
        'predictionSource': source,
        'confidence': confidence,
        'sourceLabel': '실시간' if source in ('STATION_REALTIME', 'POSITION_REALTIME') else ('위치만 표시' if source == 'STATION_REALTIME_POSITION_ONLY' else '실시간 보정'),
        'positionAgeSeconds': round(age_sec),
        'positionEtaMinutes': round((debug.get('estimatedRemainingTravelSeconds') or 0) / 60) if debug.get('estimatedRemainingTravelSeconds') else None,
        'scheduleBasis': schedule['basis'],
        'trainNo': train_no,
        'terminalStation': row.get('bstatnNm') or '',
        'updatedAt': row.get('recptnDt') or '',
        'positionOnly': position_only,
        'mapState': 'ARRIVED_AT_WOLGOT' if is_immediate and not position_only else ('ESTIMATED_AFTER_WOLGOT' if position_only else 'REALTIME_TRACKED'),
        'positionPrecision': 'realtime' if not position_only else 'estimated',
        'lastRealtimeStation': current_station if current_station == '월곶' else '',
    }
    if is_target_station_event and current_station == '월곶':
        track_key = update_post_wolgot_track(candidate, observed_at)
        if position_only and track_key and track_key in POST_WOLGOT_TRACKS:
            estimated_candidate = build_estimated_after_wolgot_candidate(POST_WOLGOT_TRACKS[track_key], now)
            if estimated_candidate:
                return estimated_candidate, debug
    position = build_train_position(candidate, debug, now, observed_at, station_count)
    if position:
        candidate['trainPosition'] = position
    return candidate, debug


def timetable_fallback(direction, now, sequence=0):
    schedule = next_wolgot_schedule(direction, now=now, sequence=sequence)
    return {
        'direction': direction,
        'destination': schedule['destination'],
        'trainLineNm': schedule['destination'],
        'arrivalMessage': '실시간 후보 없음',
        'currentStation': '',
        'arrivalCode': '',
        'trainState': '시간표 기준',
        'seconds': 0,
        'minutes': schedule['minutes'],
        'etaSeconds': schedule['minutes'] * 60,
        'displayTime': format_display_minutes(schedule['minutes'], '시간표 기준 '),
        'hasExactEta': False,
        'stationCount': None,
        'scheduledTime': schedule['time'],
        'predictedArrivalTime': schedule['arrivalAt'].strftime('%H:%M:%S'),
        'predictionSource': 'TIMETABLE_ONLY',
        'confidence': 'fallback',
        'sourceLabel': '시간표 기준',
        'positionAgeSeconds': None,
        'positionEtaMinutes': None,
        'scheduleBasis': schedule['basis'],
        'trainNo': '',
        'terminalStation': '',
        'updatedAt': now.strftime('%Y-%m-%d %H:%M:%S'),
    }


def parse_subway_arrivals(debug=False, now=None, rows_override=None):
    now = now or datetime.now(KST)
    load_post_wolgot_tracks()
    if rows_override is None:
        key = os.getenv('SEOUL_API_KEY') or 'sample'
        station = os.getenv('SUBWAY_STATION_NAME', '월곶')
        encoded_station = urllib.parse.quote(station)
        url = SEOUL_SUBWAY_ARRIVAL.format(key=urllib.parse.quote(key, safe=''), station=encoded_station)
        req = urllib.request.Request(url, headers={'User-Agent': 'update-tide-resident-portal/1.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        rows = data.get('realtimeArrivalList') or []
        log_subway_events(rows)
    else:
        rows = rows_override
    arrivals = []
    position_only_candidates = []
    debug_rows = []
    direction_seen = {}
    active_post_wolgot_keys = set()
    for row in rows:
        direction = str(row.get('updnLine') or '')
        sequence = direction_seen.get(direction, 0)
        direction_seen[direction] = sequence + 1
        candidate, info = build_subway_candidate(row, now, sequence=sequence)
        debug_rows.append(info)
        if candidate:
            if candidate.get('trainNo'):
                active_post_wolgot_keys.add(post_wolgot_track_key(candidate.get('trainNo'), candidate.get('direction'), candidate.get('destination')))
            if candidate.get('positionOnly'):
                position_only_candidates.append(candidate)
            else:
                arrivals.append(candidate)
    arrivals.sort(key=lambda x: (x['direction'], x.get('etaSeconds', 999999)))
    # If no reliable realtime candidate exists for a direction, show explicit timetable fallback.
    for direction in ('상행', '하행'):
        if not any(a['direction'] == direction for a in arrivals):
            arrivals.append(timetable_fallback(direction, now, 0))
    arrivals.sort(key=lambda x: (x['direction'], x.get('etaSeconds', 999999)))
    position_only_candidates.extend(prune_and_build_post_wolgot_positions(now, active_post_wolgot_keys))
    if position_only_candidates:
        setattr(parse_subway_arrivals, 'last_position_only_candidates', position_only_candidates)
    else:
        setattr(parse_subway_arrivals, 'last_position_only_candidates', [])
    return (arrivals, debug_rows) if debug else arrivals

def handle_subway_arrivals(handler, query=None):
    record_metric(handler, 'subway')
    query = query or {}
    debug_enabled = query.get('debug', ['0'])[0] in ('1', 'true', 'yes') or os.getenv('SUBWAY_DEBUG') == '1'
    def factory():
        parsed = parse_subway_arrivals(debug=debug_enabled)
        arrivals, debug_rows = parsed if debug_enabled else (parsed, None)
        position_only_candidates = getattr(parse_subway_arrivals, 'last_position_only_candidates', [])
        train_positions = [a.get('trainPosition') for a in [*arrivals, *position_only_candidates] if a.get('trainPosition')]
        payload = {
            'title': '월곶역 수인분당선 도착',
            'stationName': '월곶역',
            'lineName': '수인분당선',
            'walkingInfo': '이레하이니스에서 월곶역까지 도보 약 8~12분',
            'arrivals': arrivals,
            'trainPositions': train_positions,
            'stationTopology': WOLGOT_ROUTE,
            'anchorStation': '월곶',
            'source': '서울 열린데이터광장 지하철 실시간 도착정보 API',
            'predictionPolicy': 'station realtime > fresh position realtime with timestamp correction > timetable fallback',
        }
        if debug_enabled:
            payload['debug'] = debug_rows
        return payload
    try:
        cache_key = 'subway-arrivals-wolgot-debug' if debug_enabled else 'subway-arrivals-wolgot'
        json_response(handler, cached(cache_key, factory, SUBWAY_CACHE_TTL))
    except Exception as exc:
        json_response(handler, {
            'title': '월곶역 수인분당선 도착',
            'stationName': '월곶역',
            'lineName': '수인분당선',
            'walkingInfo': '이레하이니스에서 월곶역까지 도보 약 8~12분',
            'arrivals': [],
            'note': f'지하철 정보를 불러오지 못했습니다: {exc}',
            'source': '서울 열린데이터광장 지하철 실시간 도착정보 API',
        }, status=502)

def handle_bus_station_search(handler, query):
    key = os.getenv('GYEONGGI_BUS_API_KEY') or os.getenv('SEOUL_API_KEY')
    keyword = query.get('keyword', ['월곶역'])[0]
    if not key:
        return json_response(handler, {'stations': [], 'note': '버스 API 키가 설정되지 않았습니다.'}, 500)
    try:
        data = fetch_json(GG_BASE_STATION, {'serviceKey': key, 'keyword': keyword, 'format': 'json'})
        body = data.get('response', {}).get('msgBody', {})
        stations = listify(body.get('busStationList'))
        json_response(handler, {'keyword': keyword, 'stations': stations[:20], 'source': '경기도 정류소 조회 API'})
    except Exception as exc:
        json_response(handler, {'keyword': keyword, 'stations': [], 'note': str(exc)}, 502)

def get_db_connection():
    return pymysql.connect(
        host=os.getenv('DB_HOST', '127.0.0.1'),
        port=int(os.getenv('DB_PORT', '3306')),
        user=os.getenv('DB_USER', ''),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME', ''),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )

def verify_password(password, encoded):
    try:
        algo, iterations, salt, expected = str(encoded or '').split('$', 3)
        if algo != 'pbkdf2_sha256':
            return False
        digest = hashlib.pbkdf2_hmac('sha256', str(password or '').encode(), salt.encode(), int(iterations), dklen=32).hex()
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False

def get_portal_account(username):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM resident_portal_accounts WHERE username=%s AND enabled=1 LIMIT 1', (username,))
            return cur.fetchone()

def mark_portal_login(account_id):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE resident_portal_accounts SET last_login_at=CURRENT_TIMESTAMP WHERE id=%s', (account_id,))
    except Exception:
        pass

def auth_secret():
    return (os.getenv('PORTAL_AUTH_SECRET') or os.getenv('SESSION_SECRET') or 'dev-secret-change-me').encode()

def sign_value(value):
    return hmac.new(auth_secret(), value.encode(), hashlib.sha256).hexdigest()

def make_cookie(account):
    payload = json.dumps({'id': account['id'], 'u': account['username'], 'exp': int(time.time()) + PORTAL_COOKIE_MAX_AGE}, separators=(',', ':'))
    token = base64.urlsafe_b64encode(payload.encode()).decode().rstrip('=')
    return f'{token}.{sign_value(token)}'

def parse_cookies(header):
    out = {}
    for part in str(header or '').split(';'):
        if '=' in part:
            k, v = part.strip().split('=', 1)
            out[k] = v
    return out

def is_authenticated(handler):
    return current_portal_payload(handler) is not None


def current_portal_payload(handler):
    token = parse_cookies(handler.headers.get('Cookie')).get(PORTAL_COOKIE_NAME)
    if not token or '.' not in token:
        return None
    body, sig = token.rsplit('.', 1)
    if not hmac.compare_digest(sign_value(body), sig):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)).decode())
        if int(payload.get('exp', 0)) <= int(time.time()):
            return None
        return payload
    except Exception:
        return None

def current_portal_user(handler):
    payload = current_portal_payload(handler)
    if not payload:
        return None
    username = str(payload.get('u') or '')
    role = 'admin' if username.lower() == 'admin' else 'resident'
    return {'id': payload.get('id'), 'username': username, 'role': role}

def load_visit_metrics():
    try:
        if VISIT_METRICS_PATH.exists():
            return json.loads(VISIT_METRICS_PATH.read_text())
    except Exception:
        pass
    return {'total': {}, 'daily': {}}

def save_visit_metrics(metrics):
    try:
        DATA_DIR.mkdir(exist_ok=True)
        tmp = VISIT_METRICS_PATH.with_suffix('.tmp')
        tmp.write_text(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True))
        tmp.replace(VISIT_METRICS_PATH)
    except Exception:
        pass

def metric_bucket_name(handler):
    user = current_portal_user(handler)
    return (user or {}).get('role') or 'anonymous'

def record_metric(handler, section, kind='api'):
    try:
        role = metric_bucket_name(handler)
        # Admin 화면 확인/운영 호출은 실제 입주자 사용량에서 제외합니다.
        if role == 'admin':
            return
        today = datetime.now(KST).strftime('%Y-%m-%d')
        metrics = load_visit_metrics()
        for scope in (metrics.setdefault('total', {}), metrics.setdefault('daily', {}).setdefault(today, {})):
            role_bucket = scope.setdefault(role, {})
            key = f'{kind}:{section}'
            role_bucket[key] = int(role_bucket.get(key, 0)) + 1
        save_visit_metrics(metrics)
    except Exception:
        pass

def compact_metrics_for_admin():
    metrics = load_visit_metrics()
    daily = metrics.get('daily', {})
    days = sorted(daily.keys())[-14:]
    sections = [
        ('page:home', '페이지 접속'),
        ('api:ocean', '바다·날씨 API'),
        ('api:bus', '버스정류장 API'),
        ('api:subway', '월곶역 지하철 API'),
    ]
    roles = ['resident', 'admin', 'anonymous']
    return {
        'roles': roles,
        'sections': [{'key': k, 'label': v} for k, v in sections],
        'total': metrics.get('total', {}),
        'daily': [{'date': d, 'counts': daily.get(d, {})} for d in days],
        'updatedAt': datetime.now(KST).isoformat(timespec='seconds'),
    }

def handle_portal_me(handler):
    user = current_portal_user(handler)
    if not user:
        return json_response(handler, {'authenticated': False}, 401)
    return json_response(handler, {'authenticated': True, 'username': user['username'], 'role': user['role']})

def handle_admin_metrics(handler):
    user = current_portal_user(handler)
    if not user or user.get('role') != 'admin':
        return json_response(handler, {'note': 'admin only'}, 403)
    return json_response(handler, compact_metrics_for_admin())

def send_login_page(handler, error=''):
    err = f'<p class="login-error">{html.escape(error)}</p>' if error else ''
    body = (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>입주자 로그인</title><link rel="stylesheet" href="/update-tide/styles/ocean.css?v=auth2">'
        '</head><body class="portal-login-body"><main class="portal-login"><div class="portal-login-card">'
        '<div class="login-kicker">월곶 이레하이니스</div><h1>입주자 포털 로그인</h1>'
        '<p>입주자 공용 계정으로 로그인하면 이 브라우저에서 자동 로그인됩니다.</p>'
        f'{err}<form method="post" action="/update-tide/login">'
        '<label>아이디<input name="username" autocomplete="username" required autofocus></label>'
        '<label>비밀번호<input name="password" type="password" autocomplete="current-password" required></label>'
        '<button>로그인</button></form></div></main></body></html>'
    )
    data = body.encode('utf-8')
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/html; charset=utf-8')
    handler.send_header('Content-Length', str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)

def handle_login(handler):
    length = int(handler.headers.get('Content-Length') or 0)
    params = urllib.parse.parse_qs(handler.rfile.read(length).decode('utf-8', 'replace'))
    username = (params.get('username') or [''])[0].strip()
    password = (params.get('password') or [''])[0]
    try:
        account = get_portal_account(username)
        if not account or not verify_password(password, account.get('password_hash')):
            return send_login_page(handler, '아이디 또는 비밀번호가 맞지 않습니다.')
        mark_portal_login(account['id'])
        cookie = make_cookie(account)
        handler.send_response(303)
        handler.send_header('Location', '/update-tide/')
        handler.send_header('Set-Cookie', f'{PORTAL_COOKIE_NAME}={cookie}; Max-Age={PORTAL_COOKIE_MAX_AGE}; Path=/update-tide/; HttpOnly; SameSite=Lax')
        handler.end_headers()
    except Exception:
        send_login_page(handler, '로그인 처리 중 오류가 발생했습니다.')

def handle_logout(handler):
    handler.send_response(303)
    handler.send_header('Location', '/update-tide/login')
    handler.send_header('Set-Cookie', f'{PORTAL_COOKIE_NAME}=; Max-Age=0; Path=/update-tide/; HttpOnly; SameSite=Lax')
    handler.end_headers()

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == '/update-tide':
            self.send_response(303)
            self.send_header('Location', '/update-tide/')
            self.end_headers()
            return
        if path.startswith('/update-tide/'):
            path = path[len('/update-tide'):]
            self.path = urllib.parse.urlunparse(parsed._replace(path=path))
        if path in ('/login', '/login/'):
            return send_login_page(self)
        if path in ('/logout', '/logout/'):
            return handle_logout(self)
        if path == '/api/portal/me':
            return handle_portal_me(self)
        if path == '/api/admin/metrics':
            return handle_admin_metrics(self)
        if path == '/api/bus/arrivals':
            return handle_bus_arrivals(self)
        if path == '/api/bus/stations':
            return handle_bus_station_search(self, urllib.parse.parse_qs(parsed.query))
        if path == '/api/subway/arrivals':
            return handle_subway_arrivals(self, urllib.parse.parse_qs(parsed.query))
        if path == '/api/weather':
            return handle_weather(self)
        if path == '/' or path.endswith('/index.html'):
            if not is_authenticated(self):
                self.send_response(303)
                self.send_header('Location', '/update-tide/login')
                self.end_headers()
                return
            record_metric(self, 'home', 'page')
        if path.startswith('/data/tide') and path.endswith('.json'):
            record_metric(self, 'ocean')
        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith('/update-tide/'):
            path = path[len('/update-tide'):]
            self.path = urllib.parse.urlunparse(parsed._replace(path=path))
        if path in ('/login', '/login/'):
            return handle_login(self)
        self.send_error(404)

class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

if __name__ == '__main__':
    load_dotenv()
    port = int(os.getenv('PORT', '5179'))
    host = os.getenv('HOST', '127.0.0.1')
    httpd = ReusableThreadingHTTPServer((host, port), Handler)
    print(f'update-tide server listening on http://{host}:{port}', flush=True)
    httpd.serve_forever()
