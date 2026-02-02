#!/usr/bin/env python3
"""
월곶포구 조수 데이터 추출 스크립트
Simple script to fetch today's tide data and update single JSON file
"""

import json
import sys
import os
import requests
from datetime import datetime, timedelta, date
import pytz
from bs4 import BeautifulSoup
import re
from typing import Dict, List, Any

def get_seoul_time() -> datetime:
    """Get current Seoul time"""
    seoul_tz = pytz.timezone('Asia/Seoul')
    return datetime.now(seoul_tz)

def extract_tide_info(html_content: str) -> Dict[str, Any]:
    """Extract tide information from the HTML content"""
    soup = BeautifulSoup(html_content, 'html.parser')
    text_content = soup.get_text()
    
    # Initialize result
    result = {
        'high_tides': [],
        'low_tides': [],
        'sunrise': '',
        'sunset': ''
    }
    
    # Method 1: Extract using table structure patterns
    # Pattern for 만조 (high tide) section
    # Heights can be negative on some days (e.g. -22)
    high_pattern = r'만조.*?((?:\d{1,2}:\d{2}\s*\(\s*[+-]?\d+\s*\).*?)+)'
    high_match = re.search(high_pattern, text_content, re.DOTALL)
    if high_match:
        high_section = high_match.group(1)
        high_time_pattern = r'(\d{1,2}:\d{2})\s*\(\s*([+-]?\d+)\s*\)'
        high_matches = re.findall(high_time_pattern, high_section)
        
        for time_str, height_str in high_matches[:2]:
            try:
                height = int(height_str)
                result['high_tides'].append({
                    'time': time_str.strip(),
                    'height': height
                })
            except ValueError:
                continue
    
    # Pattern for 간조 (low tide) section
    low_pattern = r'간조.*?((?:\d{1,2}:\d{2}\s*\(\s*[+-]?\d+\s*\).*?)+)'
    low_match = re.search(low_pattern, text_content, re.DOTALL)
    if low_match:
        low_section = low_match.group(1)
        low_time_pattern = r'(\d{1,2}:\d{2})\s*\(\s*([+-]?\d+)\s*\)'
        low_matches = re.findall(low_time_pattern, low_section)
        
        for time_str, height_str in low_matches[:2]:
            try:
                height = int(height_str)
                result['low_tides'].append({
                    'time': time_str.strip(),
                    'height': height
                })
            except ValueError:
                continue
    
    # Extract sunrise/sunset - specific pattern for "일출/일몰	07:37/17:57"
    sunrise_sunset_pattern = r'일출/일몰\s*(\d{1,2}:\d{2})/(\d{1,2}:\d{2})'
    sunrise_sunset_match = re.search(sunrise_sunset_pattern, text_content)
    if sunrise_sunset_match:
        result['sunrise'] = sunrise_sunset_match.group(1)
        result['sunset'] = sunrise_sunset_match.group(2)
    
    # Method 2: Fallback using global patterns if specific sections didn't work
    if len(result['high_tides']) < 2:
        # Alternative: find all patterns with ▲ symbols
        global_high_pattern = r'(\d{1,2}:\d{2})\s*\(\s*([+-]?\d+)\s*\)[^▲]*▲'
        high_matches = re.findall(global_high_pattern, text_content)
        
        for time_str, height_str in high_matches[:2]:
            try:
                height = int(height_str)
                # Avoid duplicates
                if not any(t['time'] == time_str for t in result['high_tides']):
                    result['high_tides'].append({
                        'time': time_str.strip(),
                        'height': height
                    })
            except ValueError:
                continue
    
    if len(result['low_tides']) < 2:
        # Alternative: find all patterns with ▼ symbols  
        global_low_pattern = r'(\d{1,2}:\d{2})\s*\(\s*([+-]?\d+)\s*\)[^▼]*▼'
        low_matches = re.findall(global_low_pattern, text_content)
        
        for time_str, height_str in low_matches[:2]:
            try:
                height = int(height_str)
                # Avoid duplicates
                if not any(t['time'] == time_str for t in result['low_tides']):
                    result['low_tides'].append({
                        'time': time_str.strip(),
                        'height': height
                    })
            except ValueError:
                continue
    
    # Remove duplicates between high and low tides
    high_times = {t['time'] for t in result['high_tides']}
    result['low_tides'] = [t for t in result['low_tides'] if t['time'] not in high_times]
    
    return result

def fetch_tide_data_for_date(target_date: date, *, seoul_time: datetime) -> Dict[str, Any]:
    """Fetch tide data for a specific date (KST 기준)"""
    date_str = target_date.strftime('%Y-%m-%d')
    cdate = f"{target_date.year}-{target_date.month}-{target_date.day}"  # badatime uses non-zero-padded links

    # 월곶포구 URL (idx=162) - cdate 파라미터로 날짜 지정
    url = f"https://m.badatime.com/view_day.jsp?idx=162&cdate={cdate}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1'
    }

    try:
        print(f"Fetching tide data for {date_str} (Seoul Time: {seoul_time.strftime('%Y-%m-%d %H:%M:%S %Z')})...")
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        tide_info = extract_tide_info(response.text)

        # weekday/korean_date는 target_date 기준으로 생성
        seoul_tz = pytz.timezone('Asia/Seoul')
        target_dt = seoul_tz.localize(datetime(target_date.year, target_date.month, target_date.day))

        result = {
            'date': date_str,
            'korean_date': f"{target_date.year}년 {target_date.month:02d}월 {target_date.day:02d}일",
            'weekday': target_dt.strftime('%A'),
            'location': '월곶포구',
            'source': 'badatime.com',
            'last_updated': seoul_time.isoformat(),
            **tide_info
        }

        print(f"  ✅ Extracted {len(result['high_tides'])} high tides, {len(result['low_tides'])} low tides")
        if result['sunrise']:
            print(f"  🌅 Sunrise: {result['sunrise']}, 🌇 Sunset: {result['sunset']}")

        return result

    except Exception as e:
        print(f"❌ Error fetching tide data for {date_str}: {e}")
        return {}

def save_tide_json(data: Dict[str, Any], filename: str):
    """Save tide data to JSON file under data/"""
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    os.makedirs(output_dir, exist_ok=True)

    filepath = os.path.join(output_dir, filename)
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Saved today's tide data to {filepath}")
    except Exception as e:
        print(f"Error saving tide data: {e}")
        sys.exit(1)

def main():
    """Main function to update tide data files"""
    try:
        seoul_time = get_seoul_time()
        today = seoul_time.date()
        tomorrow = today + timedelta(days=1)

        today_data = fetch_tide_data_for_date(today, seoul_time=seoul_time)
        tomorrow_data = fetch_tide_data_for_date(tomorrow, seoul_time=seoul_time)

        if not today_data or not tomorrow_data:
            print("Failed to fetch tide data for today/tomorrow")
            sys.exit(1)

        # New format: split into two files for better tide-level calculation across midnight
        save_tide_json(today_data, 'tide_today.json')
        save_tide_json(tomorrow_data, 'tide_tomorrow.json')

        # Backward-compatible alias
        save_tide_json(today_data, 'tide.json')

        print("Tide data update completed successfully!")
        
    except Exception as e:
        print(f"Error in main execution: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
