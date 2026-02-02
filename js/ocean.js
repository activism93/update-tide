// Ocean View - 월곶 이레하이니스 JavaScript
const JSON_PATH = "./data/tide.json";
let lastOceanData = null;

function pad2(n) { return String(n).padStart(2, "0"); }

function kstNow() {
  const now = new Date();
  const fmt = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Seoul",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit"
  });
  const parts = fmt.formatToParts(now).reduce((acc, p) => {
    acc[p.type] = p.value;
    return acc;
  }, {});
  return new Date(`${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}+09:00`);
}

function calculateCurrentTideLevel(highTides, lowTides) {
    const now = kstNow();
    let currentMinutes = now.getHours() * 60 + now.getMinutes();
    
    // 모든 조수 시간을 분으로 변환
    const allTides = [];
    
    highTides.forEach(tide => {
        const [hours, minutes] = tide.time.split(':').map(Number);
        allTides.push({
            time: tide.time,
            minutes: hours * 60 + minutes,
            height: tide.height,
            type: 'high'
        });
    });
    
    lowTides.forEach(tide => {
        const [hours, minutes] = tide.time.split(':').map(Number);
        allTides.push({
            time: tide.time,
            minutes: hours * 60 + minutes,
            height: tide.height,
            type: 'low'
        });
    });
    
    // 시간순 정렬
    allTides.sort((a, b) => a.minutes - b.minutes);
    
    // 현재 시간 기준으로 다음 조수 찾기
    let nextTide = null;
    let prevTide = null;
    
    for (let i = 0; i < allTides.length; i++) {
        if (allTides[i].minutes > currentMinutes) {
            nextTide = allTides[i];
            prevTide = i > 0 ? allTides[i - 1] : allTides[allTides.length - 1];
            break;
        }
    }
    
    // 현재 시간이 마지막 조수보다 늦은 경우
    if (!nextTide) {
        nextTide = allTides[0];
        prevTide = allTides[allTides.length - 1];
    }
    
    // 현재 조수 레벨 계산 (간단한 선형 보간)
    if (prevTide && nextTide) {
        let prevMinutes = prevTide.minutes;
        let nextMinutes = nextTide.minutes;
        
        // 자정을 넘어가는 경우 처리
        if (nextMinutes < prevMinutes) {
            nextMinutes += 24 * 60;
            if (currentMinutes < prevMinutes) {
                currentMinutes += 24 * 60;
            }
        }
        
        const totalMinutes = nextMinutes - prevMinutes;
        const elapsedMinutes = currentMinutes - prevMinutes;
        const progress = elapsedMinutes / totalMinutes;
        
        // 높이 보간
        const currentHeight = prevTide.height + (nextTide.height - prevTide.height) * progress;
        
        // 퍼센트 계산 (최저/최고 기준)
        const minHeight = Math.min(...allTides.map(t => t.height));
        const maxHeight = Math.max(...allTides.map(t => t.height));
        const percentage = ((currentHeight - minHeight) / (maxHeight - minHeight)) * 100;
        
        return {
            percentage: Math.round(percentage),
            currentHeight: Math.round(currentHeight),
            status: progress > 0.5 ? '오름' : '내림',
            nextTide: nextTide,
            timeToNext: nextMinutes - currentMinutes
        };
    }
    
    return {
        percentage: 50,
        currentHeight: 0,
        status: '알 수 없음',
        nextTide: nextTide,
        timeToNext: 0
    };
}

function getSunStatus(sunrise, sunset) {
    const now = kstNow();
    const currentMinutes = now.getHours() * 60 + now.getMinutes();
    
    if (sunrise && sunset) {
        const [srHour, srMin] = sunrise.split(':').map(Number);
        const [ssHour, ssMin] = sunset.split(':').map(Number);
        
        const sunriseMinutes = srHour * 60 + srMin;
        const sunsetMinutes = ssHour * 60 + ssMin;
        
        if (currentMinutes < sunriseMinutes) {
            return { status: '일출 전', icon: '🌅', time: sunrise };
        } else if (currentMinutes < sunsetMinutes) {
            return { status: '낮', icon: '☀️', time: sunset };
        } else {
            return { status: '일몰 후', icon: '🌙', time: sunrise };
        }
    }
    
    return { status: '알 수 없음', icon: '🌅', time: '--:--' };
}

async function loadOceanData(forceReload = false) {
  const container = document.getElementById("oceanContainer");
  container.innerHTML = '<div class="loading">🌊 오션 정보를 불러오는 중...</div>';

  try {
    const url = `${JSON_PATH}?ts=${Date.now()}&v=2.0`;
    console.log("Loading ocean data from:", url);
    
    const resp = await fetch(url, { cache: "no-store" });
    if (!resp.ok) {
      throw new Error(`JSON fetch failed: HTTP ${resp.status} (${url})`);
    }

    const oceanData = await resp.json();
    console.log("Loaded ocean data:", oceanData);
    lastOceanData = oceanData;
    
    displayOceanData(oceanData);
  } catch (e) {
    console.log("오션 데이터 로딩 실패:", e);
    showFriendlyError(e);
    displaySampleOceanData();
  }
}
    
function displayOceanData(oceanData) {
  const now = kstNow();
  const weekdays = ["일", "월", "화", "수", "목", "금", "토"];
  
  const dateStr = oceanData.korean_date || `${now.getFullYear()}년 ${now.getMonth() + 1}월 ${now.getDate()}일 (${weekdays[now.getDay()]})`;
  
  // 현재 조수 상태 계산
  const tideLevel = calculateCurrentTideLevel(
      oceanData.high_tides || [], 
      oceanData.low_tides || []
  );
  
  // 해 상태 계산
  const sunStatus = getSunStatus(oceanData.sunrise, oceanData.sunset);
  
  const data = {
    date: dateStr,
    currentTime: now.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }),
    highTides: Array.isArray(oceanData.high_tides) && oceanData.high_tides.length ? oceanData.high_tides : [],
    lowTides: Array.isArray(oceanData.low_tides) && oceanData.low_tides.length ? oceanData.low_tides : [],
    sunrise: oceanData.sunrise || "--:--",
    sunset: oceanData.sunset || "--:--",
    tideLevel: tideLevel,
    sunStatus: sunStatus
  };

  displayOceanOverview(data);
}

function showFriendlyError(err) {
  const container = document.getElementById("oceanContainer");
  const msg = String(err && err.message ? err.message : err);
  container.innerHTML = `
    <div class="error-box">
      <div style="font-weight: 700; margin-bottom: 15px; font-size: 1.3em;">🌊 오션 정보 로딩 실패</div>
      <div style="margin-bottom: 15px; line-height: 1.6;">
        월곶 이레하이니스 건물의 넓은 통창으로 바다를 볼 수 있는 오션 정보를 제공합니다.<br>
        현재 기술적인 문제로 정보를 불러올 수 없습니다.
      </div>
      <div style="margin-bottom: 15px;"><span style="font-weight:600;">에러:</span> <code>${escapeHtml(msg)}</code></div>
      <div>새로고침 버튼을 눌러 다시 시도해주세요.</div>
    </div>
  `;
}

function escapeHtml(s) {
  return s.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function displaySampleOceanData() {
  const now = kstNow();
  const weekdays = ["일", "월", "화", "수", "목", "금", "토"];
  const dateStr = `${now.getFullYear()}년 ${now.getMonth() + 1}월 ${now.getDate()}일 (${weekdays[now.getDay()]})`;

  const sampleData = {
    date: dateStr,
    currentTime: now.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }),
    highTides: [
      { time: "06:30", height: 350 },
      { time: "18:45", height: 280 }
    ],
    lowTides: [
      { time: "00:15", height: 120 },
      { time: "12:20", height: 80 }
    ],
    sunrise: "06:30",
    sunset: "18:45",
    tideLevel: {
        percentage: 65,
        currentHeight: 250,
        status: '오름',
        nextTide: { time: "18:45", height: 280, type: 'high' },
        timeToNext: 120
    },
    sunStatus: { status: '낮', icon: '☀️', time: "18:45" }
  };

  displayOceanOverview(sampleData);
}

function displayOceanOverview(data) {
  const container = document.getElementById("oceanContainer");

  let oceanHTML = `
    <div class="ocean-overview">
      <div class="current-status">
        <div class="status-time">
          <div class="current-time">${data.currentTime}</div>
          <div class="current-date">${data.date}</div>
        </div>
        
        <div class="tide-level-indicator">
          <div class="tide-wave"></div>
          <div class="tide-percentage">${data.tideLevel.percentage}%</div>
          <div class="tide-level-text">현재 조수 레벨</div>
          <div style="font-size: 1em; color: #7f8c8d; margin-top: 5px;">
            ${data.tideLevel.status} · 다음 ${data.tideLevel.nextTide.time}
          </div>
        </div>
        
        <div class="sun-position">
          <div class="sun-icon">${data.sunStatus.icon}</div>
          <div class="sun-status">${data.sunStatus.status}</div>
          <div class="sun-time">${data.sunStatus.time}</div>
        </div>
      </div>
      
      <div class="tide-schedule">
  `;

  // 모든 조수 이벤트를 시간순으로 정렬
  const allTides = [];
  data.highTides.forEach((tide, index) => {
    allTides.push({ ...tide, type: 'high', label: '만조' });
  });
  data.lowTides.forEach((tide, index) => {
    allTides.push({ ...tide, type: 'low', label: '간조' });
  });
  
  allTides.sort((a, b) => {
    const [aHour, aMin] = a.time.split(':').map(Number);
    const [bHour, bMin] = b.time.split(':').map(Number);
    return (aHour * 60 + aMin) - (bHour * 60 + bMin);
  });

  allTides.forEach(tide => {
    const tideSymbol = tide.type === 'high' ? '▲' : '▼';
    const tideIconClass = tide.type === 'high' ? 'tide-icon-high' : 'tide-icon-low';

    oceanHTML += `
      <div class="tide-event ${tide.type}-tide">
        <div class="tide-icon ${tideIconClass}">${tideSymbol}</div>
        <div class="tide-type">${tide.label}</div>
        <div class="tide-time">${tide.time}</div>
        <div class="tide-height">${tide.height}cm</div>
      </div>
    `;
  });


  oceanHTML += `
      </div>
      
      <div class="ocean-conditions">
        <div class="condition-card">
          <div class="condition-icon">🌅</div>
          <div class="condition-label">일출</div>
          <div class="condition-value">${data.sunrise}</div>
        </div>
        <div class="condition-card">
          <div class="condition-icon">🌇</div>
          <div class="condition-label">일몰</div>
          <div class="condition-value">${data.sunset}</div>
        </div>
        <div class="condition-card">
          <div class="condition-icon">📍</div>
          <div class="condition-label">위치</div>
          <div class="condition-value">월곶포구</div>
        </div>
      </div>
    </div>
  `;

  container.innerHTML = oceanHTML;
}

// 초기 로드 및 주기적 업데이트
document.addEventListener('DOMContentLoaded', function() {
    loadOceanData(false);
    
    // 5분마다 자동 새로고침
    setInterval(() => {
        loadOceanData(true);
    }, 5 * 60 * 1000);
});

// 강제 새로고침 함수
function forceRefresh() {
    console.log("Force refreshing ocean data...");
    loadOceanData(true);
}