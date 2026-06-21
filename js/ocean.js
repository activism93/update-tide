// Ocean View - 월곶 이레하이니스 JavaScript
// Two-day JSON files are used to compute tide level across midnight.
const TODAY_JSON_PATH = "./data/tide_today.json";
const TOMORROW_JSON_PATH = "./data/tide_tomorrow.json";
// Backward-compatible fallback
const FALLBACK_JSON_PATH = "./data/tide.json";

let lastOceanData = null;
let isFetching = false;
let minuteTickIntervalId = null;
let minuteTickTimeoutId = null;
let lastKstDateKey = null;

const kstTimeFormatter = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    hour: '2-digit',
    minute: '2-digit'
});

const kstDateKeyFormatter = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
});

function pad2(n) { return String(n).padStart(2, "0"); }

function getKstParts(date = new Date()) {
  const fmt = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Seoul",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: false
  });
  return fmt.formatToParts(date).reduce((acc, p) => {
    if (p.type !== 'literal') acc[p.type] = p.value;
    return acc;
  }, {});
}

function kstNow() {
  const now = new Date();
  const parts = getKstParts(now);
  return new Date(`${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}+09:00`);
}

function currentKstAbsMinutes() {
    const parts = getKstParts();
    return Number(parts.hour) * 60 + Number(parts.minute);
}

function formatDuration(minutes) {
    const safeMinutes = Math.max(0, Math.round(Number(minutes) || 0));
    const h = Math.floor(safeMinutes / 60);
    const m = safeMinutes % 60;
    if (h <= 0) return `${m}분 후`;
    if (m === 0) return `${h}시간 후`;
    return `${h}시간 ${m}분 후`;
}

function getTideTypeLabel(type) {
    if (type === 'high') return '만조';
    if (type === 'low') return '간조';
    return '조수';
}

function getFlowLabel(status) {
    if (status === '오름') return '물이 차오르는 중';
    if (status === '내림') return '물이 빠지는 중';
    return status || '상태 확인 중';
}

function timeToMinutes(timeStr) {
    if (!timeStr || typeof timeStr !== 'string') return null;
    const parts = timeStr.split(':');
    if (parts.length !== 2) return null;
    const h = Number(parts[0]);
    const m = Number(parts[1]);
    if (!Number.isFinite(h) || !Number.isFinite(m)) return null;
    if (h < 0 || h > 23 || m < 0 || m > 59) return null;
    return h * 60 + m;
}

function buildTideEvents(highTides, lowTides, dayOffset) {
    const events = [];

    (highTides || []).forEach(tide => {
        const minutes = timeToMinutes(tide.time);
        const height = Number(tide.height);
        if (minutes == null || !Number.isFinite(height)) return;
        events.push({
            time: tide.time,
            minutes,
            absMinutes: dayOffset * 1440 + minutes,
            height,
            type: 'high',
            dayOffset
        });
    });

    (lowTides || []).forEach(tide => {
        const minutes = timeToMinutes(tide.time);
        const height = Number(tide.height);
        if (minutes == null || !Number.isFinite(height)) return;
        events.push({
            time: tide.time,
            minutes,
            absMinutes: dayOffset * 1440 + minutes,
            height,
            type: 'low',
            dayOffset
        });
    });

    return events;
}

function calculateCurrentTideLevel(tideEvents) {
    const currentAbsMinutes = currentKstAbsMinutes();

    const events = (tideEvents || [])
        .filter(e => e && Number.isFinite(e.absMinutes) && Number.isFinite(e.height))
        .slice()
        .sort((a, b) => a.absMinutes - b.absMinutes);

    if (events.length < 2) {
        return {
            percentage: 50,
            currentHeight: 0,
            status: '알 수 없음',
            nextTide: { time: '--:--', displayTime: '--:--', type: 'unknown' },
            timeToNext: 0
        };
    }

    // Find next tide strictly after now
    let next = events.find(e => e.absMinutes > currentAbsMinutes);
    if (!next) {
        // If we don't have tomorrow data, fall back to first event and treat it as next day
        const first = events[0];
        next = { ...first, absMinutes: first.absMinutes + 1440, dayOffset: (first.dayOffset || 0) + 1 };
    }

    // Find previous tide at/before now
    let prev = null;
    for (let i = events.length - 1; i >= 0; i--) {
        if (events[i].absMinutes <= currentAbsMinutes) {
            prev = events[i];
            break;
        }
    }

    if (!prev) {
        // Before the first tide of today: approximate prev as last tide of today but shifted to previous day.
        const todayEvents = events.filter(e => e.dayOffset === 0);
        if (todayEvents.length > 0) {
            const lastToday = todayEvents[todayEvents.length - 1];
            prev = { ...lastToday, absMinutes: lastToday.absMinutes - 1440, dayOffset: -1 };
        } else {
            prev = events[0];
        }
    }

    let prevAbs = prev.absMinutes;
    let nextAbs = next.absMinutes;
    if (nextAbs <= prevAbs) {
        nextAbs += 1440;
    }

    const total = Math.max(1, nextAbs - prevAbs);
    const elapsed = Math.min(total, Math.max(0, currentAbsMinutes - prevAbs));
    const progress = elapsed / total;

    const currentHeight = prev.height + (next.height - prev.height) * progress;

    // Percent: 0 = low, 100 = high within the current segment.
    let percentage = 50;
    let status = next.height >= prev.height ? '오름' : '내림';

    if (prev.type === 'low' && next.type === 'high') {
        percentage = progress * 100;
        status = '오름';
    } else if (prev.type === 'high' && next.type === 'low') {
        percentage = (1 - progress) * 100;
        status = '내림';
    } else {
        const minH = Math.min(prev.height, next.height);
        const maxH = Math.max(prev.height, next.height);
        percentage = maxH > minH ? ((currentHeight - minH) / (maxH - minH)) * 100 : 50;
    }

    const isTomorrow = (next.dayOffset || 0) >= 1;
    const nextDisplay = `${isTomorrow ? '내일 ' : ''}${next.time}`;

    return {
        percentage: Math.round(Math.max(0, Math.min(100, percentage))),
        currentHeight: Math.round(currentHeight),
        status,
        nextTide: {
            time: next.time,
            displayTime: nextDisplay,
            height: next.height,
            type: next.type,
            dayOffset: next.dayOffset
        },
        timeToNext: Math.max(0, Math.round(nextAbs - currentAbsMinutes))
    };
}

function getSunStatus(sunrise, sunset) {
    const currentMinutes = currentKstAbsMinutes();
    
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
    isFetching = true;
    const ts = Date.now();
    const todayUrl = `${TODAY_JSON_PATH}?ts=${ts}`;
    const tomorrowUrl = `${TOMORROW_JSON_PATH}?ts=${ts}`;

    console.log("Loading ocean data from:", todayUrl, tomorrowUrl);

    const [todayResp, tomorrowResp] = await Promise.all([
        fetch(todayUrl, { cache: "no-store" }),
        fetch(tomorrowUrl, { cache: "no-store" })
    ]);

    if (!todayResp.ok) {
        throw new Error(`JSON fetch failed: HTTP ${todayResp.status} (${todayUrl})`);
    }

    const todayData = await todayResp.json();
    const tomorrowData = tomorrowResp.ok ? await tomorrowResp.json() : null;

    console.log("Loaded today data:", todayData);
    if (tomorrowData) console.log("Loaded tomorrow data:", tomorrowData);

    lastOceanData = { today: todayData, tomorrow: tomorrowData };

    displayOceanData(todayData, tomorrowData);
  } catch (e) {
    console.log("오션 데이터 로딩 실패:", e);
    // Fallback: legacy single file
    try {
        isFetching = true;
        const url = `${FALLBACK_JSON_PATH}?ts=${Date.now()}`;
        const resp = await fetch(url, { cache: "no-store" });
        if (!resp.ok) throw new Error(`JSON fetch failed: HTTP ${resp.status} (${url})`);
        const legacyData = await resp.json();
        lastOceanData = { today: legacyData, tomorrow: null };
        displayOceanData(legacyData, null);
    } catch (e2) {
        showFriendlyError(e);
        displaySampleOceanData();
    } finally {
        isFetching = false;
    }
  } finally {
    isFetching = false;
  }
}
    
function displayOceanData(todayData, tomorrowData) {
  const kstParts = getKstParts();
  
  const dateStr = (todayData && todayData.korean_date) || `${kstParts.year}년 ${Number(kstParts.month)}월 ${Number(kstParts.day)}일`;
  
  const todayHigh = (todayData && todayData.high_tides) || [];
  const todayLow = (todayData && todayData.low_tides) || [];
  const tomorrowHigh = (tomorrowData && tomorrowData.high_tides) || [];
  const tomorrowLow = (tomorrowData && tomorrowData.low_tides) || [];

  // 현재 조수 상태 계산 (오늘 + 내일 데이터 기반)
  const tideEvents = [
      ...buildTideEvents(todayHigh, todayLow, 0),
      ...buildTideEvents(tomorrowHigh, tomorrowLow, 1)
  ];
  const tideLevel = calculateCurrentTideLevel(tideEvents);
  
  // 해 상태 계산
  const sunStatus = getSunStatus(todayData && todayData.sunrise, todayData && todayData.sunset);
  
  const data = {
    date: dateStr,
    currentTime: kstTimeFormatter.format(new Date()),
    highTides: Array.isArray(todayHigh) && todayHigh.length ? todayHigh : [],
    lowTides: Array.isArray(todayLow) && todayLow.length ? todayLow : [],
    sunrise: (todayData && todayData.sunrise) || "--:--",
    sunset: (todayData && todayData.sunset) || "--:--",
    location: (todayData && todayData.location) || "월곶포구",
    source: (todayData && todayData.source) || "",
    lastUpdated: todayData && todayData.last_updated,
    tideLevel: tideLevel,
    sunStatus: sunStatus
  };

  displayOceanOverview(data);
}

function computeTideLevelFromCache() {
    if (!lastOceanData || !lastOceanData.today) return null;

    const todayData = lastOceanData.today;
    const tomorrowData = lastOceanData.tomorrow;

    const todayHigh = (todayData && todayData.high_tides) || [];
    const todayLow = (todayData && todayData.low_tides) || [];
    const tomorrowHigh = (tomorrowData && tomorrowData.high_tides) || [];
    const tomorrowLow = (tomorrowData && tomorrowData.low_tides) || [];

    const tideEvents = [
        ...buildTideEvents(todayHigh, todayLow, 0),
        ...buildTideEvents(tomorrowHigh, tomorrowLow, 1)
    ];

    return calculateCurrentTideLevel(tideEvents);
}

function updateMinuteIndicators() {
    // Update date rollover first
    const dateKey = kstDateKeyFormatter.format(new Date());
    if (lastKstDateKey && dateKey !== lastKstDateKey) {
        lastKstDateKey = dateKey;
        // Immediately fetch fresh files on midnight rollover
        loadOceanData(true);
        return;
    }

    // Avoid fighting with the loading state
    if (isFetching) return;

    const timeEl = document.getElementById('oceanCurrentTime');
    if (timeEl) {
        timeEl.textContent = kstTimeFormatter.format(new Date());
    }

    const tideLevel = computeTideLevelFromCache();
    if (!tideLevel) return;

    const pctEl = document.getElementById('oceanTidePercentage');
    if (pctEl) {
        pctEl.textContent = `${tideLevel.percentage}%`;
    }

    const heightEl = document.getElementById('oceanCurrentHeight');
    if (heightEl) {
        heightEl.textContent = `${tideLevel.currentHeight}cm`;
    }

    const waveEl = document.getElementById('oceanTideWave');
    if (waveEl) {
        waveEl.style.setProperty('--tide-fill', `${tideLevel.percentage}%`);
    }

    const nextEl = document.getElementById('oceanTideNextLine');
    if (nextEl) {
        nextEl.textContent = `${getFlowLabel(tideLevel.status)} · 다음 ${getTideTypeLabel(tideLevel.nextTide.type)} ${tideLevel.nextTide.displayTime || tideLevel.nextTide.time || '--:--'} · ${formatDuration(tideLevel.timeToNext)}`;
    }

    document.querySelectorAll('.tide-event').forEach(card => {
        const isNext = card.dataset.tideTime === tideLevel.nextTide.time && card.dataset.tideType === tideLevel.nextTide.type;
        card.classList.toggle('next-tide', isNext);
    });

    // Sun status changes minute-by-minute around sunrise/sunset
    const todayData = lastOceanData.today;
    const sun = getSunStatus(todayData && todayData.sunrise, todayData && todayData.sunset);

    const sunIconEl = document.getElementById('oceanSunIcon');
    if (sunIconEl) sunIconEl.textContent = sun.icon;
    const sunStatusEl = document.getElementById('oceanSunStatus');
    if (sunStatusEl) sunStatusEl.textContent = sun.status;
    const sunTimeEl = document.getElementById('oceanSunTime');
    if (sunTimeEl) sunTimeEl.textContent = sun.time;
}

function startMinuteTicker() {
    if (minuteTickTimeoutId) {
        clearTimeout(minuteTickTimeoutId);
        minuteTickTimeoutId = null;
    }
    if (minuteTickIntervalId) {
        clearInterval(minuteTickIntervalId);
        minuteTickIntervalId = null;
    }

    const now = new Date();
    const msUntilNextMinute = (60 - now.getSeconds()) * 1000 - now.getMilliseconds() + 25;
    minuteTickTimeoutId = setTimeout(() => {
        updateMinuteIndicators();
        minuteTickIntervalId = setInterval(updateMinuteIndicators, 60 * 1000);
    }, Math.max(0, msUntilNextMinute));
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
  const kstParts = getKstParts();
  const dateStr = `${kstParts.year}년 ${Number(kstParts.month)}월 ${Number(kstParts.day)}일`;

  const sampleData = {
    date: dateStr,
    currentTime: kstTimeFormatter.format(new Date()),
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
    location: "월곶포구",
    source: "샘플 데이터",
    lastUpdated: null,
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
  const lastUpdatedText = data.lastUpdated ? formatLastUpdated(data.lastUpdated) : '업데이트 시간 확인 중';
  const nextLabel = getTideTypeLabel(data.tideLevel.nextTide.type);
  const flowLabel = getFlowLabel(data.tideLevel.status);

  let oceanHTML = `
    <div class="ocean-overview">
      <div class="current-status">
        <div class="status-time">
          <div class="current-time" id="oceanCurrentTime">${data.currentTime}</div>
          <div class="current-date" id="oceanCurrentDate">${data.date}</div>
          <div class="updated-at">${lastUpdatedText}</div>
        </div>
        
        <div class="tide-level-indicator">
          <div class="tide-kicker">현재 예상 수위</div>
          <div class="current-height" id="oceanCurrentHeight">${data.tideLevel.currentHeight}cm</div>
          <div class="tide-wave" id="oceanTideWave" style="--tide-fill: ${data.tideLevel.percentage}%;">
            <div class="tide-water"></div>
          </div>
          <div class="tide-percentage" id="oceanTidePercentage">${data.tideLevel.percentage}%</div>
          <div class="tide-level-text">저조~만조 기준 레벨</div>
          <div class="tide-next-line" id="oceanTideNextLine">
            ${flowLabel} · 다음 ${nextLabel} ${data.tideLevel.nextTide.displayTime || data.tideLevel.nextTide.time || '--:--'} · ${formatDuration(data.tideLevel.timeToNext)}
          </div>
        </div>
        
        <div class="sun-position">
          <div class="sun-icon" id="oceanSunIcon">${data.sunStatus.icon}</div>
          <div class="sun-status" id="oceanSunStatus">${data.sunStatus.status}</div>
          <div class="sun-time" id="oceanSunTime">${data.sunStatus.time}</div>
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
    const isNextTide = tide.time === data.tideLevel.nextTide.time && tide.type === data.tideLevel.nextTide.type;

    oceanHTML += `
      <div class="tide-event ${tide.type}-tide ${isNextTide ? 'next-tide' : ''}" data-tide-time="${tide.time}" data-tide-type="${tide.type}">
        ${isNextTide ? '<div class="next-badge">다음</div>' : ''}
        <div class="tide-head">
          <span class="tide-icon ${tideIconClass}">${tideSymbol}</span>
          <span class="tide-type">${tide.label}</span>
        </div>
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
          <div class="condition-value">${data.location || '월곶포구'}</div>
        </div>
      </div>
      <div class="data-source">출처 ${data.source || '조수 데이터'} · 자동 5분 갱신</div>
    </div>
  `;

  container.innerHTML = oceanHTML;
}

function formatLastUpdated(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '최근 업데이트 확인 중';
    const dateText = new Intl.DateTimeFormat('ko-KR', {
        timeZone: 'Asia/Seoul',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    }).format(date);
    return `최근 업데이트 ${dateText}`;
}

// 초기 로드 및 주기적 업데이트
document.addEventListener('DOMContentLoaded', function() {
    lastKstDateKey = kstDateKeyFormatter.format(new Date());
    loadOceanData(false);
    startMinuteTicker();
    
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
