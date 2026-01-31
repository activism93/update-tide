#!/usr/bin/env python3
"""
물때 데이터를 월별 JSON 파일로 생성하는 스크립트
badatime.com에서 데이터를 가져와 data/tide/YYYY-MM.json 형태로 저장
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

def extract_tide_data(html_content: str, year: int, month: int) -> Dict:
    """HTML에서 물때 데이터 추출"""
    month_data = {}
    
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        body_text = soup.get_text()
        
        # 물때 정보 추출 (일별로 시간과 타입)
        day_pattern = r'(\d+)일[^▲▼]*?((?:\d{2}:\d{2}[▲▼]\s*)+)'
        
        for match in re.finditer(day_pattern, body_text):
            day = int(match.group(1))
            tides_text = match.group(2)
            
            # 개별 물때 시간 추출
            tide_pattern = r'(\d{2}:\d{2})([▲▼])'
            high_tides = []
            low_tides = []
            
            for tide_match in re.finditer(tide_pattern, tides_text):
                time = tide_match.group(1)
                tide_type = tide_match.group(2)
                
                if tide_type == '▲':
                    high_tides.append({"time": time, "height": "--", "change": "--"})
                elif tide_type == '▼':
                    low_tides.append({"time": time, "height": "--", "change": "--"})
            
            if high_tides or low_tides:
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
        
        return month_data
        
    except Exception as e:
        print(f"데이터 추출 오류: {e}")
        return {}

def fetch_tide_data(year: int, month: int) -> Optional[Dict]:
    """badatime.com에서 물때 데이터 가져오기"""
    try:
        # 월곶포구 (idx=162)
        url = f"https://m.badatime.com/view_calendar.jsp?idx=162-{year}-{month:02d}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        return extract_tide_data(response.text, year, month)
        
    except requests.RequestException as e:
        print(f"HTTP 요청 오류: {e}")
        return None
    except Exception as e:
        print(f"데이터 가져오기 오류: {e}")
        return None

def save_tide_data(data: Dict, year: int, month: int) -> bool:
    """물때 데이터를 JSON 파일로 저장"""
    try:
        # 디렉토리 생성
        os.makedirs('data/tide', exist_ok=True)
        
        filename = f"data/tide/{year}-{month:02d}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"저장 완료: {filename} ({len(data)}일 데이터)")
        return True
        
    except Exception as e:
        print(f"저장 오류: {e}")
        return False

def generate_sample_data(year: int, month: int) -> Dict:
    """샘플 데이터 생성 (실제 데이터 가져오기 실패시 사용)"""
    import calendar
    
    month_data = {}
    days_in_month = calendar.monthrange(year, month)[1]
    
    for day in range(1, days_in_month + 1):
        # 시간 계산
        day_offset = day
        base_minutes = (day_offset * 50) % (12 * 60)
        
        tide1 = base_minutes
        tide2 = (base_minutes + 370) % (24 * 60)
        tide3 = (base_minutes + 740) % (24 * 60)
        tide4 = (base_minutes + 1110) % (24 * 60)
        
        times = [
            {"minutes": tide1, "type": "high"},
            {"minutes": tide2, "type": "low"},
            {"minutes": tide3, "type": "high"},
            {"minutes": tide4, "type": "low"}
        ]
        
        times.sort(key=lambda x: x["minutes"])
        
        high_tides = []
        low_tides = []
        
        for t in times:
            h = (t["minutes"] // 60) % 24
            m = t["minutes"] % 60
            time_str = f"{h:02d}:{m:02d}"
            
            tide_data = {"time": time_str, "height": "--", "change": "--"}
            
            if t["type"] == "high":
                high_tides.append(tide_data)
            else:
                low_tides.append(tide_data)
        
        # 월물 계산
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
    
    return month_data

def main():
    """메인 함수"""
    import sys
    from datetime import datetime
    
    # 현재 년월 가져오기
    now = datetime.now()
    year = now.year
    month = now.month
    
    # 명령행 인자로 년월 지정 가능
    if len(sys.argv) >= 2:
        year = int(sys.argv[1])
    if len(sys.argv) >= 3:
        month = int(sys.argv[2])
    
    print(f"물때 데이터 생성 시작: {year}-{month:02d}")
    
    # 실제 데이터 시도
    tide_data = fetch_tide_data(year, month)
    
    if tide_data and len(tide_data) > 0:
        print(f"실제 데이터 가져오기 성공: {len(tide_data)}일")
    else:
        print("실제 데이터 가져오기 실패, 샘플 데이터 생성")
        tide_data = generate_sample_data(year, month)
    
    # 데이터 저장
    if save_tide_data(tide_data, year, month):
        print("완료!")
    else:
        print("저장 실패")
        sys.exit(1)

if __name__ == "__main__":
    main()