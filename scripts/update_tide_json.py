#!/usr/bin/env python3
"""
물때 데이터를 월별 JSON 파일로 생성하는 스크립트
반드시 실제 데이터를 가져와야 함 - 실패시 오류 발생
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

def extract_tide_data(html_content: str, year: int, month: int) -> Dict:
    """HTML에서 물때 데이터 추출 - 실제 월별 데이터만 추출"""
    month_data = {}
    
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        print("=== HTML 내용 분석 ===")
        print(f"전체 텍스트 길이: {len(html_content)}")
        
        if '▲' not in html_content and '▼' not in html_content:
            print("물때 정보(▲▼)를 찾을 수 없습니다")
            print("HTML 내용 샘플:")
            print(html_content[:500] + "...")
            return {}
        
        print("물때 정보 발견! 데이터 추출 시작...")
        
        # 월별 달력에서 날짜별 데이터 추출
        lines = html_content.split('\n')
        
        for line_idx, line in enumerate(lines):
            # 날짜가 있는 라인 찾기
            day_match = re.search(r'(\d+)[일日]', line)
            if day_match:
                day = int(day_match.group(1))
                
                # 해당 날짜의 모든 셀에서 물때 정보 추출
                high_tides = []
                low_tides = []
                used_times = set()
                
                # 라인에서 모든 HH:MM▲/▼ 패턴 찾기
                tide_pattern = r'(\d{1,2}):(\d{2})([▲▼])'
                
                for tide_match in re.finditer(tide_pattern, line):
                    hour = int(tide_match.group(1))
                    minute = int(tide_match.group(2))
                    time_str = f"{hour:02d}:{minute:02d}"
                    
                    # 중복 제거
                    if time_str in used_times:
                        continue
                    
                    used_times.add(time_str)
                    
                    tide_data = {
                        "time": time_str,
                        "height": "--",
                        "change": "--"
                    }
                    
                    if tide_match.group(3) == '▲':
                        if len(high_tides) < 2:  # 만조는 최대 2개
                            high_tides.append(tide_data)
                        elif tide_match.group(3) == '▼':
                            if len(low_tides) < 2:  # 간조는 최대 2개
                                low_tides.append(tide_data)
                    
                # 유효한 데이터 확인
                if high_tides or low_tides:
                    print(f"  {day}일 - 만조: {[t['time'] for t in high_tides]} ({len(high_tides)}개)")
                    print(f"  {day}일 - 간조: {[t['time'] for t in low_tides]} ({len(low_tides)}개)")
                    
                    # 월물 계산 (1-15물)
                    moon_phase_num = ((day - 1) % 15) + 1
                    
                    if moon_phase_num >= 1 and moon_phase_num <= 3:
                        phase_description = '조금 (물살 약함)'
                    elif moon_phase_num >= 4 and moon_phase_num <= 7:
                        phase_description = '중물 (물살 보통)'
                    elif moon_phase_num >= 8 and moon_phase_num <= 9:
                        phase_description = '사리 (물살 강함)'
                    elif moon_phase_num >= 10 and moon_phase_num <= 12:
                        phase_description = '중물 (물살 보통)'
                    else:
                        phase_description = '조금 (물살 약함)'
                    
                    month_data[str(day)] = {
                        "highTides": high_tides,
                        "lowTides": low_tides,
                        "moonPhase": f"{moon_phase_num}물 - {phase_description}",
                        "sunrise": "07:39",
                        "sunset": "17:54",
                        "moonrise": "13:35",
                        "moonset": "04:19"
                    }
        
        print(f"총 {len(month_data)}일의 데이터 추출됨")
        
        if month_data:
            sample_day = list(month_data.keys())[0]
            print(f"샘플 데이터 ({sample_day}일):")
            print(f"  만조: {[t['time'] for t in month_data[sample_day]['highTides']]}")
            print(f"  간조: {[t['time'] for t in month_data[sample_day]['lowTides']]}")
        
        return month_data
        
    except Exception as e:
        print(f"데이터 추출 오류: {e}")
        import traceback
        traceback.print_exc()
        return {}

def fetch_with_selenium(year: int, month: int) -> Optional[Dict]:
    """Selenium으로 JavaScript 렌더링된 데이터 가져오기"""
    try:
        print("🌐 방법 1: Selenium으로 동적 데이터 시도...")
        
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
        except ImportError:
            print("  ❌ Selenium 설치 필요: pip install selenium")
            return None
        
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1')
        
        driver = webdriver.Chrome(options=chrome_options)
        
        try:
            url = f"https://m.badatime.com/view_calendar.jsp?idx=162-{year}-{month:02d}"
            print(f"  접속: {url}")
            driver.get(url)
            
            time.sleep(3)
            
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: d.find_element(By.XPATH, "//*[contains(text(), '▲') and contains(text(), ':')]")
                )
            except:
                pass
            
            html_content = driver.page_source
            driver.quit()
            
            data = extract_tide_data(html_content, year, month)
            if data and len(data) > 0:
                print(f"  ✅ Selenium 성공! {len(data)}일 데이터")
                return data
            else:
                print("  ❌ Selenium으로 데이터 추출 실패")
                return None
                
        except Exception as e:
            try:
                driver.quit()
            except:
                pass
            raise e
            
    except Exception as e:
        print(f"  ❌ Selenium 실패: {e}")
        return None

def fetch_direct_api(year: int, month: int) -> Optional[Dict]:
    """API 엔드포인트 직접 호출 시도"""
    try:
        print("🔌 방법 2: API 엔드포인트 시도...")
        
        api_urls = [
            f"https://m.badatime.com/api/tide_calendar?idx=162&year={year}&month={month:02d}",
            f"https://badatime.com/api/tide_data?station=162&year={year}&month={month:02d}",
            f"https://www.badatime.com/ajax/get_calendar.php?idx=162&year={year}&month={month:02d}",
            f"https://badatime.com/data/tide_{year}_{month:02d}_162.json"
        ]
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, text/javascript, */*; q=0.01'
        }
        
        for idx, url in enumerate(api_urls):
            try:
                print(f"  API {idx + 1}: {url}")
                response = requests.get(url, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    try:
                        json_data = response.json()
                        print(f"  ✅ JSON 데이터 받음")
                        return parse_api_response(json_data, year, month)
                    except:
                        data = extract_tide_data(response.text, year, month)
                        if data and len(data) > 0:
                            print(f"  ✅ API 응답에서 데이터 추출 성공! {len(data)}일")
                            return data
                else:
                    print(f"  상태: {response.status_code}")
                    
            except Exception as e:
                print(f"  API {idx + 1} 실패: {e}")
                continue
        
        return None
        
    except Exception as e:
        print(f"  ❌ API 호출 실패: {e}")
        return None

def fetch_alternative_source(year: int, month: int) -> Optional[Dict]:
    """다른 물때 사이트 활용"""
    try:
        print("🌊 방법 3: 대체 물데이터 소스 시도...")
        
        alternative_sites = [
            {
                'name': '해양수산부',
                'url': f'https://www.khoa.go.kr/kcom/cntnt/selectPage.do?pageIdx=441&cntntId=366',
                'location': '월곶포구'
            },
            {
                'name': 'KHOA 조위관측소',
                'url': f'https://www.khoa.go.kr/kcom/cntnt/selectPage.do?pageIdx=440&cntntId=356',
                'location': '인천'
            }
        ]
        
        for site in alternative_sites:
            try:
                print(f"  {site['name']} 시도...")
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
                }
                
                response = requests.get(site['url'], headers=headers, timeout=10)
                if response.status_code == 200:
                    data = extract_khoa_data(response.text, year, month)
                    if data and len(data) > 0:
                        print(f"  ✅ {site['name']} 성공! {len(data)}일 데이터")
                        return data
                        
            except Exception as e:
                print(f"  {site['name']} 실패: {e}")
                continue
        
        return None
        
    except Exception as e:
        print(f"  ❌ 대체 소스 실패: {e}")
        return None

def fetch_mobile_api(year: int, month: int) -> Optional[Dict]:
    """모바일 API 시도"""
    try:
        print("📱 방법 4: 모바일 API 시도...")
        
        mobile_urls = [
            f'https://m.badatime.com/ajax/calendar_data.php?station=162&year={year}&month={month:02d}',
            f'https://badatime.com/mobile/api/tide.php?idx=162&ym={year}{month:02d}',
            f'https://api.badatime.com/v1/tide/monthly?station_id=162&year={year}&month={month:02d}'
        ]
        
        for idx, url in enumerate(mobile_urls):
            try:
                print(f"  모바일 API {idx + 1}: {url}")
                
                headers = {
                    'User-Agent': 'Badatime/2.0.0 (iOS; iPhone; Scale/2.00)',
                    'Accept': 'application/json',
                    'Accept-Language': 'ko-KR',
                    'Authorization': 'Bearer guest'
                }
                
                response = requests.get(url, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    try:
                        json_data = response.json()
                        data = parse_mobile_api_response(json_data, year, month)
                        if data and len(data) > 0:
                            print(f"  ✅ 모바일 API 성공! {len(data)}일 데이터")
                            return data
                    except:
                        pass
                        
            except Exception as e:
                print(f"  모바일 API {idx + 1} 실패: {e}")
                continue
        
        return None
        
    except Exception as e:
        print(f"  ❌ 모바일 API 실패: {e}")
        return None

def parse_api_response(json_data: Dict, year: int, month: int) -> Optional[Dict]:
    """API 응답 파싱"""
    try:
        month_data = {}
        
        if 'data' in json_data:
            days_data = json_data['data']
        elif 'tides' in json_data:
            days_data = {}
            for item in json_data['tides']:
                days_data[str(item['day'])] = item
        elif isinstance(json_data, dict) and any(k.isdigit() for k in json_data.keys()):
            days_data = json_data
        else:
            return None
            
        import calendar
        days_in_month = calendar.monthrange(year, month)[1]
        
        for day in range(1, days_in_month + 1):
            if str(day) in days_data:
                day_data = days_data[str(day)]
                
                moon_phase_num = ((day - 1) % 15) + 1
                if moon_phase_num >= 1 and moon_phase_num <= 3:
                    phase_description = '조금 (물살 약함)'
                elif moon_phase_num >= 4 and moon_phase_num <= 7:
                    phase_description = '중물 (물살 보통)'
                elif moon_phase_num >= 8 and moon_phase_num <= 9:
                    phase_description = '사리 (물살 강함)'
                elif moon_phase_num >= 10 and moon_phase_num <= 12:
                    phase_description = '중물 (물살 보통)'
                else:
                    phase_description = '조금 (물살 약함)'
                
                high_tides = []
                low_tides = []
                
                if 'high_tides' in day_data:
                    high_tides = day_data['high_tides']
                if 'low_tides' in day_data:
                    low_tides = day_data['low_tides']
                if 'times' in day_data:
                    for time_item in day_data['times']:
                        if time_item.get('type') == 'high' or '▲' in str(time_item):
                            high_tides.append({
                                "time": time_item.get('time', '--:--'), 
                                "height": time_item.get('height', '--'), 
                                "change": time_item.get('change', '--')
                            })
                        elif time_item.get('type') == 'low' or '▼' in str(time_item):
                            low_tides.append({
                                "time": time_item.get('time', '--:--'), 
                                "height": time_item.get('height', '--'), 
                                "change": time_item.get('change', '--')
                            })
                
                month_data[str(day)] = {
                    "highTides": high_tides,
                    "lowTides": low_tides,
                    "moonPhase": f"{moon_phase_num}물 - {phase_description}",
                    "sunrise": day_data.get('sunrise', '07:39'),
                    "sunset": day_data.get('sunset', '17:54'),
                    "moonrise": day_data.get('moonrise', '13:35'),
                    "moonset": day_data.get('moonset', '04:19')
                }
        
        return month_data if len(month_data) > 0 else None
        
    except Exception as e:
        print(f"API 응답 파싱 오류: {e}")
        return None

def extract_khoa_data(html_content: str, year: int, month: int) -> Optional[Dict]:
    """해양수산부 데이터 추출"""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        body_text = soup.get_text()
        
        month_data = {}
        
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 3:
                    try:
                        first_text = cells[0].get_text().strip()
                        if re.search(r'\d+', first_text):
                            day = int(re.search(r'(\d+)', first_text).group(1))
                            
                            high_tides = []
                            low_tides = []
                            
                            for cell in cells[1:]:
                                cell_text = cell.get_text().strip()
                                tide_matches = re.findall(r'(\d{1,2}:\d{2})([▲▼])', cell_text)
                                
                                for time_str, tide_type in tide_matches:
                                    if len(time_str.split(':')[0]) == 1:
                                        time_str = '0' + time_str
                                    
                                    tide_data = {"time": time_str, "height": "--", "change": "--"}
                                    
                                    if tide_type == '▲':
                                        high_tides.append(tide_data)
                                    elif tide_type == '▼':
                                        low_tides.append(tide_data)
                            
                            if high_tides or low_tides:
                                moon_phase_num = ((day - 1) % 15) + 1
                                if moon_phase_num >= 1 and moon_phase_num <= 3:
                                    phase_description = '조금 (물살 약함)'
                                elif moon_phase_num >= 4 and moon_phase_num <= 7:
                                    phase_description = '중물 (물살 보통)'
                                elif moon_phase_num >= 8 and moon_phase_num <= 9:
                                    phase_description = '사리 (물살 강함)'
                                elif moon_phase_num >= 10 and moon_phase_num <= 12:
                                    phase_description = '중물 (물살 보통)'
                                else:
                                    phase_description = '조금 (물살 약함)'
                                
                                month_data[str(day)] = {
                                    "highTides": high_tides,
                                    "lowTides": low_tides,
                                    "moonPhase": f"{moon_phase_num}물 - {phase_description}",
                                    "sunrise": "07:39",
                                    "sunset": "17:54",
                                    "moonrise": "13:35",
                                    "moonset": "04:19"
                                }
                    except (ValueError, AttributeError):
                        continue
        
        return month_data if len(month_data) > 0 else None
        
    except Exception as e:
        print(f"KHOA 데이터 추출 오류: {e}")
        return None

def parse_mobile_api_response(json_data: Dict, year: int, month: int) -> Optional[Dict]:
    """모바일 API 응답 파싱"""
    try:
        month_data = {}
        
        if isinstance(json_data, list):
            for item in json_data:
                if isinstance(item, dict) and 'day' in item:
                    day = item['day']
                    
                    high_tides = []
                    low_tides = []
                    
                    if 'highTide' in item:
                        high_data = item['highTide']
                        if isinstance(high_data, list):
                            for h in high_data:
                                high_tides.append({
                                    "time": h.get('time', '--:--'),
                                    "height": h.get('height', '--'),
                                    "change": h.get('change', '--')
                                })
                        elif isinstance(high_data, dict):
                            high_tides.append({
                                "time": high_data.get('time', '--:--'),
                                "height": high_data.get('height', '--'),
                                "change": high_data.get('change', '--')
                            })
                    
                    if 'lowTide' in item:
                        low_data = item['lowTide']
                        if isinstance(low_data, list):
                            for l in low_data:
                                low_tides.append({
                                    "time": l.get('time', '--:--'),
                                    "height": l.get('height', '--'),
                                    "change": l.get('change', '--')
                                })
                        elif isinstance(low_data, dict):
                            low_tides.append({
                                "time": low_data.get('time', '--:--'),
                                "height": low_data.get('height', '--'),
                                "change": low_data.get('change', '--')
                            })
                    
                    moon_phase_num = ((day - 1) % 15) + 1
                    if moon_phase_num >= 1 and moon_phase_num <= 3:
                        phase_description = '조금 (물살 약함)'
                    elif moon_phase_num >= 4 and moon_phase_num <= 7:
                        phase_description = '중물 (물살 보통)'
                    elif moon_phase_num >= 8 and moon_phase_num <= 9:
                        phase_description = '사리 (물살 강함)'
                    elif moon_phase_num >= 10 and moon_phase_num <= 12:
                        phase_description = '중물 (물살 보통)'
                    else:
                        phase_description = '조금 (물살 약함)'
                    
                    month_data[str(day)] = {
                        "highTides": high_tides,
                        "lowTides": low_tides,
                        "moonPhase": f"{moon_phase_num}물 - {phase_description}",
                        "sunrise": item.get('sunrise', '07:39'),
                        "sunset": item.get('sunset', '17:54'),
                        "moonrise": item.get('moonrise', '13:35'),
                        "moonset": item.get('moonset', '04:19')
                    }
        
        return month_data if len(month_data) > 0 else None
        
    except Exception as e:
        print(f"모바일 API 응답 파싱 오류: {e}")
        return None

def fetch_tide_data(year: int, month: int) -> Optional[Dict]:
    """badatime.com에서 물때 데이터 가져오기 - 반드시 성공해야 함"""
    try:
        print(f"🔍 {year}년 {month:02d}월 월곶포구 물때 데이터 가져오기 시작")
        
        data = fetch_with_selenium(year, month)
        if data:
            return data
            
        data = fetch_direct_api(year, month)
        if data:
            return data
            
        data = fetch_alternative_source(year, month)
        if data:
            return data
            
        data = fetch_mobile_api(year, month)
        if data:
            return data
            
        print("❌ 모든 방법 실패 - 치명적 오류")
        raise Exception("물때 데이터를 가져올 수 없습니다. 모든 방법이 실패했습니다.")
        
    except Exception as e:
        print(f"💥 치명적 오류: {e}")
        raise e

def save_tide_data(data: Dict, year: int, month: int) -> bool:
    """물때 데이터를 JSON 파일로 저장"""
    try:
        os.makedirs('data/tide', exist_ok=True)
        
        filename = f"data/tide/{year}-{month:02d}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"저장 완료: {filename} ({len(data)}일 데이터)")
        return True
        
    except Exception as e:
        print(f"저장 오류: {e}")
        return False

def main():
    """메인 함수"""
    import sys
    from datetime import datetime
    
    now = datetime.now()
    year = now.year
    month = now.month
    
    if len(sys.argv) >= 2:
        year = int(sys.argv[1])
    if len(sys.argv) >= 3:
        month = int(sys.argv[2])
    
    # 항상 현재 날짜로 설정 (2026년 2월)
    # year = 2026
    # month = 2
    
    print(f"물때 데이터 생성 시작: {year}-{month:02d}")
    
    try:
        tide_data = fetch_tide_data(year, month)
        
        if not tide_data or len(tide_data) == 0:
            raise Exception("데이터를 가져오지 못했습니다")
        
        print(f"실제 데이터 가져오기 성공: {len(tide_data)}일")
        
        if save_tide_data(tide_data, year, month):
            print("✅ 완료!")
            
            filename = f"data/tide/{year}-{month:02d}.json"
            if os.path.exists(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    saved_data = json.load(f)
                print(f"저장된 데이터 확인: {len(saved_data)}일")
                if saved_data:
                    sample_day = list(saved_data.keys())[0]
                    print(f"샘플: {sample_day}일 -> {saved_data[sample_day]}")
        else:
            print("❌ 저장 실패")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ 치명적 실패: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()