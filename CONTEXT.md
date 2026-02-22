# 프로젝트 컨텍스트 (Deep Research 투자 분석 대시보드)
최종 업데이트: 2026-02-22

## 프로젝트 개요
- 기관용 딥 리서치 투자 분석 대시보드
- 티커 입력 → yfinance 데이터 수집 → 뉴스 파싱 → LLM 12단계 팩터 분석 → JSON 출력
- 핵심 철학: 한줄관통 강제, Variant Perception(시장 괴리) 도출
- 단일 파일 구조: app.py, requirements.txt, .streamlit/secrets.toml, CONTEXT.md

## 기술 스택
- Python 3.12, Streamlit, yfinance, BeautifulSoup, Plotly, pandas, numpy
- LLM: 현재 OpenAI GPT-4o → Claude Opus 4.6 전환 확정 (secrets.toml 수정으로 변경)
- 배포: Streamlit Community Cloud (비밀번호 잠금 적용)
- GitHub: wlcjs8080-cmd/deep-research-dashboard (main 브랜치)
- Supabase: 테이블 SQL 준비됨, 아직 연결 안 됨

## 핵심 파일 구조
- app.py: 메인 대시보드 코드
- requirements.txt: 패키지 목록
- .streamlit/secrets.toml: API 키 (비공개, 절대 공개 금지)
- CONTEXT.md: 이 파일 (프로젝트 맥락 기록)

════════════════════════════════════════
1차 세션 (2026-02-21)
════════════════════════════════════════
- app.py 코드 생성, requirements.txt 생성 및 패키지 설치
- secrets.toml 세팅 (OpenAI API 키 등록, $10 충전, 자동충전 OFF)
- AAPL 첫 테스트 성공

════════════════════════════════════════
2차 세션 (2026-02-21)
════════════════════════════════════════
### 완료
- NVDA 테스트 성공, UI 정상 작동 확인
- CONTEXT.md 생성

### 발견된 핵심 문제점
1. 한줄관통이 형식만 채우고 구체적 팩트 없음
2. A/B/C 등급 정의 부재
3. 옵션 시장 해석 없음 (수치만 나열)
4. Part B(11~20) 일반론만 나옴 (yfinance에 없는 데이터)
5. 핵심 산업 이슈 누락

### 근본 원인
- yfinance만으로는 산업 맥락 분석 불가
- "데이터 없으면 쓰지 마라" + "깊은 인사이트를 내라" 프롬프트 모순
- 해결: LLM 자체 지식 허용 + 출처 구분 표기 ([DATA]/[LLM지식]/[추정])

════════════════════════════════════════
3차 세션 (2026-02-22)
════════════════════════════════════════
### 완료
- GitHub 계정(wlcjs8080-cmd) 및 저장소(deep-research-dashboard) 생성
- app.py, requirements.txt GitHub 업로드
- Streamlit Cloud 배포 완료 (.streamlit.app URL)
- 비밀번호 잠금 기능 추가
- _SYSTEM_PROMPT 재작성: 22개→12개 항목, 품질 규칙 12가지
- user_prompt 재작성: 12개 항목 상세 지침 + JSON 구조
- ITEM_TITLE_MAP 22개→12개 교체
- UI 섹션: Part A(1~3), Part B(4~11), Part C(12)
- items 범위: items[:3], items[3:11]
- "22단계"→"12단계" 일괄 변경
- 취소선(~~) 자동 제거 필터 추가
- MU 테스트 성공, 12개 항목 정상 출력

### 모델 결정
- Opus 4.6 단일 호출 확정 (1회 약 770원, $10으로 약 18회)
- 3분할 호출(770원×3=2,300원)은 비용 과다로 보류
- GPT-4.1+3분할(750원)도 검토했으나 Opus 단일호출이 가성비 최선

### FMP API 심층 조사 완료
- FMP(Financial Modeling Prep) 무료티어 채택 확정
- 무료: 일 250호출, 분석 1회당 1~2호출이면 충분
- 향상 항목: #2(경영진 크로스체크), #3(매출 드라이버), #11(촉매 캘린더)
- 예상 품질 향상: 약 25% ([추정] 태그 → [DATA] 태그로 전환)
- 비교 대상: Finnhub(무료 제한적), API Ninjas(유료 $99~), Seeking Alpha(스크래핑 불안정)
- 다음 단계: FMP 가입 → API 키 발급 → secrets.toml 추가 → app.py에 collect_earnings_transcript() 함수 추가

### 현재 상태
- 로컬(Cursor) = GitHub = Streamlit Cloud 코드 동기화 완료
- 12개 항목 체계 정상 작동
- 비밀번호 잠금 작동 (Streamlit Cloud)

════════════════════════════════════════
다음 세션 작업 (우선순위 순)
════════════════════════════════════════
0. [최우선] FMP API 연동 (어닝콜 트랜스크립트) — 품질 25% 향상
   → FMP 가입 → 키 발급 → secrets.toml 추가 → app.py 함수 추가
1. [최우선] LLM 모델 전환: GPT-4o → Claude Opus 4.6
   → secrets.toml에서 provider=anthropic, model=claude-opus-4-6 변경
   → requirements.txt에 anthropic 패키지 추가
2. 분석 품질 검토 및 프롬프트 미세조정
3. 마크다운 헤더(###) 자동 제거 필터 추가
4. Supabase 연동 (리포트 저장)
5. UI 개선 (첫 화면 API 설정 코드 제거, 폰트 통일)

════════════════════════════════════════
영구 참고사항
════════════════════════════════════════
- 코드 수정 흐름: Cursor에서 수정 → GitHub에 푸시 → Streamlit Cloud 자동 반영
- secrets.toml은 절대 공개 금지 (GitHub에 올리지 않음)
- 데이터 소스: yfinance + Yahoo RSS + FMP(예정)
- 향후 추가 데이터: SEC EDGAR, 특허/채용/로비 데이터
- 분석 1회 비용: Opus 4.6 기준 약 770원 ($10으로 약 18회)
- Streamlit Cloud 비밀번호: secrets.toml [auth] 섹션에 설정됨

════════════════════════════════════════
다음 세션 시작 시 전달할 것
════════════════════════════════════════
1. 이 CONTEXT.md 전체 내용
2. app.py 코드 (Cursor에서 복사 또는 GitHub에서 가져오기)
3. requirements.txt 내용
4. secrets.toml 내용은 비공개 유지 (키 값은 전달하지 않음)
