# 나의 여행 지도

1996년 입사 이후 30년간의 출장·주재·여행 기록을 **지도 한 장과 연표 한 줄**로 모으는 개인 아카이브 —
그리고 그 기록을 처음 보는 사람에게 보여 주는 **여행 홈페이지**.
설계 문서는 [PRD_MyTravel.md](PRD_MyTravel.md).

**공개본: https://holyjoekang.github.io/my-travel-map/**
(실명을 뺀 `--public` 빌드다. 개인 빌드는 아래 방법으로 직접 만든다.)

## 빠른 시작

```bash
python scripts/build_all.py
```

`app/index.html` 이 만들어진다. 브라우저로 열면 끝이다 — **서버도, API 키도, 설치할 패키지도 없다.**
파이썬 3.10 이상, 표준 라이브러리만 쓴다.

여행지 사진만 trip.com 에서 받아 온다(아래 [여행지 사진](#여행지-사진-tripcom)).
캐시가 이미 있으면 빌드는 밖을 부르지 않고, 사진이 안 떠도 나머지 화면은 그대로 돈다.

## 지금 들어 있는 것

| | 수 |
|---|---|
| 여정 | 47 |
| 장소 | 143 (도시급 78 · 장소 65) |
| 블로그 여행 후보 | 112 (687편 중) |
| 사진·소개가 붙은 여행지 | 75 |
| 기간 | 1996 ~ 2026 |

출처별로는 구글 지도 저장 목록 128개(2005년 지역전문가), 구글 시트 출장 이력 28건(2016~19),
구글 문서 여행 일지, 네이버 블로그, 그리고 기억이다.

## 구조

```
data/
  site.json               홈 화면 문구·표지·모집 코스 ← 사이트 얼굴은 여기서 고친다
  tripcom_places.json     장소 이름 → trip.com 목적지 번호
  destinations.json       ← 캐시 · trip.com 사진 주소와 소개 발췌
  gmaps_saved_2005.json   지도 저장 목록 「2005년 지역전문가」 128개 (수집 완료)
  trips.json              여정 원장 — 사람은 people 에만 두고 여정은 id로 참조
  trip_html/              여행 전에 만들어 둔 일정표 HTML ← 여기에 넣으면 여정에 붙는다
  trip_html/private/      개인 일정표 (gitignore — 개인 빌드에만 들어간다)
  itineraries.json        ← 빌드 산출물 · 여정 ↔ 일정표 대응표
  place_coords.json       도시·장소 좌표 원장 [위도, 경도]
  place_aliases.json      표기 → 정식 도시명 (하문=샤먼 시, 온주=원저우 시 …)
  blog_cat*.json          네이버 블로그 카테고리별 글 목록 687편
  blog_bodies.json        그 글들의 본문 앞부분 (판정용)
  llm_verdicts.json       2단계 판정 결과
  import_candidates.json  ← 빌드 산출물 · 승인 대기 후보
  private.json            실명·업무 요약 (gitignore — 저장소에 없다)
  places.json             ← 빌드 산출물
  world_land.json         ← 빌드 산출물 (세계지도 윤곽 캐시)
scripts/
  topojson.py             TopoJSON 디코더
  fetch_world_map.py      세계지도 내려받아 캐시 (빌드 때 1회)
  fetch_blog_bodies.py    블로그 본문 수집 (이어받기)
  fetch_destinations.py   trip.com 여행지 사진·소개 수집 (캐시)
  classify_posts.py       글 → 여정 후보 판정 (규칙 + LLM)
  build_itineraries.py    trip_html 일정표를 여정에 붙인다 (규칙만 쓴다 · LLM 없음)
  build_places.py         별칭 정규화 + 좌표 결합 → places.json
  build_app.py            데이터를 HTML에 주입 → app/index.html
  build_all.py            위 넷을 순서대로
  release.py              빌드 → 테스트 → 커밋 → 푸시 (배포는 CI가 이어받는다)
app/
  index.template.html     화면 (여기를 고친다)
  index.html              ← 빌드 산출물
  itinerary/              ← 빌드 산출물 · 일정표 사본 (여정에서 열린다)
tests/
  test_build.py           python -m unittest discover -s tests
```

**고칠 때는 `app/index.template.html` 을 고치고 다시 빌드한다.** `app/index.html` 은 산출물이라 덮어써진다.

## 화면

- **홈** — 표지 사진 한 장과 숫자 띠, **다시 가고 싶은 곳** 8곳, 최근의 여정,
  안내할 수 있는 코스, 동행 문의. 문구와 표지와 코스는 `data/site.json` 에서 고친다
- **여행지** — 다녀온 도시를 사진 카드로. 나라별로 걸러 본다. 카드를 누르면 그 도시의 내 기록이,
  “Trip.com 가이드”를 누르면 원문이 열린다
- **지도** — 세계 / 아시아 / 중국 축척. 점 크기는 방문 횟수, 색은 목적. 연도 슬라이더를 끌면 시간순으로 켜진다
- **연표** — 1996~2026을 연도별로. 각 해에 그때의 시대(E1~E7)와 직책이 함께 붙는다
- **지역** — 나라별 도시 목록
- **통계** — 도시·나라·여정 수, 가장 많이 간 곳
- **도시 페이지** — 그 도시의 모든 방문 이력과 그 안의 장소들 (베이징은 여정 14 · 장소 23)
- **사진** — 끌어놓으면 EXIF 촬영일시를 읽어 맞는 여정을 찾아준다. 썸네일은 브라우저에만 저장된다
- **후보** — 블로그에서 뽑은 여정 후보를 승인/버림으로 검토하고, 승인한 것만 `trips.json` 형식으로 내보낸다
- **일정표** — 일정표가 붙은 여정은 카드에 `일정표` 표가 뜨고, 눌러서 연 패널 맨 위의
  카드로 그 날 하루하루의 계획이 열린다 (아래 [일정표](#일정표-trip_html))

지도는 외부 타일을 받지 않는다. 국경 폴리곤을 미리 받아 SVG로 직접 그리므로
오프라인에서도 뜨고, 아티팩트 CSP에도 걸리지 않는다.

## 일정표 (trip_html)

여행 전에 따로 만들어 둔 **일정표 한 장**(HTML)을 여정에 붙인다.
`data/trip_html/` 에 파일을 넣고 빌드하면 끝이다 — 손으로 이어 줄 것이 없다.

```bash
python scripts/build_itineraries.py --check   # 무엇에 붙을지만 본다
python scripts/build_all.py                   # 붙이고 앱까지 다시 만든다
```

붙이는 방법은 규칙뿐이고 **LLM을 쓰지 않는다.** 파일에서 제목·기간·도시를 읽어
(제목 → 본문 → 파일 이름 순으로 찾는다) 도시가 겹치고 날짜가 30일 안에 있는 여정을 고른다.
**짝이 없으면 그 여행을 여정으로 새로 적는다**(`planned: true`) — 아직 다녀오지 않은 여행도
연표와 홈에 `예정` 으로 선다. 손으로 짝을 정하려면 `data/trips.json` 의 그 여정에
`"itinerary": "파일이름.html"` 을 적으면 그것이 이긴다.

**공개와 개인.** `data/trip_html/` 에 둔 것은 저장소에 올라가고 공개본에도 실린다.
실명·연락처·집주소가 들어 있는 일정표는 `data/trip_html/private/` 에 둔다 —
gitignore 라 저장소에 올라가지 않고 개인 빌드에만 들어간다(PRD §11).
공개 폴더에 그런 것이 보이면 **빌드가 멈춘다**(이름+직책·전화·이메일·집 호수 형태로 잡는다).

## 여행지 사진 (trip.com)

도시 이름과 날짜만으로는 처음 보는 사람에게 그림이 안 그려진다.
그래서 **다녀온 도시의 얼굴을 trip.com 여행 가이드에서 빌려 온다**(PRD §14).

```bash
python scripts/fetch_destinations.py              # 캐시에 없는 것만
python scripts/fetch_destinations.py --refresh    # 전부 다시
python scripts/fetch_destinations.py --only 베이징 상하이
```

- **빌드가 받고 화면은 안 받는다.** 표지 사진 주소·소개 발췌·명소 사진 주소를
  `data/destinations.json` 에 캐시해 두고, 앱은 그 캐시만 읽는다
- **사진은 복사하지 않고 링크로 건다.** 번들에는 주소만 들어간다. 소개 글도 260자 발췌만 싣고
  카드마다 원문으로 링크한다. 출처는 카드·도시 패널·바닥글에 밝힌다
- **없어도 돈다.** 사진을 못 받으면 그 자리는 흙빛 바탕에 도시 이름만 남는다.
  밖에서 받는 것은 `ak-d.tripcdn.com` 의 사진뿐이고, 테스트가 그 한 곳만 허용한다

**도시를 더 넣으려면** trip.com 에서 그 도시 가이드를 열고 주소 끝 숫자를
`data/tripcom_places.json` 에 적은 뒤 다시 돌린다 — `.../destination/beijing-1/` 의 `1`.
trip.com 에 가이드가 없는 곳(남해·부여·평택·실리콘밸리 등)은 비워 둔다.

## 여행객 모집용 문구

홈의 **안내할 수 있는 길**과 **동행 문의**는 `data/site.json` 에서 온다.

```json
{ "tagline": "30년, 발로 그린 아시아",
  "heroPlace": "베이징",
  "offers": [{ "title": "…", "body": "…", "places": ["시안 시", "둔황 시"] }],
  "invite": { "title": "…", "body": "…",
              "contact": { "email": "", "kakao": "", "instagram": "" } } }
```

`contact` 는 **적은 것만 버튼으로 나가고**, 비어 있으면 버튼 대신 안내 문구가 나간다.
**공개 빌드에도 그대로 나가므로 공개해도 되는 연락처만 적는다.**

## 블로그에서 여정 뽑기 (Phase 2)

```bash
python scripts/fetch_blog_bodies.py                          # 본문 수집 (687편, 약 4분)
python scripts/classify_posts.py                             # 1단계: 규칙
python scripts/classify_posts.py --api                       # 2단계: Claude API (ANTHROPIC_API_KEY)
python scripts/classify_posts.py --apply data/llm_verdicts.json   # 또는 밖에서 판정한 결과를 반영
```

2단계로 나눈 이유는 비용이다. 1단계 규칙이 687편 중 **575편을 자동으로 걸러내** 모델에 물을 것은
109편만 남았다. 제목에 확실한 신호(`[대련 여행]`, `2박 3일`)가 있으면 바로 채택하고,
확실한 제외 신호(`영화 리뷰`, `베스트셀러`, 마라톤 대회 안내)가 있으면 바로 버린다.
남은 것은 본문 앞부분의 이동 흔적(`도착했다`, `숙소`, `공항`, `일정`)과 칼럼 말투(`저자는`, `분석에 따르면`)로
점수를 매겨 가운데 띠만 2단계로 넘긴다.

**후보는 자동 등록되지 않는다.** 앱의 **후보** 탭에서 승인해야 여정이 된다(PRD §1).

## 공개 빌드

출장 기록에는 거래선·동료 실명과 업무 내용이 들어 있다.
GitHub Pages(https://holyjoekang.github.io/my-travel-map/)에는 **공개 빌드만** 올라간다 —
CI에는 `data/private.json` 이 없으므로 애초에 실명을 알 수 없다.

```bash
python scripts/build_app.py --public   # → app/index.public.html
```

올리는 것은 스크립트 하나로 한다. **테스트가 떨어지면 커밋하지 않는다.**

```bash
python scripts/release.py -m "무엇을 고쳤는지"
```

`--dry-run` 은 무엇을 할지만 보여 주고, `--no-push` 는 커밋까지만 하고,
`--watch` 는 푸시 뒤 CI 결과까지 지켜본다(`gh` 필요).
푸시가 끝나면 Actions 가 공개 빌드를 다시 만들어 Pages 에 올린다.

**실명은 저장소에 없다.** `data/private.json`(gitignore)에만 있고, 이 파일이 없으면
공개 표기만으로 그대로 빌드된다. 그래서 CI와 남의 클론에서도 문제없이 돈다.

공개 빌드는 **실명을 번들에 넣지 않는다.** 화면에서 가리는 게 아니라 데이터에서 빼므로 소스를 봐도 안 나온다.
실명이 하나라도 남아 있으면 빌드가 실패한다.

표기를 정하려면 `data/trips.json` 의 `people[*].publicLabel` 에 직접 적는다
(`"Mr. K"`, `"Ms. J"` 등). **비워두면 "동료 A" 같은 중립 표기로 나간다** —
이름만으로 성별을 추측하지 않기 때문이다. 자세한 규칙은 PRD §11.

공개용 요약이 없는 출장은 요약 없이 도시·날짜만 나간다(`summaryPublic` 에 적으면 그게 나간다).

## 데이터 더 넣기

- **여정 추가** — `data/trips.json` 의 `trips` 에 한 줄 추가. 도시는 원문 표기 그대로 써도 된다
- **표기가 새로 나오면** — `data/place_aliases.json` 에 `"새표기": "정식 도시명"` 추가
- **새 도시** — `data/place_coords.json` 에 `"도시명": [위도, 경도]` 추가
- 빌드가 `좌표없음` 을 알려준다. CI에서 막으려면 `python scripts/build_places.py --strict`

## 테스트

```bash
python -m unittest discover -s tests -v
```

별칭이 한 도시로 모이는지, 좌표 범위가 맞는지, 여정 날짜가 시대와 어긋나지 않는지,
그리고 **공개 빌드에 실명이 새지 않는지**를 본다.

## 남은 일

PRD §13 참조. 큰 것만 옮기면:

- `needsReview` 12건 — 상위 도시가 불분명한 장소
- 저장 목록에 없는 지역전문가 시절 도시 보태기 (63곳은 기억보다 적다)
- 1996~2004 첫 출장들의 연·월 특정 — 지금은 연도 범위만 있다
- 후보 112건 승인 — 앱의 **후보** 탭에서 검토한 뒤 `trips.json` 에 넣는다
- 후보 중 10건은 도시를 못 찾았다 (본문에 지명이 안 나오는 회고 글)
- `data/site.json` 의 `contact` 가 비어 있다 — 모집을 시작하려면 먼저 채운다
- trip.com 에 가이드가 없는 8곳(남해·부여·유명산·평택·뉴저지·실리콘밸리·펑라이 시·침사추이)은 사진이 없다
- 블로그 '힐링 모먼트' 1,397편 접근 경로
