#!/usr/bin/env python3
import json
import os
import time
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
GG_BASE_ARRIVAL = 'https://apis.data.go.kr/6410000/busarrivalservice/v2/getBusArrivalListv2'
GG_BASE_STATION = 'https://apis.data.go.kr/6410000/busstationservice/v2/getBusStationListv2'
CACHE_TTL = int(os.getenv('BUS_CACHE_TTL_SECONDS', '30'))
CACHE = {}
DEFAULT_STATIONS = [
    {
        'stationId': '224000096',
        'stationName': '풍림아파트상가',
        'mobileNo': '25164',
        'direction': '상행 · 배곧/오이도/강남 방면',
        'distance': '약 160m',
    },
    {
        'stationId': '224000125',
        'stationName': '풍림아파트상가',
        'mobileNo': '25162',
        'direction': '하행 · 개봉/대야/인천 방면',
        'distance': '약 180m',
    },
    {
        'stationId': '224000095',
        'stationName': '월곶포구',
        'mobileNo': '25187',
        'direction': '포구 앞 · 배곧/오이도 방면',
        'distance': '약 430m',
    },
    {
        'stationId': '224000126',
        'stationName': '월곶포구',
        'mobileNo': '25188',
        'direction': '포구 앞 · 개봉/대야/인천 방면',
        'distance': '약 450m',
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

def cached(key, factory):
    now = time.time()
    hit = CACHE.get(key)
    if hit and now - hit['time'] < CACHE_TTL:
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
    data = fetch_json(GG_BASE_ARRIVAL, {
        'serviceKey': key,
        'stationId': station['stationId'],
        'format': 'json'
    })
    header = data.get('response', {}).get('msgHeader', {})
    body = data.get('response', {}).get('msgBody', {})
    rows = listify(body.get('busArrivalList'))
    arrivals = []
    for row in rows:
        route = str(row.get('routeName') or row.get('routeId') or '')
        for order in (1, 2):
            predict = row.get(f'predictTime{order}')
            if predict in (None, '', 0, '0'):
                continue
            arrivals.append({
                'routeName': route,
                'minutes': int(predict),
                'seconds': int(row.get(f'predictTimeSec{order}') or 0),
                'locationNo': row.get(f'locationNo{order}') or '',
                'plateNo': row.get(f'plateNo{order}') or '',
                'crowded': crowd_label(row.get(f'crowded{order}')),
                'destination': row.get('routeDestName') or '',
                'lowPlate': str(row.get(f'lowPlate{order}')) == '1',
            })
    arrivals.sort(key=lambda x: (x['minutes'], x['seconds']))
    return {
        **station,
        'arrivals': arrivals[:8],
        'resultCode': header.get('resultCode'),
        'resultMessage': header.get('resultMessage'),
        'updatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }

def handle_bus_arrivals(handler):
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

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/bus/arrivals':
            return handle_bus_arrivals(self)
        if parsed.path == '/api/bus/stations':
            return handle_bus_station_search(self, urllib.parse.parse_qs(parsed.query))
        return super().do_GET()

if __name__ == '__main__':
    load_dotenv()
    port = int(os.getenv('PORT', '5179'))
    host = os.getenv('HOST', '127.0.0.1')
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f'update-tide server listening on http://{host}:{port}', flush=True)
    httpd.serve_forever()
