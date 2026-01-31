# 월곶포구 물때표

정적 JSON 파일과 GitHub Actions를 이용한 월곶포구 물때표 웹 애플리케이션입니다.

## 구조

```
your-repo/
├── index.html                 # 메인 HTML 파일
├── data/
│   └── tide/
│       └── .gitkeep          # 빈 폴더 커밋용 더미 파일
├── scripts/
│   └── update_tide_json.py   # 물때 데이터 생성 스크립트
└── .github/
    └── workflows/
        └── update-tide.yml   # GitHub Actions 워크플로우
```

## 기능

- 🌊 월곶포구 실시간 물때 정보
- 📱 반응형 디자인
- 🔄 자동 데이터 업데이트 (매일 09:00 KST)
- 📊 정적 JSON 파일 기반 (빠른 로딩)
- 🌅 일출/일몰, 월출/월몰 정보
- 🌙 월물(사리/조금) 상태 표시

## 데이터 소스

badatime.com (m.badatime.com)에서 월곶포구(idx=162)의 물때 데이터를 가져옵니다.

## 자동 업데이트

GitHub Actions를 통해 매일 09:00 KST에 자동으로 데이터를 업데이트합니다:

1. 현재 달의 데이터 생성
2. 다음 달의 데이터 생성  
3. JSON 파일을 `data/tide/` 폴더에 저장
4. 변경사항이 있으면 자동 커밋

## 로컬 개발

### 1. 의존성 설치
```bash
pip install requests beautifulsoup4
```

### 2. 데이터 수동 생성
```bash
# 현재 달 데이터
python scripts/update_tide_json.py

# 특정 년월 데이터
python scripts/update_tide_json.py 2024 2
```

### 3. 로컬 서버로 확인
```bash
python -m http.server 8000
# 브라우저에서 http://localhost:8000 접속
```

## JSON 파일 형식

`data/tide/YYYY-MM.json` 형태로 저장:

```json
{
  "1": {
    "highTides": [
      {"time": "05:30", "height": "--", "change": "--"}
    ],
    "lowTides": [
      {"time": "11:45", "height": "--", "change": "--"}
    ],
    "moonPhase": "8물 - 사리 (물살 강함)",
    "sunrise": "07:39",
    "sunset": "17:54",
    "moonrise": "13:35",
    "moonset": "04:19"
  }
}
```

## 배포

GitHub Pages에 배포하는 것을 권장합니다:

1. GitHub 레포지토리 생성
2. Settings > Pages에서 Source를 "Deploy from a branch"로 설정
3. main 브랜치의 root 폴더 선택
4. Actions가 자동으로 데이터를 업데이트하고 페이지가 반영됨

## 에러 처리

- JSON 파일이 없거나 로딩 실패시 친절한 에러 메시지 표시
- 실시간 데이터 가져오기 실패시 샘플 데이터로 fallback
- 네트워크 오류에 대한 안정적인 처리