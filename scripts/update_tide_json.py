#!/usr/bin/env python3
"""
월곶포구 조수 데이터 추출 스크립트
Simple script to fetch today's tide data and update single JSON file
"""

import json
import sys
import os
import requests
from datetime import datetime
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
    
    # Extract high tides (만조) - look for times with heights after 만조 label
    # Pattern: 만조 followed by times like "04:20 (698)"
    high_tide_section = re.search(r'만조.*?(?=간조|일출|$)', text_content, re.DOTALL)
    if high_tide_section:
        high_section = high_tide_section.group(0)
        high_tide_pattern = r'(\d{1,2}:\d{2})\s*\((\d+)\)'
        high_matches = re.findall(high_tide_pattern, high_section)
        
        for time_str, height in high_matches[:2]:  # Only take first 2 high tides
            result['high_tides'].append({
                'time': time_str,
                'height': int(height)
            })
    
    # Extract low tides (간조) - look for times with heights after 간조 label  
    low_tide_section = re.search(r'간조.*?(?=일출|$)', text_content, re.DOTALL)
    if low_tide_section:
        low_section = low_tide_section.group(0)
        low_tide_pattern = r'(\d{1,2}:\d{2})\s*\((\d+)\)'
        low_matches = re.findall(low_tide_pattern, low_section)
        
        for time_str, height in low_matches[:2]:  # Only take first 2 low tides
            result['low_tides'].append({
                'time': time_str,
                'height': int(height)
            })
    
    # Extract sunrise and sunset from 일출/일몰 section
    sunrise_sunset_section = re.search(r'일출/일몰.*?$', text_content, re.DOTALL)
    if sunrise_sunset_section:
        ss_section = sunrise_sunset_section.group(0)
        # Look for patterns like "일출 06:30" and "일몰 18:45"
        sunrise_match = re.search(r'일출.*?(\d{1,2}:\d{2})', ss_section)
        sunset_match = re.search(r'일몰.*?(\d{1,2}:\d{2})', ss_section)
        
        if sunrise_match:
            result['sunrise'] = sunrise_match.group(1)
        if sunset_match:
            result['sunset'] = sunset_match.group(1)
    
    # Fallback: if section extraction didn't work, try global patterns
    if not result['high_tides']:
        # Alternative pattern: find all times with ▲ symbols (high tide)
        high_alt_pattern = r'(\d{1,2}:\d{2})\s*\(\d+\)[^▲]*▲'
        high_alt_matches = re.findall(high_alt_pattern, text_content)
        for time_str in high_alt_matches[:2]:
            # Extract height separately
            height_match = re.search(fr'{re.escape(time_str)}\s*\((\d+)\)', text_content)
            if height_match:
                result['high_tides'].append({
                    'time': time_str,
                    'height': int(height_match.group(1))
                })
    
    if not result['low_tides']:
        # Alternative pattern: find all times with ▼ symbols (low tide)
        low_alt_pattern = r'(\d{1,2}:\d{2})\s*\(\d+\)[^▼]*▼'
        low_alt_matches = re.findall(low_alt_pattern, text_content)
        for time_str in low_alt_matches[:2]:
            # Extract height separately
            height_match = re.search(fr'{re.escape(time_str)}\s*\((\d+)\)', text_content)
            if height_match:
                result['low_tides'].append({
                    'time': time_str,
                    'height': int(height_match.group(1))
                })
    
    return result

def fetch_today_tide_data() -> Dict[str, Any]:
    """
    Fetch today's tide data from badatime.com
    
    Returns:
        Dictionary with today's tide data
    """
    seoul_time = get_seoul_time()
    date_str = seoul_time.strftime('%Y-%m-%d')
    
    # 월곶포구 URL (idx=162)
    url = f"https://m.badatime.com/view_day.jsp?idx=162-{date_str}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1'
    }
    
    try:
        print(f"Fetching today's tide data for {date_str}...")
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        tide_info = extract_tide_info(response.text)
        
        result = {
            'date': date_str,
            'korean_date': seoul_time.strftime('%Y년 %m월 %d일'),
            'weekday': seoul_time.strftime('%A'),
            'location': '월곶포구',
            'source': 'badatime.com',
            'last_updated': seoul_time.isoformat(),
            **tide_info
        }
        
        print(f"  Extracted {len(result['high_tides'])} high tides, {len(result['low_tides'])} low tides")
        if result['sunrise']:
            print(f"  Sunrise: {result['sunrise']}, Sunset: {result['sunset']}")
        
        return result
        
    except Exception as e:
        print(f"Error fetching today's tide data: {e}")
        return {}

def save_tide_json(data: Dict[str, Any]):
    """Save today's tide data to single JSON file"""
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    os.makedirs(output_dir, exist_ok=True)
    
    filepath = os.path.join(output_dir, 'tide.json')
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Saved today's tide data to {filepath}")
    except Exception as e:
        print(f"Error saving tide data: {e}")
        sys.exit(1)

def main():
    """Main function to update today's tide data"""
    try:
        # Fetch today's tide data
        today_data = fetch_today_tide_data()
        
        if today_data:
            save_tide_json(today_data)
            print("Today's tide data update completed successfully!")
        else:
            print("Failed to fetch tide data")
            sys.exit(1)
        
    except Exception as e:
        print(f"Error in main execution: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()