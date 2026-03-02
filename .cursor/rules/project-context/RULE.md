---
description: "프로젝트 맥락, 히스토리, 계획 — 모든 대화에서 항상 참조"
alwaysApply: true
---

# ============================================================
# 이 파일의 역할 (에이전트 필독)
# ============================================================
# 이 파일은 프로젝트의 "무엇을 하고 있는가"를 기록하는 곳이다.
#
# 포함하는 내용:
#   - 프로젝트 개요 및 핵심 철학
#   - 기술 스택 및 아키텍처
#   - 파일 구조
#   - 세션별 작업 히스토리 (누적 기록)
#   - 현재 상태
#   - 다음 작업 목록 (우선순위 순)
#   - 장기 로드맵
#   - 영구 참고사항
#
# [에이전트 수정 규칙]
# - 이 파일을 수정할 때 기존 내용을 절대 삭제하지 마라.
# - 세션 히스토리는 맨 아래에 새 세션을 추가하는 방식으로만 작성하라.
# - "다음 작업 목록"은 완료된 항목에 ✅ 표시만 하고 삭제하지 마라.
# - "현재 상태" 섹션만 최신으로 덮어쓰기 가능하다.
# - 어떤 내용이든 이 파일에 해당하는지 판단이 안 되면,
#   coding-standards/RULE.md 또는 workflow/RULE.md의 역할 설명을 읽고 비교하라.
# ============================================================


# 프로젝트 개요

## 프로젝트명
기관용 딥 리서치 투자 분석 대시보드 (Institutional Deep Research Dashboard)

## 핵심 철학
1. 정보 피로도 제거: 모든 분석 항목에 "한줄관통"을 강제하는 UI와 프롬프트 구조
2. Variant Perception: 시장 기대치와 실제의 괴리를 찾아 Alpha(초과수익) 근거 제공
3. 데이터 출처 투명성: 모든 수치에 [DATA] / [LLM지식] / [추정] 태그 필수

## 기능 요약
티커 입력 → yfinance 데이터 수집 → Yahoo RSS 뉴스 파싱 → FMP 어닝콜 수집 → LLM 12단계 팩터 분석 → JSON 출력 → UI 렌더링

최종 의견은 매수/보유/매도 중 하나이며, Bull/Base/Bear 3시나리오 + 비대칭 리스크/리워드 비율을 함께 제시한다.
Supabase 저장(예정)과 JSON 다운로드를 지원한다.


# 기술 스택

## 언어 및 프레임워크
- Python 3.12
- Streamlit (웹 UI)
- Plotly (차트)
- pandas, numpy (데이터 처리)

## 데이터 수집
- yfinance: 주가, 재무제표, 기관/내부자, 옵션 체인
- BeautifulSoup: Yahoo Finance RSS 뉴스 헤드라인 파싱
- FMP API (Financial Modeling Prep): 어닝콜 트랜스크립트, 어닝 서프라이즈
  - 무료 티어, 일 250호출 제한
  - 분석 1회당 1~2호출이면 충분

## LLM
- 현재: OpenAI GPT-4.1 (1회 약 145원, $10으로 ~100회)
- 전환 예정: Anthropic Claude Opus 4.6 (1회 약 435원, $10으로 ~33회)
- secrets.toml의 [llm] 섹션에서 provider/model 변경으로 전환

## 데이터베이스
- Supabase: 테이블 SQL은 app.py 상단 주석에 준비됨, 아직 연결 안 됨

## 배포
- GitHub: wlcjs8080-cmd/deep-research-dashboard (main 브랜치)
- Streamlit Community Cloud: main 브랜치 push 시 자동 반영
- 비밀번호 잠금 적용됨 (secrets.toml [auth] 섹션)


# 파일 구조

프로젝트 루트/
├── .cursor/
│   └── rules/
│       ├── project-context/
│       │   └── RULE.md          ← 이 파일
│       ├── coding-standards/
│       │   └── RULE.md          ← 코딩 규칙
│       └── workflow/
│           └── RULE.md          ← 작업 흐름 규칙
├── .streamlit/
│   └── secrets.toml             ← API 키 (절대 공개 금지)
├── app.py                       ← 메인 코드 (단일 파일, 모든 로직 포함)
├── requirements.txt             ← 패키지 목록
├── CONTEXT.md                   ← 기존 맥락 문서 (레거시, 이 파일로 이전됨)
├── .gitignore                   ← secrets.toml 제외 설정
└── README.md

## app.py 주요 함수 목록
- collect_yfinance_data(): yfinance 전체 데이터 수집 파이프라인
- collect_fmp_earnings_transcript(): FMP 어닝콜 트랜스크립트 + 어닝 서프라이즈 수집
- collect_news(): Yahoo Finance RSS 뉴스 헤드라인 수집 (최대 20건)
- get_peer_data(): 섹터 기반 동종 기업 최대 3곳 데이터 수집
- prepare_data_context(): LLM에 주입할 데이터 컨텍스트 문자열 생성
- run_llm_analysis(): 12단계 LLM 분석 실행 → JSON Dict 반환
- save_to_supabase(): Supabase에 리포트 저장
- load_past_reports(): 과거 리포트 목록 조회
- render_top_summary(): 최상단 최종 의견 요약
- render_price_chart(): 캔들스틱 주가 차트 + 거래량 + MA선
- render_financial_cards(): 핵심 재무 지표 카드
- render_institutional_insider(): 기관 보유 + 내부자 거래
- render_peer_table(): 동종 기업 비교 테이블
- render_options_summary(): 옵션 IV vs 실현변동성 분석
- render_news(): 뉴스 헤드라인
- render_analysis_item(): 단일 분석 항목 렌더링
- render_alpha_matrix(): 알파 소스 종합 매트릭스
- render_final_opinion_box(): 최종 투자 의견 박스


# 세션 히스토리

## 1차 세션 (2026-02-21)
- app.py 코드 생성, requirements.txt 생성 및 패키지 설치
- secrets.toml 세팅 (OpenAI API 키 등록, $10 충전, 자동충전 OFF)
- AAPL 첫 테스트 성공

## 2차 세션 (2026-02-21)
- NVDA 테스트 성공, UI 정상 작동 확인
- CONTEXT.md 생성
- 발견된 문제점:
  - 한줄관통이 형식만 채우고 구체적 팩트 없음
  - A/B/C 등급 정의 부재
  - 옵션 시장 해석 없음 (수치만 나열)
  - Part B(11~20) 일반론만 나옴 (yfinance에 없는 데이터)
  - 핵심 산업 이슈 누락
- 근본 원인: yfinance만으로는 산업 맥락 분석 불가
- 해결 방향: LLM 자체 지식 허용 + 출처 구분 표기 ([DATA]/[LLM지식]/[추정])

## 3차 세션 (2026-02-22)
- GitHub 계정(wlcjs8080-cmd) 및 저장소(deep-research-dashboard) 생성
- app.py, requirements.txt GitHub 업로드
- Streamlit Cloud 배포 완료 + 비밀번호 잠금 기능 추가
- 22개 분석 항목 → 12개 항목 체계로 전면 재구성:
  - _SYSTEM_PROMPT 재작성 (품질 규칙 12가지 포함)
  - user_prompt 재작성 (12개 항목 상세 지침 + JSON 구조)
  - ITEM_TITLE_MAP 22개 → 12개 교체
  - UI 섹션: Part A(1~3), Part B(4~11), Part C(12)
  - items 범위: items[:3], items[3:11]
- 취소선(~~) 자동 제거 필터 추가
- MU 테스트 성공, 12개 항목 정상 출력
- FMP API 조사 완료:
  - FMP 무료 티어 채택 확정 (일 250호출)
  - 향상 항목: #2(경영진 크로스체크), #3(매출 드라이버), #11(촉매 캘린더)
  - 예상 품질 향상: 약 25%
- 모델 비용 비교 후 결정:
  - Opus 4.6 단일 호출 확정 (1회 약 435원)
  - 3분할 호출(770원×3=2,300원)은 비용 과다로 보류

## 5차 세션 (2026-02-22)
- 티커 유효성 검증 강화:
  - 영문+숫자+점만 허용 (한글/특수문자 차단)
  - yfinance 데이터 존재 확인 (currentPrice 또는 marketCap 체크)
- OpenAI API 키 재발급 (GitHub 노출로 자동 비활성화됨)
- .gitignore 인코딩 수정 (UTF-16 → UTF-8) — secrets.toml 보안 확보
- NVDA 분석 테스트 실행 (GPT-4.1 기반)
- 품질 심층 진단 — 12개 문제점 도출:
  1. 취소선(~~)이 여전히 수시로 등장
  2. Bull/Bear Case 확률이 텍스트에 묻혀 직관적이지 않음
  3. 핵심 재무지표가 맥락 없이 숫자만 나열됨
  4. 기관 보유/내부자 거래 테이블 헤더가 전부 영어
  5. 확신도 A/B/C가 작은 캡션으로만 표시되어 눈에 안 띔
  6. 옵션/변동성 해설이 전문가 용어로만 되어있음
  7. 뉴스가 무관한 일반 시장 뉴스까지 포함
  8. 리스크 시나리오 괄호 안에 라벨 없이 숫자만 나열
  9. 상세 근거 글자 크기가 제멋대로 (마크다운 헤더 혼입)
  10. 21번 Top 3 인사이트가 나열만 되고 설명 없음
  11. 22번 최종 의견 확률이 텍스트에 묻혀있음
  12. 전문 용어 직관적 번역 부재
- 현재 품질 평가: 10점 만점 기준 4점 (목표: 7점 이상)

## 6차 세션 (2026-02-25)
- .cursor/rules/ 체계 도입
- 기존 CONTEXT.md 내용을 3개 RULE.md로 이전
  - project-context/RULE.md (이 파일)
  - coding-standards/RULE.md
  - workflow/RULE.md

## 7차 세션 (2026-03-02)
- _SYSTEM_PROMPT을 1번 전용(v8)으로 축소
- user_prompt을 1번(밸류에이션 갭 진단) v8로 교체
- UI 렌더링: Part A/B/C 제거, items[:1]로 1번만 출력
- OpenAI 새 키 발급, 잔액 $9.12
- GPT-4.1 → GPT-5 전환 (temperature 삭제, max_tokens → max_completion_tokens)
- MU 티커로 1번 프롬프트 테스트 성공
- render_analysis_item()에 상세근거 가독성 필터 추가 (볼드 제거, 마크다운 헤더 제거, 마침표 기준 줄바꿈)
- FMP API 키 설정 완료
- 품질 검증 결과: Forward P/E 오류, 가이던스 미확인, 동종업체 선정 오류, 주가 반응 수치 왜곡
- RULE.md 3개 최신화 작업 시작


# 현재 상태
# (이 섹션만 최신으로 덮어쓰기 가능하다)

- 마지막 작업일: 2026-03-02
- app.py 버전: 1번 프롬프트(밸류에이션 갭 진단) v8 전용으로 축소, items[:1] 출력
- LLM 모델: GPT-5 (secrets.toml model="gpt-5", GPT-5.2 전환 대기 중)
- 배포 상태: Streamlit Cloud 정상 운영 중
- 분석 품질: 4/10점 (목표 7점 이상) — MU 테스트 완료, 방향성은 맞으나 수치 정확도 낮음
- Supabase: 미연결
- .cursor/rules: 도입 완료
- OpenAI 잔액: $9.12
- FMP API: secrets.toml에 키 설정 완료
- Anthropic API: 키 발급 완료, 크레딧 충전 미완료
- repo 상태: public (Claude 읽기용)


# 다음 작업 목록 (우선순위 순)
# (완료 시 ✅ 표시만 하고 삭제하지 마라)

## Phase 1 — 즉시 수정 (UI/코드)
- [x] 1-1. 취소선(~~) 완전 차단 ✅ 후처리 필터 적용됨
- [ ] 1-2. Bull/Bear Case 확률 시각화
- [ ] 1-3. 핵심 재무지표 개선 (그룹핑 + 색상 + 직관 라벨 + 동종비교)
- [ ] 1-4. 기관 보유/내부자 테이블 한글화
- [ ] 1-5. 확신도 A/B/C 시각적 강화 (배지 + 하이라이트)
- [x] 1-6. 상세 근거 글자 크기 통일 ✅ 마크다운 헤더 제거 + 마침표 줄바꿈 적용됨
- [ ] 1-7. 옵션/변동성 해설 직관화
- [ ] 1-8. 최종 의견 확률 강조
- [ ] 1-9. Top 3 인사이트 설명 + 액션 추가

## Phase 2 — LLM 전환 + 프롬프트
- [ ] 2-1. Claude Opus 4.6 전환 (secrets.toml 변경 + anthropic 패키지 추가)
- [ ] 2-2. 프롬프트 미세조정 (리스크 라벨, 전문용어 번역, 취소선 강화금지)
- [ ] 2-3. 뉴스 필터링 기준 수립 (펀더멘탈 영향 있는 뉴스만)

## Phase 3 — 인프라
- [ ] 3-1. Supabase 연동 (리포트 저장/조회)
- [ ] 3-2. UI 추가 개선 (첫 화면 API 설정 코드 제거, 폰트 통일)

## Phase 4 — 장기 로드맵
- [ ] 4-1. 한국 주식 지원
- [ ] 4-2. SEC EDGAR 데이터 연동
- [ ] 4-3. 특허/채용/로비 데이터 연동
- [ ] 4-4. 멀티 티커 비교 분석


# 영구 참고사항

## 비용
- GPT-4.1: 1회 약 $0.10 (145원), $10으로 ~100회
- Claude Opus 4.6: 1회 약 $0.30 (435원), $10으로 ~33회
- FMP API: 무료 티어 (일 250호출)

## 보안
- secrets.toml은 절대 GitHub에 올리지 않는다
- .gitignore에 .streamlit/secrets.toml 반드시 포함
- API 키가 GitHub에 노출되면 즉시 재발급한다

## secrets.toml 구조 (값은 비공개, 2026-03-02 업데이트)
[supabase]
url = "..."
key = "..."

[llm]
api_key = "..."
model = "gpt-5"
provider = "openai"

[fmp]
api_key = "..."

[auth]
password = "..."