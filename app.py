from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re

app = FastAPI(title="Tide Time API", description="월곶포구 물때표 API")

# CORS settings - allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def extract_tide_data(html_content: str, year: int, month: int) -> dict:
    """Extract tide data from the HTML content"""
    month_data = {}
    
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        body_text = soup.get_text()
        
        # Extract tide information using regex
        # Pattern: date followed by times with ▲ or ▼
        day_pattern = r'(\d+)일[^▲▼]*?((?:\d{2}:\d{2}[▲▼]\s*)+)'
        
        matches = re.finditer(day_pattern, body_text)
        
        for match in matches:
            day = int(match.group(1))
            tides_text = match.group(2)
            
            # Extract individual tide times
            tide_pattern = r'(\d{2}:\d{2})([▲▼])'
            high_tides = []
            low_tides = []
            
            tide_matches = re.finditer(tide_pattern, tides_text)
            
            for tide_match in tide_matches:
                time = tide_match.group(1)
                tide_type = tide_match.group(2)
                
                if tide_type == '▲':
                    high_tides.append({"time": time, "height": "--", "change": "--"})
                elif tide_type == '▼':
                    low_tides.append({"time": time, "height": "--", "change": "--"})
            
            if high_tides or low_tides:
                month_data[day] = {
                    "high_tides": high_tides,
                    "low_tides": low_tides
                }
        
        print(f"Extracted {len(month_data)} days of tide data")
        return month_data
        
    except Exception as e:
        print(f"Error extracting tide data: {e}")
        return {}

@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Tide Time API is running"}

@app.get("/tide/{year}/{month}")
async def get_tide_data(year: int, month: int):
    """Get tide data for a specific month"""
    try:
        # URL for 월곶포구 (idx=162)
        url = f"https://m.badatime.com/view_calendar.jsp?idx=162-{year}-{month:02d}"
        
        # Fetch data from the website
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Extract tide data
        tide_data = extract_tide_data(response.text, year, month)
        
        return {
            "year": year,
            "month": month,
            "data": tide_data,
            "source": "badatime.com"
        }
        
    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch data: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/tide/today")
async def get_today_tide():
    """Get today's tide data"""
    now = datetime.now()
    return await get_tide_data(now.year, now.month)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)