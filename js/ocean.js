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

function renderOceanIcon(type) {
  const icons = {
    wave: '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M6 24c5.2 0 5.2-4 10.4-4s5.2 4 10.4 4 5.2-4 10.4-4"/><path d="M3.5 29.5c5.8 0 5.8-4.2 11.6-4.2s5.8 4.2 11.6 4.2 5.8-4.2 11.6-4.2"/><path d="M8 15.5c4.4-5.8 12.9-7.8 19.9-3.3 2.3 1.5 4.1 3.5 5.2 5.8"/></svg>',
    view: '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M5 25c4.5-6.2 9.5-9.3 15-9.3S30.5 18.8 35 25c-4.5 6.2-9.5 9.3-15 9.3S9.5 31.2 5 25Z"/><circle cx="20" cy="25" r="4.5"/><path d="M9 12h22"/><path d="M13 7h14"/></svg>',
    flats: '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M6 26h28"/><path d="M9 20h7l3-5 4 9 3-4h5"/><path d="M7 31c4 1.7 8 1.7 12 0s8-1.7 12 0"/><circle cx="29" cy="11" r="3"/></svg>',
    low: '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M7 27h26"/><path d="M10 22c2.5-2 5-3 7.5-3s5 1 7.5 3 5 3 7.5 3"/><path d="M12 14h16"/><path d="M16 10h8"/></svg>',
    rising: '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M8 28h24"/><path d="M10 23c4 0 4-3 8-3s4 3 8 3 4-3 8-3"/><path d="M14 14h12"/><path d="M25 8l6 6-6 6"/><path d="M14 14h17"/></svg>',
    falling: '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M8 28h24"/><path d="M10 23c4 0 4-3 8-3s4 3 8 3 4-3 8-3"/><path d="M14 14h17"/><path d="M25 20l6-6-6-6"/></svg>',
    steady: '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M8 28h24"/><path d="M10 22c4 0 4-3 8-3s4 3 8 3 4-3 8-3"/><path d="M12 12h16"/><path d="M16 8l-4 4 4 4"/><path d="M24 8l4 4-4 4"/></svg>',
    sunset: '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M7 28h26"/><path d="M11 23a9 9 0 0 1 18 0"/><path d="M20 6v6"/><path d="M9 12l4 4"/><path d="M31 12l-4 4"/><path d="M13 33h14"/></svg>',
    sunrise: '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M7 28h26"/><path d="M11 23a9 9 0 0 1 18 0"/><path d="M20 13V7"/><path d="M16 10l4-4 4 4"/><path d="M9 15l4 3"/><path d="M31 15l-4 3"/></svg>',
    moon: '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M26.5 29.5c-8 0-14.5-6.5-14.5-14.5 0-3.1 1-6 2.7-8.3C8.8 9 5 14.6 5 21c0 8.3 6.7 15 15 15 6.4 0 12-3.8 14.3-9.7-2.3 2-5 3.2-7.8 3.2Z"/><path d="M28 8l1.2 2.8L32 12l-2.8 1.2L28 16l-1.2-2.8L24 12l2.8-1.2L28 8Z"/></svg>',
    location: '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M20 35s11-9.3 11-20A11 11 0 0 0 9 15c0 10.7 11 20 11 20Z"/><circle cx="20" cy="15" r="3.8"/><path d="M14 35h12"/></svg>'
  };
  return icons[type] || icons.view;
}

function getViewMood(tideLevel) {
    const pct = Number(tideLevel && tideLevel.percentage) || 0;
    if (pct >= 82) return { iconType: 'wave', title: '오션감 극대화', text: '수위가 높은 시간대라 창밖 수면감이 가장 풍부하게 느껴집니다.' };
    if (pct >= 55) return { iconType: 'view', title: '조망 균형 좋음', text: '수면이 충분히 차올라 안정적인 오션뷰를 보기 좋은 구간입니다.' };
    if (pct >= 28) return { iconType: 'flats', title: '갯벌·수로 변화', text: '물이 오가며 포구와 갯벌의 질감 변화가 잘 보이는 시간대입니다.' };
    return { iconType: 'low', title: '간조 풍경', text: '수위가 낮아 갯벌과 포구 라인이 선명하게 드러나는 구간입니다.' };
}

function getFlowInsight(tideLevel) {
    const nextType = getTideTypeLabel(tideLevel.nextTide && tideLevel.nextTide.type);
    const flow = getFlowLabel(tideLevel.status);
    return {
        iconType: tideLevel.status === '오름' ? 'rising' : tideLevel.status === '내림' ? 'falling' : 'steady',
        title: flow,
        text: `다음 ${nextType}까지 ${formatDuration(tideLevel.timeToNext)} 남았습니다.`
    };
}

function getGoldenHourInsight(sunStatus, sunset) {
    if (sunStatus && sunStatus.status === '낮') {
        return { iconType: 'sunset', title: '오늘의 석양 체크', text: `일몰은 ${sunset || '--:--'}입니다. 해질녘에는 수면 반사가 살아납니다.` };
    }
    if (sunStatus && sunStatus.status === '일출 전') {
        return { iconType: 'sunrise', title: '아침 조망 준비', text: `${sunStatus.time || '--:--'} 일출 전후로 포구 색감이 가장 부드럽습니다.` };
    }
    return { iconType: 'moon', title: '야간 포구 무드', text: '일몰 후에는 조명과 수면 반사가 차분한 야경을 만듭니다.' };
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

function easeTideProgress(progress) {
    // Tide level changes are closer to a smooth harmonic curve than a straight line.
    // 0 -> 0, 0.5 -> 0.5, 1 -> 1 with slower movement near high/low slack water.
    const p = Math.min(1, Math.max(0, Number(progress) || 0));
    return (1 - Math.cos(Math.PI * p)) / 2;
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
    const easedProgress = easeTideProgress(progress);

    const currentHeight = prev.height + (next.height - prev.height) * easedProgress;

    // Percent: 0 = low, 100 = high within the current segment.
    let percentage = 50;
    let status = next.height >= prev.height ? '오름' : '내림';

    if (prev.type === 'low' && next.type === 'high') {
        percentage = easedProgress * 100;
        status = '오름';
    } else if (prev.type === 'high' && next.type === 'low') {
        percentage = (1 - easedProgress) * 100;
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
            return { status: '일출 전', iconType: 'sunrise', time: sunrise, timeLabel: `일출 ${sunrise}` };
        } else if (currentMinutes < sunsetMinutes) {
            return { status: '일몰 전', iconType: 'sunset', time: sunset, timeLabel: `일몰 ${sunset}` };
        } else {
            return { status: '일몰 후', iconType: 'moon', time: sunrise, timeLabel: `내일 일출 ${sunrise}` };
        }
    }
    
    return { status: '알 수 없음', iconType: 'sunrise', time: '--:--' };
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
    sunStatus: sunStatus,
    insights: [
      getViewMood(tideLevel),
      getFlowInsight(tideLevel),
      getGoldenHourInsight(sunStatus, (todayData && todayData.sunset) || '--:--')
    ]
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
    sunStatus: { status: '낮', iconType: 'sunset', time: "18:45" },
    insights: [
      { iconType: 'view', title: '조망 균형 좋음', text: '수면이 충분히 차올라 안정적인 오션뷰를 보기 좋은 구간입니다.' },
      { icon: '↗️', title: '물이 차오르는 중', text: '다음 만조까지 2시간 후 남았습니다.' },
      { iconType: 'sunset', title: '오늘의 석양 체크', text: '일몰 전후로 수면 반사가 살아납니다.' }
    ]
  };

  displayOceanOverview(sampleData);
}

function displayOceanOverview(data) {
  const container = document.getElementById("oceanContainer");
  const lastUpdatedText = data.lastUpdated ? formatLastUpdated(data.lastUpdated) : '업데이트 시간 확인 중';
  const nextLabel = getTideTypeLabel(data.tideLevel.nextTide.type);
  const flowLabel = getFlowLabel(data.tideLevel.status);

  const insightCards = (data.insights || []).map(item => `
    <div class="insight-card">
      <div class="insight-icon">${renderOceanIcon(item.iconType)}</div>
      <div>
        <div class="insight-title">${item.title}</div>
        <div class="insight-text">${item.text}</div>
      </div>
    </div>
  `).join('');

  let oceanHTML = `
    <div id="seaSection" class="ocean-overview">
      <div class="overview-label">오늘의 바다</div>
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
        <div class="tide-head">
          <span class="tide-icon ${tideIconClass}">${tideSymbol}</span>
          <span class="tide-type">${tide.label}${isNextTide ? '<span class="next-badge">다음</span>' : ''}</span>
        </div>
        <div class="tide-time">${tide.time}</div>
        <div class="tide-height">${tide.height}cm</div>
      </div>
    `;
  });


  oceanHTML += `
      </div>

      <div class="insight-grid">
        ${insightCards}
      </div>
      
      <div class="ocean-conditions">
        <div class="condition-card">
          <div class="condition-icon">${renderOceanIcon('sunrise')}</div>
          <div class="condition-label">일출</div>
          <div class="condition-value">${data.sunrise}</div>
        </div>
        <div class="condition-card">
          <div class="condition-icon">${renderOceanIcon('sunset')}</div>
          <div class="condition-label">일몰</div>
          <div class="condition-value">${data.sunset}</div>
        </div>
        <div class="condition-card">
          <div class="condition-icon">${renderOceanIcon('location')}</div>
          <div class="condition-label">위치</div>
          <div class="condition-value">${data.location || '월곶포구'}</div>
        </div>
      </div>
      <div id="weatherCard" class="weather-card weather-loading" data-section-title="오늘의 날씨">날씨 정보를 불러오는 중...</div>
      <div class="data-source">출처 ${data.source || '조수 데이터'} · 자동 5분 갱신</div>
    </div>
  `;

  container.innerHTML = oceanHTML;
  loadWeatherInfo();
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


function busRouteClass(routeName, routeTypeName) {
  const name = String(routeName || '').toUpperCase();
  const type = String(routeTypeName || '');
  if (name.startsWith('M') || type.includes('광역')) return 'route-red';
  if (['790', '790A', '790B'].includes(name) || type.includes('좌석')) return 'route-blue';
  if (['23', '32', '34', '63'].includes(name) || type.includes('일반')) return 'route-green';
  if (name === '1') return 'route-green';
  return 'route-default';
}

const BUS_PIN_STORAGE_KEY = 'ireResidentPinnedBusRoutes:v1';

function normalizeRouteName(routeName) {
  return String(routeName || '').trim().toUpperCase();
}

function normalizeStopKey(stopKey) {
  return String(stopKey || '').trim().toLowerCase();
}

function makePinKey(stopKey, routeName) {
  return `${normalizeStopKey(stopKey)}::${normalizeRouteName(routeName)}`;
}

function getPinnedRoutes() {
  try {
    return new Set(JSON.parse(localStorage.getItem(BUS_PIN_STORAGE_KEY) || '[]'));
  } catch (_) {
    return new Set();
  }
}

function savePinnedRoutes(pins) {
  localStorage.setItem(BUS_PIN_STORAGE_KEY, JSON.stringify([...pins]));
}

function toggleBusRoutePin(stopKey, routeName) {
  const key = makePinKey(stopKey, routeName);
  if (!key || key.endsWith('::')) return;
  const pins = getPinnedRoutes();
  if (pins.has(key)) pins.delete(key);
  else pins.add(key);
  savePinnedRoutes(pins);
  loadBusArrivals();
}

function applyUserPinnedSort(stopKey, arrivals) {
  const pins = getPinnedRoutes();
  return [...(arrivals || [])]
    .map((arrival, index) => ({
      ...arrival,
      isUserPinned: pins.has(makePinKey(stopKey, arrival.routeName)),
      originalIndex: index
    }))
    .sort((a, b) => {
      if (a.isUserPinned !== b.isUserPinned) return a.isUserPinned ? -1 : 1;
      if (a.isUserPinned && b.isUserPinned) return normalizeRouteName(a.routeName).localeCompare(normalizeRouteName(b.routeName), 'ko');
      return a.originalIndex - b.originalIndex;
    });
}

function scrollToBusStop(anchorId) {
  const target = document.getElementById(anchorId);
  if (!target) return;
  target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  target.classList.remove('bus-stop-highlight');
  // Restart the highlight animation even when the same marker is clicked repeatedly.
  window.requestAnimationFrame(() => {
    target.classList.add('bus-stop-highlight');
    window.setTimeout(() => target.classList.remove('bus-stop-highlight'), 1800);
  });
}

async function loadBusArrivals() {
  const card = document.getElementById('busInfoCard');
  if (!card) return;
  try {
    const response = await fetch(new URL('api/bus/arrivals?t=' + Date.now(), window.location.href), { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.note || '버스 정보 조회 실패');
    renderBusArrivals(data);
  } catch (error) {
    card.innerHTML = `
      <div class="bus-card-header">
        <div>
          <div class="section-kicker">교통 정보</div>
          <h2>이레하이니스 주변 버스</h2>
        </div>
        <div class="bus-badge">준비중</div>
      </div>
      <p class="bus-note">실시간 버스 정보를 잠시 불러오지 못했습니다. 곧 다시 시도해 주세요.</p>
    `;
  }
}

function renderBusArrivals(data) {
  const card = document.getElementById('busInfoCard');
  if (!card) return;
  const stationHtml = (data.stations || []).map(station => {
    const stopKey = station.anchorId || `stop-${station.mapNo || station.stationId || 'x'}`;
    const arrivals = applyUserPinnedSort(stopKey, station.arrivals || []);
    const arrivalHtml = arrivals.length ? arrivals.map(arrival => `
      <div class="bus-arrival-row ${arrival.hasPrediction === false ? 'no-prediction' : ''} ${arrival.isUserPinned ? 'pinned-route' : ''}">
        <div class="bus-route-no ${busRouteClass(arrival.routeName, arrival.routeTypeName)}">${arrival.routeName}</div>
        <div class="bus-arrival-main">
          <strong>${arrival.hasPrediction === false ? (arrival.statusText || '도착 예정 없음') : `${arrival.minutes}분 후`}</strong>
          <span>${arrival.hasPrediction === false ? (arrival.destination ? `${arrival.destination}행` : '현재 예측 차량 없음') : `${arrival.locationNo ? `${arrival.locationNo}번째 전` : '도착 정보 확인 중'}${arrival.nextMinutes ? ` · 다음 ${arrival.nextMinutes}분` : ''}${arrival.destination ? ` · ${arrival.destination}행` : ''}`}</span>
        </div>
        ${arrival.crowded ? `<div class="bus-crowd crowd-${arrival.crowded}">${arrival.crowded}</div>` : '<div class="bus-crowd-placeholder"></div>'}
        <button class="route-pin-btn ${arrival.isUserPinned ? 'active' : ''}" type="button" onclick="toggleBusRoutePin('${String(stopKey).replace(/'/g, "&#39;")}', '${String(arrival.routeName).replace(/'/g, "&#39;")}')" aria-label="${arrival.routeName} 노선 ${arrival.isUserPinned ? '고정 해제' : '상단 고정'}" title="${arrival.isUserPinned ? '고정 해제' : '상단 고정'}">${arrival.isUserPinned ? '📌' : '📍'}</button>
      </div>
    `).join('') : '<div class="bus-empty">현재 표시할 도착 정보가 없습니다.</div>';
    return `
      <div id="${station.anchorId || `stop-${station.mapNo || 'x'}`}" class="bus-station-card">
        <div class="bus-station-title">
          <span>${station.mapNo ? `<b class="map-no">${station.mapNo}</b> ` : ''}${station.stationName}${station.mobileNo ? ` <em>${station.mobileNo}</em>` : ''}</span>
          <small>${station.distance || ''}</small>
        </div>
        ${station.direction ? `<div class="bus-direction">${station.direction}</div>` : ''}
        ${arrivalHtml}
      </div>
    `;
  }).join('');
  card.innerHTML = `
    <div class="bus-card-header">
      <div>
        <div class="section-kicker">교통 정보</div>
        <h2>${data.title || '이레하이니스 주변 버스 도착'}</h2>
      </div>
      <div class="bus-badge">실시간</div>
    </div>
    <div class="route-legend">
      <span><i class="route-swatch route-green"></i> 일반/지선</span>
      <span><i class="route-swatch route-blue"></i> 좌석/간선형</span>
      <span><i class="route-swatch route-red"></i> 광역/M버스</span>
      <span><b class="legend-pin">📍/📌</b> 노선 직접 고정</span>
    </div>
    <div class="bus-grid">${stationHtml}</div>
    <div class="data-source">출처 ${data.source || '경기도 버스정보'} · 약 30초 캐시</div>
  `;
}



function switchInfoTab(tabName) {
  const activeName = ['ocean', 'bus', 'subway', 'adminMetrics'].includes(tabName) ? tabName : 'ocean';
  document.querySelectorAll('.transport-tab').forEach(button => {
    const isActive = button.getAttribute('aria-controls') === `${activeName}Panel`;
    button.classList.toggle('active', isActive);
    button.setAttribute('aria-selected', isActive ? 'true' : 'false');
  });
  document.querySelectorAll('.transport-panel').forEach(panel => {
    const isActive = panel.id === `${activeName}Panel`;
    panel.classList.toggle('active', isActive);
    panel.hidden = !isActive;
  });
  if (activeName === 'subway') scheduleSubwayTrainMarkerSync();
}

async function loadSubwayArrivals() {
  const card = document.getElementById('subwayInfoCard');
  if (!card) return;
  try {
    const response = await fetch(new URL('api/subway/arrivals?t=' + Date.now(), window.location.href), { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.note || '지하철 정보 조회 실패');
    renderSubwayArrivals(data);
  } catch (error) {
    card.innerHTML = `
      <div class="bus-card-header">
        <div>
          <div class="section-kicker">지하철 정보</div>
          <h2>월곶역 수인분당선</h2>
        </div>
        <div class="bus-badge">준비중</div>
      </div>
      <p class="bus-note">실시간 지하철 정보를 잠시 불러오지 못했습니다. 곧 다시 시도해 주세요.</p>
    `;
  }
}

const SUINBUNDANG_STATIONS = ['청량리','왕십리','서울숲','압구정로데오','강남구청','선정릉','선릉','한티','도곡','구룡','개포동','대모산입구','수서','복정','가천대','태평','모란','야탑','이매','서현','수내','정자','미금','오리','죽전','보정','구성','신갈','기흥','상갈','청명','영통','망포','매탄권선','수원시청','매교','수원','고색','오목천','어천','야목','사리','한대앞','중앙','고잔','초지','안산','신길온천','정왕','오이도','달월','월곶','소래포구','인천논현','호구포','남동인더스파크','원인재','연수','송도','인하대','숭의','신포','인천'];


function subwayMapStations(direction) {
  const topology = window.subwayTopology || SUINBUNDANG_STATIONS;
  const wolgotIndex = topology.indexOf('월곶');
  if (wolgotIndex < 0) return topology;
  // Hide each direction's post-Wolgot section on screen. The API can keep
  // estimating those trains internally, but the visible map stops at Wolgot.
  if (direction === '상행') return topology.slice(wolgotIndex);
  if (direction === '하행') return topology.slice(0, wolgotIndex + 1);
  return topology;
}

function isVisibleBeforeOrAtWolgot(train) {
  const topology = window.subwayTopology || SUINBUNDANG_STATIONS;
  const wolgotIndex = topology.indexOf('월곶');
  const logical = Number(train.logicalPosition);
  if (wolgotIndex < 0 || !Number.isFinite(logical)) return true;
  if (train.direction === '상행') return logical >= wolgotIndex;
  if (train.direction === '하행') return logical <= wolgotIndex;
  return true;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderTrainMarker(train, stations, orderIndex) {
  const topology = window.subwayTopology || SUINBUNDANG_STATIONS;
  const firstIndex = topology.indexOf(stations[0]);
  const logical = Number(train.logicalPosition);
  if (!Number.isFinite(logical) || firstIndex < 0) return '';
  const rowOffset = logical - firstIndex;
  const lateral = 0;
  const dirClass = train.direction === '하행' ? 'down' : 'up';
  const isEstimated = train.positionPrecision === 'estimated';
  const precisionClass = isEstimated ? 'estimated' : 'realtime';
  const label = isEstimated ? (train.trainNo || '') : (train.etaLabel || (train.etaSeconds != null ? `${Math.round(train.etaSeconds / 60)}분` : train.destination || ''));
  const precisionLabel = train.positionPrecision === 'estimated' ? '월곶 이후 추정 위치' : '실시간 위치';
  const title = `${train.destination || train.direction} ${train.trainNo || ''} 열차 · ${precisionLabel} · ${train.rawState || train.normalizedState || ''} · ${train.currentStation || ''}`;
  return `
    <button class="train-position-marker ${dirClass} ${precisionClass}" type="button" data-position-precision="${escapeHtml(train.positionPrecision || 'realtime')}" data-map-state="${escapeHtml(train.mapState || 'REALTIME_TRACKED')}" data-logical-position="${logical}" data-row-offset="${rowOffset}" style="--train-offset:${lateral}px" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}">
      <span class="train-marker ${dirClass}"><i aria-hidden="true"></i></span>
      <b>${escapeHtml(label)}</b>
    </button>
  `;
}

function syncSubwayTrainMarkerPositions(root = document) {
  const maps = root.querySelectorAll ? root.querySelectorAll('.subway-position-map') : [];
  maps.forEach(map => {
    const scroll = map.querySelector('.subway-map-scroll');
    const rows = [...map.querySelectorAll('.subway-station-row')];
    const markers = [...map.querySelectorAll('.train-position-marker')];
    if (!scroll || !rows.length || !markers.length || map.offsetParent === null) return;

    const scrollRect = scroll.getBoundingClientRect();
    if (scrollRect.height === 0) return;
    const centers = rows.map(row => {
      const rect = row.getBoundingClientRect();
      return rect.top - scrollRect.top + scroll.scrollTop + rect.height / 2;
    });
    const first = centers[0] ?? 0;
    const last = centers[centers.length - 1] ?? first;

    markers.forEach(marker => {
      const rowOffset = Number(marker.dataset.rowOffset);
      if (!Number.isFinite(rowOffset)) return;
      const lowerIndex = Math.floor(rowOffset);
      const progress = rowOffset - lowerIndex;
      const lower = centers[lowerIndex];
      const upper = centers[lowerIndex + 1];
      let y;
      if (Number.isFinite(lower) && Number.isFinite(upper)) {
        y = lower + (upper - lower) * progress;
      } else if (Number.isFinite(lower)) {
        y = lower;
      } else if (rowOffset < 0) {
        y = first;
      } else {
        y = last;
      }
      marker.style.setProperty('--train-y', `${Math.round(y * 100) / 100}px`);
    });
  });
}

function scheduleSubwayTrainMarkerSync() {
  requestAnimationFrame(() => syncSubwayTrainMarkerPositions(document));
}

window.addEventListener('resize', scheduleSubwayTrainMarkerSync);
window.addEventListener('load', scheduleSubwayTrainMarkerSync);

function renderSubwayDirectionMap(direction, arrivals, trainPositions = []) {
  const directionPositions = (trainPositions || []).filter(t => t.direction === direction && t.validationStatus !== 'rejected' && isVisibleBeforeOrAtWolgot(t));
  const directionArrivals = (arrivals || []).filter(a => a.direction === direction);
  const stations = subwayMapStations(direction);
  const trainsByStation = directionArrivals.reduce((acc, train) => {
    (acc[train.currentStation] ||= []).push(train);
    return acc;
  }, {});
  const terminal = direction === '상행' ? '왕십리·청량리 방면' : '인천 방면';
  const directionArrow = direction === '상행' ? '↑' : '↓';
  const directionLabel = direction === '상행' ? '위쪽으로 이동' : '아래쪽으로 이동';
  return `
    <div class="subway-position-map ${direction === '하행' ? 'down' : 'up'}">
      <div class="subway-map-head">
        <strong><b class="subway-direction-arrow ${direction === '상행' ? 'up' : 'down'}">${directionArrow}</b>${direction} 실시간 위치</strong>
        <span>${terminal} · ${directionLabel}${directionPositions[0]?.positionTimestamp ? ` · ${directionPositions[0].positionTimestamp.slice(11,16)} 기준` : ' · 현재 운행 위치 없음'}</span>
        <button class="subway-map-refresh" type="button" onclick="loadSubwayArrivals()" aria-label="${direction} 지하철 실시간 위치 새로고침">↻</button>
      </div>
      <div class="subway-map-scroll">
        <div class="subway-line-vertical ${direction === '하행' ? 'down' : 'up'}" aria-hidden="true"></div>
        ${stations.map((station, stationIndex) => {
          const trains = trainsByStation[station] || [];
          const stationClasses = [
            'subway-station-row',
            station === '월곶' ? 'target-station' : '',
            stationIndex === 0 || stationIndex === stations.length - 1 ? 'terminal-station' : '',
            stationIndex === 0 ? 'route-start-station' : '',
            stationIndex === stations.length - 1 ? 'route-end-station' : ''
          ].filter(Boolean).join(' ');
          return `
            <div class="${stationClasses}" data-station-index="${stationIndex}">
              <div class="subway-station-marker"><span class="station-dot"></span></div>
              <div class="subway-station-name">${escapeHtml(station)}</div>
              <div class="subway-train-tags">
                ${trains.map(train => `<span>${escapeHtml(train.destination || direction)} ${escapeHtml(train.trainNo || '')}</span>`).join('')}
              </div>
            </div>
          `;
        }).join('')}
        <div class="train-position-layer" aria-label="실시간 열차 위치">
          ${directionPositions.map((train, idx) => renderTrainMarker(train, stations, idx)).join('')}
        </div>
      </div>
    </div>
  `;
}

function renderSubwayMiniMap(arrivals, trainPositions = []) {
  const maps = ['상행', '하행'].map(direction => renderSubwayDirectionMap(direction, arrivals, trainPositions)).join('');
  return `<div class="subway-position-grid">${maps}</div>`;
}

function renderSubwayArrivals(data) {
  const card = document.getElementById('subwayInfoCard');
  if (!card) return;
  const grouped = (data.arrivals || []).reduce((acc, arrival) => {
    const key = arrival.direction || '도착 정보';
    (acc[key] ||= []).push(arrival);
    return acc;
  }, {});
  const allArrivals = data.arrivals || [];
  window.subwayTopology = data.stationTopology || SUINBUNDANG_STATIONS;
  const trainPositions = data.trainPositions || [];
  const groupHtml = Object.entries(grouped).length ? Object.entries(grouped).map(([direction, arrivals]) => `
    <div class="subway-direction-card">
      <div class="subway-direction-title"><span>${direction}</span><small>${arrivals[0]?.destination || ''}</small></div>
      ${arrivals.map(arrival => `
        <div class="subway-arrival-row">
          <div class="subway-line-badge">수인분당</div>
          <div class="bus-arrival-main">
            <strong>${arrival.displayTime || (arrival.minutes === 0 ? '곧 도착' : arrival.minutes ? `${arrival.minutes}분 후` : (arrival.arrivalMessage || '도착 정보 확인 중'))}</strong>
            <span>${arrival.sourceLabel || (arrival.predictionSource === 'TIMETABLE_ONLY' ? '시간표 기준' : '실시간')}${arrival.destination ? ` · ${arrival.destination}` : ''}${arrival.trainState && arrival.predictionSource !== 'TIMETABLE_ONLY' ? ` · ${arrival.trainState}` : ''}${arrival.arrivalMessage && arrival.predictionSource !== 'TIMETABLE_ONLY' ? ` ${arrival.arrivalMessage}` : ''}${arrival.trainNo ? ` · 열차 ${arrival.trainNo}` : ''}${arrival.updatedAt ? ` · ${arrival.updatedAt.slice(11, 16)} 기준` : ''}</span>
          </div>
        </div>
      `).join('')}
    </div>
  `).join('') : '<div class="bus-empty">현재 표시할 지하철 도착 정보가 없습니다.</div>';

  card.innerHTML = `
    <div class="bus-card-header">
      <div>
        <div class="section-kicker">지하철 정보</div>
        <h2>${data.title || '월곶역 수인분당선 도착'}</h2>
      </div>
      <button class="subway-refresh-btn" type="button" onclick="loadSubwayArrivals()">↻ 새로고침</button>
    </div>
    <p class="bus-note">${data.walkingInfo || '이레하이니스 인근 월곶역 도착 정보입니다.'} · 실시간 정보가 부족하면 시간표 기준으로 표시합니다.</p>
    <div class="subway-grid">${groupHtml}</div>
    ${renderSubwayMiniMap(allArrivals, trainPositions)}
    <div class="data-source">출처 ${data.source || '지하철 실시간 도착정보'} · 약 15초 캐시</div>
  `;
  scheduleSubwayTrainMarkerSync();
}

function scrollToOceanSection(section) {
  const target = section === 'weather' ? document.getElementById('weatherCard') : document.getElementById('seaSection');
  if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function loadWeatherInfo() {
  const card = document.getElementById('weatherCard');
  if (!card) return;
  try {
    const response = await fetch(new URL('api/weather?t=' + Date.now(), window.location.href), { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.note || '날씨 정보 조회 실패');
    renderWeatherInfo(data);
  } catch (error) {
    card.className = 'weather-card weather-error';
    card.textContent = '날씨 정보를 잠시 불러오지 못했습니다.';
  }
}

function renderWeatherIcon(condition) {
  const name = String(condition || '');
  if (name.includes('비')) {
    return '<svg viewBox="0 0 48 48" aria-hidden="true"><path class="wx-cloud" d="M16 31h18a8 8 0 0 0 .8-16 12 12 0 0 0-22.7 3.5A6.5 6.5 0 0 0 16 31Z"/><path class="wx-rain" d="M18 37l-2 4M26 37l-2 4M34 37l-2 4"/></svg>';
  }
  if (name.includes('흐림')) {
    return '<svg viewBox="0 0 48 48" aria-hidden="true"><path class="wx-cloud" d="M15 32h20a8 8 0 0 0 .5-16 12 12 0 0 0-23 4A6.5 6.5 0 0 0 15 32Z"/></svg>';
  }
  if (name.includes('구름')) {
    return '<svg viewBox="0 0 48 48" aria-hidden="true"><circle class="wx-sun" cx="18" cy="18" r="8"/><path class="wx-cloud" d="M18 33h17a7 7 0 0 0 .4-14 10 10 0 0 0-18.7 3.4A5.8 5.8 0 0 0 18 33Z"/></svg>';
  }
  return '<svg viewBox="0 0 48 48" aria-hidden="true"><circle class="wx-sun" cx="24" cy="24" r="9"/><path class="wx-ray" d="M24 5v6M24 37v6M5 24h6M37 24h6M10.6 10.6l4.2 4.2M33.2 33.2l4.2 4.2M37.4 10.6l-4.2 4.2M14.8 33.2l-4.2 4.2"/></svg>';
}

function renderWeatherInfo(data) {
  const card = document.getElementById('weatherCard');
  if (!card) return;
  const forecastTime = data.forecastAt ? new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit'
  }).format(new Date(data.forecastAt)) : '--:--';
  card.className = data.isUnavailable ? 'weather-card weather-error' : 'weather-card';
  if (data.isUnavailable) {
    card.innerHTML = `
      <div class="weather-section-label">오늘의 날씨</div>
      <div class="weather-head">
        <div class="weather-title-wrap">
          <div class="weather-icon">${renderWeatherIcon('흐림')}</div>
          <div>
            <div class="weather-kicker">기상청 연결 오류</div>
            <div class="weather-title">현재 날씨 정보를 불러오지 못했습니다</div>
          </div>
        </div>
        <div class="weather-source">기상청</div>
      </div>
      <div class="weather-note">거짓 예보값 대신 연결 실패로 표시합니다. ${data.note || ''}</div>
    `;
    return;
  }
  card.innerHTML = `
    <div class="weather-section-label">오늘의 날씨</div>
    <div class="weather-head">
      <div class="weather-title-wrap">
        <div class="weather-icon">${renderWeatherIcon(data.condition)}</div>
        <div>
          <div class="weather-kicker">날씨 · 바람</div>
          <div class="weather-title">${data.temperatureC ?? '--'}°C · ${data.condition || '날씨'} · ${data.windDirection || '바람'} ${data.windSpeedMs ?? '--'}m/s</div>
        </div>
      </div>
      <div class="weather-source">${data.model === 'KMA' ? '기상청' : 'Windy'}</div>
    </div>
    <div class="weather-metrics">
      <div><span>돌풍</span><strong>${data.windGustMs ?? '--'}m/s</strong></div>
      <div><span>강수</span><strong>${data.precipMm1h ?? data.precipMm3h ?? '--'}mm</strong></div>
      <div><span>${data.cloudCover == null ? '출처' : '구름'}</span><strong>${data.cloudCover == null ? (data.model === 'KMA' ? '기상청' : '--') : `${data.cloudCover}%`}</strong></div>
      <div><span>습도</span><strong>${data.humidity ?? '--'}%</strong></div>
    </div>
    <div class="weather-note">${forecastTime} 기준 · ${data.source || (data.model === 'KMA' ? '기상청' : 'Windy 예보')} ${data.secondarySource ? `· ${data.secondarySource}` : ''}${data.modelTemperatureDiffC ? ` · 모델 온도차 ${data.modelTemperatureDiffC}°C` : ''}</div>
  `;
}


async function setupAdminMetricsTab() {
  try {
    const meResponse = await fetch(new URL('api/portal/me?t=' + Date.now(), window.location.href), { cache: 'no-store' });
    if (!meResponse.ok) return;
    const me = await meResponse.json();
    if (me.role !== 'admin') return;
    const tabs = document.querySelector('.transport-tabs');
    const tabsCard = document.querySelector('.transport-tabs-card');
    if (!tabs || !tabsCard || document.getElementById('adminMetricsPanel')) return;
    tabs.insertAdjacentHTML('beforeend', '<button class="transport-tab admin-only-tab" type="button" role="tab" aria-selected="false" aria-controls="adminMetricsPanel" onclick="switchInfoTab(\'adminMetrics\'); loadAdminMetrics();">접속 통계</button>');
    tabsCard.insertAdjacentHTML('beforeend', `
      <div id="adminMetricsPanel" class="transport-panel" role="tabpanel" hidden>
        <section class="admin-metrics-card">
          <div class="bus-card-header">
            <div>
              <div class="section-kicker">Admin</div>
              <h2>접속자 수 · API 호출 통계</h2>
            </div>
            <button class="metrics-refresh" type="button" onclick="loadAdminMetrics()">새로고침</button>
          </div>
          <div id="adminMetricsContent" class="metrics-loading">통계를 불러오는 중...</div>
        </section>
      </div>
    `);
  } catch (error) {
    console.warn('admin metrics setup failed', error);
  }
}

function metricValue(counts, role, key) {
  return Number((counts?.[role] || {})[key] || 0);
}

function renderMetricBars(metrics, key, label) {
  const totalCounts = metrics.total || {};
  const resident = metricValue(totalCounts, 'resident', key);
  const admin = metricValue(totalCounts, 'admin', key);
  const anonymous = metricValue(totalCounts, 'anonymous', key);
  const max = Math.max(1, resident, admin, anonymous);
  return `
    <div class="metric-row">
      <div class="metric-row-head"><strong>${label}</strong><span>총 ${resident + admin + anonymous}</span></div>
      ${[
        ['resident', 'resident 계정', resident],
        ['admin', 'admin 계정', admin],
        ['anonymous', '비로그인/기타', anonymous],
      ].map(([role, name, value]) => `
        <div class="metric-bar-line ${role}">
          <span>${name}</span>
          <div class="metric-bar"><i style="width:${Math.round((value / max) * 100)}%"></i></div>
          <b>${value}</b>
        </div>
      `).join('')}
    </div>
  `;
}

async function loadAdminMetrics() {
  const content = document.getElementById('adminMetricsContent');
  if (!content) return;
  content.innerHTML = '<div class="metrics-loading">통계를 불러오는 중...</div>';
  try {
    const response = await fetch(new URL('api/admin/metrics?t=' + Date.now(), window.location.href), { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.note || '통계 조회 실패');
    const latestDays = (data.daily || []).slice(-7).reverse();
    content.innerHTML = `
      <div class="metrics-summary-grid">
        ${(data.sections || []).map(section => renderMetricBars(data, section.key, section.label)).join('')}
      </div>
      <div class="metrics-daily-card">
        <h3>최근 7일 일별 합계</h3>
        <div class="metrics-table-wrap">
          <table class="metrics-table">
            <thead><tr><th>날짜</th><th>계정</th><th>바다·날씨</th><th>버스</th><th>지하철</th><th>페이지</th></tr></thead>
            <tbody>
              ${latestDays.map(day => ['resident', 'admin'].map(role => `
                <tr>
                  <td>${day.date}</td>
                  <td>${role}</td>
                  <td>${metricValue(day.counts, role, 'api:ocean')}</td>
                  <td>${metricValue(day.counts, role, 'api:bus')}</td>
                  <td>${metricValue(day.counts, role, 'api:subway')}</td>
                  <td>${metricValue(day.counts, role, 'page:home')}</td>
                </tr>
              `).join('')).join('')}
            </tbody>
          </table>
        </div>
        <div class="data-source">업데이트 ${data.updatedAt || ''}</div>
      </div>
    `;
  } catch (error) {
    content.innerHTML = `<p class="bus-note">통계를 불러오지 못했습니다. ${error.message || ''}</p>`;
  }
}

// 초기 로드 및 주기적 업데이트
document.addEventListener('DOMContentLoaded', function() {
    lastKstDateKey = kstDateKeyFormatter.format(new Date());
    loadOceanData(false);
    loadBusArrivals();
    loadSubwayArrivals();
    loadWeatherInfo();
    setupAdminMetricsTab();
    startMinuteTicker();
    
    // 조수 원본 JSON은 1시간마다만 다시 받고, 현재 수위/남은 시간은 1분 ticker가 계속 재계산합니다.
    setInterval(() => {
        loadOceanData(true);
    }, 60 * 60 * 1000);

    // 교통/날씨는 변화 주기에 맞춰 별도 갱신합니다.
    setInterval(() => {
        loadBusArrivals();
    }, 60 * 1000);

    setInterval(() => {
        loadSubwayArrivals();
    }, 30 * 1000);

    setInterval(() => {
        loadWeatherInfo();
    }, 30 * 60 * 1000);

    setInterval(() => {
        }, 60 * 1000);
});

// 강제 새로고침 함수
function forceRefresh() {
    console.log("Force refreshing ocean data...");
    loadOceanData(true);
    loadBusArrivals();
    loadSubwayArrivals();
    loadWeatherInfo();
}
