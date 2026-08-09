#!/usr/bin/env python3
import base64
import hashlib
import hmac
import html
import json
import os
import time
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pymysql

BASE_DIR = Path(__file__).resolve().parent
GG_BASE_ARRIVAL = 'https://apis.data.go.kr/6410000/busarrivalservice/v2/getBusArrivalListv2'
GG_BASE_STATION = 'https://apis.data.go.kr/6410000/busstationservice/v2/getBusStationListv2'
GG_BASE_STATION_ROUTES = 'https://apis.data.go.kr/6410000/busstationservice/v2/getBusStationViaRouteListv2'
CACHE_TTL = int(os.getenv('BUS_CACHE_TTL_SECONDS', '30'))
CACHE = {}
PORTAL_COOKIE_NAME = 'ire_resident_portal'
PORTAL_COOKIE_MAX_AGE = 60 * 60 * 24 * 30
DEFAULT_STATIONS = [
    {
        'mapNo': '1',
        'anchorId': 'stop-1',
        'stationId': '224000096',
        'stationName': '풍림아파트상가',
        'mobileNo': '25164',
        'direction': '상행 · 배곧/오이도/강남 방면',
        'distance': '약 160m',
    },
    {
        'mapNo': '2',
        'anchorId': 'stop-2',
        'stationId': '224000125',
        'stationName': '풍림아파트상가',
        'mobileNo': '25162',
        'direction': '하행 · 개봉/대야/인천 방면',
        'distance': '약 180m',
    },
    {
        'mapNo': '3',
        'anchorId': 'stop-3',
        'stationId': '224000124',
        'stationName': '풍림아파트후문',
        'mobileNo': '25161',
        'direction': '후문 · 개봉/대야 방면',
        'distance': '약 280m',
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
    token = parse_cookies(handler.headers.get('Cookie')).get(PORTAL_COOKIE_NAME)
    if not token or '.' not in token:
        return False
    body, sig = token.rsplit('.', 1)
    if not hmac.compare_digest(sign_value(body), sig):
        return False
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)).decode())
        return int(payload.get('exp', 0)) > int(time.time())
    except Exception:
        return False

def send_login_page(handler, error=''):
    err = f'<p class="login-error">{html.escape(error)}</p>' if error else ''
    body = (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>입주자 로그인</title><link rel="stylesheet" href="styles/ocean.css?v=auth1">'
        '</head><body class="portal-login-body"><main class="portal-login"><div class="portal-login-card">'
        '<div class="login-kicker">월곶 이레하이니스</div><h1>입주자 포털 로그인</h1>'
        '<p>입주자 공용 계정으로 로그인하면 이 브라우저에서 자동 로그인됩니다.</p>'
        f'{err}<form method="post" action="login">'
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
        handler.send_header('Location', './')
        handler.send_header('Set-Cookie', f'{PORTAL_COOKIE_NAME}={cookie}; Max-Age={PORTAL_COOKIE_MAX_AGE}; Path=/update-tide/; HttpOnly; SameSite=Lax')
        handler.end_headers()
    except Exception:
        send_login_page(handler, '로그인 처리 중 오류가 발생했습니다.')

def handle_logout(handler):
    handler.send_response(303)
    handler.send_header('Location', './login')
    handler.send_header('Set-Cookie', f'{PORTAL_COOKIE_NAME}=; Max-Age=0; Path=/update-tide/; HttpOnly; SameSite=Lax')
    handler.end_headers()

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ('/login', '/login/'):
            return send_login_page(self)
        if parsed.path in ('/logout', '/logout/'):
            return handle_logout(self)
        if parsed.path == '/api/bus/arrivals':
            return handle_bus_arrivals(self)
        if parsed.path == '/api/bus/stations':
            return handle_bus_station_search(self, urllib.parse.parse_qs(parsed.query))
        if parsed.path == '/' or parsed.path.endswith('/index.html'):
            if not is_authenticated(self):
                self.send_response(303)
                self.send_header('Location', 'login')
                self.end_headers()
                return
        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ('/login', '/login/'):
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
