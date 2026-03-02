---
description: "코딩 규칙, 금지 패턴, 스타일 가이드 — 모든 대화에서 항상 참조"
alwaysApply: true
---

# ============================================================
# 이 파일의 역할 (에이전트 필독)
# ============================================================
# 이 파일은 "어떻게 코드를 짜야 하는가"를 기록하는 곳이다.
#
# 포함하는 내용:
#   - Python / Streamlit 코딩 규칙
#   - 이 프로젝트 고유의 금지 패턴
#   - 에러 처리 패턴
#   - UI 렌더링 규칙
#   - LLM 프롬프트 작성 규칙
#   - LLM 응답 후처리 규칙
#   - 네이밍 컨벤션
#   - 작업 중 발견된 코딩 교훈 (누적)
#
# [에이전트 수정 규칙]
# - 이 파일을 수정할 때 기존 내용을 절대 삭제하지 마라.
# - 새로운 규칙은 해당 섹션의 맨 아래에 추가하라.
# - 규칙을 추가할 때 발견 날짜와 이유를 한 줄로 적어라.
#   예: "- (2026-02-25) ~~취소선~~ 금지: LLM이 반복 생성하여 UI 깨짐"
# - 코딩과 관련 없는 내용(작업 계획, git 절차 등)은
#   project-context/RULE.md 또는 workflow/RULE.md에 넣어라.
# ============================================================


# Python 일반 규칙

- 타입 힌트를 적극 사용하라: 함수 파라미터와 반환값에 항상 타입 명시
- f-string을 기본 문자열 포맷으로 사용하라
- try-except 사용 시 Exception을 그대로 쓰지 말고 구체적 예외를 쓰되,
  이 프로젝트에서는 yfinance/외부 API 호출 부분에 한해 broad except 허용
- 함수 하나가 100줄을 넘기면 분리를 검토하라
- import는 파일 최상단에 모아두라 (표준 라이브러리 → 서드파티 → 로컬 순)


# Streamlit 규칙

- st.session_state 키 이름은 snake_case로 통일하라
  예: analysis_complete, analysis_result, current_ticker
- st.cache_resource는 Supabase 클라이언트처럼 한 번만 생성하는 객체에만 사용하라
- st.cache_data는 이 프로젝트에서는 사용하지 마라
  (yfinance 데이터는 매번 최신을 가져와야 하므로 캐시하면 안 됨)
- st.rerun()은 분석 완료 후 결과 화면 전환 시에만 사용하라
- st.columns() 사용 시 with 문법을 쓰라
  예: with col1: st.metric(...)


# UI 렌더링 규칙

- HTML을 직접 쓸 때는 반드시 st.markdown(unsafe_allow_html=True) 사용
- CSS 클래스는 app.py 상단의 <style> 블록에 정의된 것만 사용하라
  현재 정의된 클래스:
  - .main-header: 메인 제목
  - .opinion-buy / .opinion-hold / .opinion-sell: 최종 의견 배지
  - .item-header: 분석 항목 제목
  - .top-insight: Top 3 인사이트 카드
  - .section-divider: 구분선
- 새 CSS 클래스가 필요하면 같은 <style> 블록에 추가하라
- 색상 규칙:
  - 긍정/매수/상승: #00C851 (초록)
  - 부정/매도/하락: #FF4444 (빨강)
  - 중립/보유/경고: #FFB300 (주황)
  - 강조/브랜드: #7C3AED (보라)
  - 배경: #1A1A2E, #16213E (어두운 남색 계열)
  - 구분선: #2D2D3F


# 금지 패턴 (절대 사용 금지)

- (2026-02-22) 취소선(~~텍스트~~) 사용 금지
  이유: LLM이 분석 텍스트에 취소선을 반복 생성하여 UI가 깨짐
  조치: LLM 응답 후처리에서 ~~ 를 자동 제거하는 필터 적용됨

- (2026-02-22) 마크다운 헤더(###, ##, #) LLM 응답 내 사용 금지
  이유: 상세 근거 텍스트에 마크다운 헤더가 혼입되면 글자 크기가 제멋대로 됨
  조치: _SYSTEM_PROMPT에서 금지 지시, 후처리 필터 추가 예정

- Streamlit에서 st.write() 사용 금지
  이유: st.markdown()으로 통일하여 HTML 제어 가능하게 유지


# LLM 프롬프트 작성 규칙

- _SYSTEM_PROMPT와 user_prompt는 app.py 내에 문자열 변수로 관리
- 프롬프트에서 JSON 출력을 요구할 때 반드시 구조 예시를 제공하라
- OpenAI 사용 시 response_format={"type": "json_object"} 필수
- Anthropic 사용 시 JSON 파싱은 정규식으로 중괄호 블록 추출
  raw = resp.content[0].text
  match = re.search(r"\{.*\}", raw, re.DOTALL)
- temperature는 0.2로 고정 (일관성 우선)
- max_tokens는 16000으로 설정 (12개 항목 전체 출력에 필요)


# LLM 응답 후처리 규칙

- LLM 응답 JSON 파싱 후, 모든 텍스트 필드에서 아래를 제거하라:
  - 취소선: .replace("~~", "")
  - 마크다운 헤더: ### ## # 로 시작하는 줄의 # 기호 제거 (예정)
- JSON 파싱 실패 시 원본 텍스트 앞 400자를 에러 메시지에 포함하여 디버깅 가능하게
- items 배열이 12개 미만이면 경고 표시 (LLM이 항목을 누락한 경우)


# 에러 처리 패턴

- yfinance 데이터 수집: 각 속성별로 개별 try-except 감싸기
  data["_status"][attr] = "ok" 또는 "fail:{에러메시지}" 형태로 상태 기록
  한 속성 실패가 전체 수집을 중단시키면 안 됨

- 외부 API 호출 (FMP, 뉴스 RSS):
  timeout=10~15 설정 필수
  HTTP 상태코드 체크 필수
  실패 시 빈 데이터 반환 (분석 자체가 중단되면 안 됨)

- LLM API 호출:
  JSON 파싱 실패 → 에러 메시지 + 원본 일부 표시
  API 자체 실패 → st.error() 표시 + None 반환

- UI 렌더링:
  데이터가 None이거나 빈 DataFrame이면 st.info("데이터 없음") 표시
  절대로 에러로 페이지 전체가 죽으면 안 됨


# 숫자 포맷팅 규칙

- 큰 숫자는 fmt_num() 함수 사용 (K/M/B/T 단위 자동 변환)
- 퍼센트는 safe_pct() 함수 사용 (None 안전 처리)
- 소수점은 safe_float() 함수 사용 (기본 2자리)
- 값이 None이거나 NaN이면 항상 "N/A" 반환
- 달러 표시: prefix="$" 사용


# 네이밍 컨벤션

- 함수: snake_case (예: collect_yfinance_data, render_price_chart)
- 변수: snake_case (예: price_df, yf_data, fmp_data)
- 상수: UPPER_SNAKE_CASE (예: ITEM_TITLE_MAP, PEER_MAP, _SYSTEM_PROMPT)
- session_state 키: snake_case (예: analysis_complete, current_ticker)
- CSS 클래스: kebab-case (예: opinion-buy, item-header, top-insight)


# 데이터 구조 규칙

- yfinance 데이터는 Dict[str, Any] 형태로 관리
  필수 키: info, price_df, _status
  DataFrame 속성: income_stmt, balance_sheet, cashflow 등
  없는 데이터는 빈 pd.DataFrame() 으로 대체 (None 아님)

- LLM 분석 결과는 JSON Dict 형태
  필수 키: items (List[Dict]), alpha_matrix (Dict), final_opinion (Dict)
  items 각 항목: 항목번호, 항목명, 한줄관통, 방향성, 상세설명, 데이터출처, 확신도

- 동종 기업 데이터는 List[Dict] 형태
  각 Dict: ticker, name, market_cap, pe_ratio, forward_pe, ev_ebitda 등


# 작업 중 발견된 코딩 교훈 (누적)
# (새로운 교훈 발견 시 여기에 날짜와 함께 추가하라)

- (2026-02-21) yfinance stock.info는 한번 호출하면 캐시됨.
  별도 변수에 저장해서 여러 번 참조해도 API를 반복 호출하지 않음.

- (2026-02-22) yfinance의 일부 속성(earnings_history 등)은 특정 티커에서
  빈 DataFrame을 반환하거나 에러를 내므로, 반드시 개별 try-except로 감싸야 함.

- (2026-02-22) Anthropic API 응답은 JSON만 반환하라고 해도 마크다운 코드블록으로
  감싸는 경우가 있음. re.search(r"\{.*\}", raw, re.DOTALL)로 추출 필수.

- (2026-02-22) Streamlit Cloud에서 requirements.txt에 없는 패키지는
  자동 설치 안 됨. 새 패키지 추가 시 반드시 requirements.txt 업데이트.

- (2026-02-22) .gitignore가 UTF-16 인코딩이면 GitHub이 인식 못함.
  반드시 UTF-8로 저장해야 secrets.toml이 제외됨.
