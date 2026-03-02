# llm_pipeline.py — LLM 관련 전부
import streamlit as st
import pandas as pd
import numpy as np
import json
import re
from typing import Optional, Dict, Any, List

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from utils import fmt_num, safe_pct, safe_float, df_safe


def _line(label: str, val) -> str:
    return f"{label}: {val}"


def prepare_data_context(ticker: str, yf_data: Dict,
                         news: List[Dict], peers: List[Dict],
                         fmp_data: Optional[Dict] = None) -> str:
    """LLM에 주입할 데이터 컨텍스트 문자열 생성"""
    info = yf_data.get("info", {})
    lines: List[str] = []

    def sec(title):
        lines.append("")
        lines.append(f"===== {title} =====")

    # ── 기업 기본 정보 ──────────────────────────────────────────
    sec("기업 기본 정보")
    lines += [
        _line("티커", ticker),
        _line("기업명", info.get("longName") or info.get("shortName") or "N/A"),
        _line("섹터", info.get("sector", "N/A")),
        _line("산업", info.get("industry", "N/A")),
    ]
    summary = (info.get("longBusinessSummary") or "")[:600]
    if summary:
        lines.append(_line("사업 설명", summary))

    # ── 주가 정보 ────────────────────────────────────────────────
    sec("주가 정보 [등급 A — yfinance 직접 수집]")
    cur = info.get("currentPrice") or info.get("regularMarketPrice")
    hi52 = info.get("fiftyTwoWeekHigh")
    lo52 = info.get("fiftyTwoWeekLow")
    lines.append(_line("현재 주가", f"${cur}"))
    if cur and hi52:
        lines.append(_line("52주 최고가", f"${hi52}  (현재 대비 {(cur-hi52)/hi52*100:.1f}%)"))
    if cur and lo52:
        lines.append(_line("52주 최저가", f"${lo52}  (현재 대비 +{(cur-lo52)/lo52*100:.1f}%)"))
    lines += [
        _line("베타", info.get("beta", "N/A")),
        _line("50일 이동평균", f"${info.get('fiftyDayAverage','N/A')}"),
        _line("200일 이동평균", f"${info.get('twoHundredDayAverage','N/A')}"),
    ]
    avol = info.get("averageVolume10days") or info.get("averageVolume")
    if avol:
        lines.append(_line("평균 거래량(10일)", f"{int(avol):,}"))

    # ── 밸류에이션 ──────────────────────────────────────────────
    sec("밸류에이션 지표 [등급 A — yfinance 직접 수집]")
    target_mean = info.get("targetMeanPrice")
    upside = None
    if cur and target_mean:
        upside = (target_mean - cur) / cur * 100
    lines += [
        _line("시가총액", fmt_num(info.get("marketCap"), "$")),
        _line("엔터프라이즈 밸류(EV)", fmt_num(info.get("enterpriseValue"), "$")),
        _line("P/E (TTM)", safe_float(info.get("trailingPE")) + "x"),
        _line("Forward P/E", safe_float(info.get("forwardPE")) + "x"),
        _line("PEG 비율", safe_float(info.get("pegRatio"))),
        _line("EV/EBITDA", safe_float(info.get("enterpriseToEbitda")) + "x"),
        _line("EV/Revenue", safe_float(info.get("enterpriseToRevenue")) + "x"),
        _line("Price/Book", safe_float(info.get("priceToBook")) + "x"),
        _line("Price/Sales(TTM)", safe_float(info.get("priceToSalesTrailing12Months")) + "x"),
        _line("애널리스트 평균 목표가",
              f"${target_mean}  (상승여력 {upside:.1f}%)" if upside is not None else f"${target_mean}"),
        _line("애널리스트 최고/최저 목표가",
              f"${info.get('targetHighPrice','N/A')} / ${info.get('targetLowPrice','N/A')}"),
        _line("추천 의견", info.get("recommendationKey", "N/A")),
        _line("의견 제출 애널리스트 수", info.get("numberOfAnalystOpinions", "N/A")),
    ]

    # ── 수익성·성장 ──────────────────────────────────────────────
    sec("수익성 및 성장 지표 [등급 A — yfinance 직접 수집]")
    lines += [
        _line("총 매출(TTM)", fmt_num(info.get("totalRevenue"), "$")),
        _line("매출 성장률(YoY)", safe_pct(info.get("revenueGrowth"))),
        _line("분기 매출 성장률", safe_pct(info.get("revenueQuarterlyGrowth"))),
        _line("EBITDA", fmt_num(info.get("ebitda"), "$")),
        _line("총마진(Gross Margin)", safe_pct(info.get("grossMargins"))),
        _line("영업이익률(Operating Margin)", safe_pct(info.get("operatingMargins"))),
        _line("순이익률(Net Margin)", safe_pct(info.get("profitMargins"))),
        _line("ROE", safe_pct(info.get("returnOnEquity"))),
        _line("ROA", safe_pct(info.get("returnOnAssets"))),
        _line("EPS(TTM)", f"${info.get('trailingEps','N/A')}"),
        _line("Forward EPS(추정)", f"${info.get('forwardEps','N/A')}"),
        _line("EPS 성장률(YoY)", safe_pct(info.get("earningsGrowth"))),
        _line("분기 EPS 성장률", safe_pct(info.get("earningsQuarterlyGrowth"))),
    ]

    # ── 재무 건전성 ─────────────────────────────────────────────
    sec("재무 건전성 [등급 A — yfinance 직접 수집]")
    td = info.get("totalDebt", 0) or 0
    tc = info.get("totalCash", 0) or 0
    lines += [
        _line("총부채", fmt_num(td, "$")),
        _line("현금 및 현금성자산", fmt_num(tc, "$")),
        _line("순부채(Net Debt)", fmt_num(td - tc, "$")),
        _line("부채비율(D/E)", safe_float(info.get("debtToEquity"))),
        _line("유동비율(Current Ratio)", safe_float(info.get("currentRatio"))),
        _line("잉여현금흐름(FCF)", fmt_num(info.get("freeCashflow"), "$")),
        _line("영업현금흐름", fmt_num(info.get("operatingCashflow"), "$")),
        _line("CAPEX(자본지출)", fmt_num(info.get("capitalExpenditures"), "$")),
        _line("배당 수익률", safe_pct(info.get("dividendYield")) if info.get("dividendYield") else "무배당"),
        _line("주당 배당금", f"${info.get('dividendRate','N/A')}"),
        _line("유통 주식 수", fmt_num(info.get("sharesOutstanding"))),
        _line("내부자 보유 비율", safe_pct(info.get("heldPercentInsiders"))),
        _line("기관 보유 비율", safe_pct(info.get("heldPercentInstitutions"))),
    ]

    # ── 어닝 히스토리 ────────────────────────────────────────────
    eh = df_safe(yf_data.get("earnings_history"))
    if not eh.empty:
        try:
            sec("어닝 서프라이즈 히스토리(최근 8분기) [등급 A]")
            lines.append(eh.tail(8).to_string())
        except Exception:
            pass

    # ── 다음 어닝 날짜 ───────────────────────────────────────────
    ed = df_safe(yf_data.get("earnings_dates"))
    if not ed.empty:
        try:
            future = ed[ed.index > pd.Timestamp.now(tz="UTC")]
            if not future.empty:
                sec("다음 어닝 발표 예정일 [등급 A]")
                lines.append(_line("예정일", future.index[0].strftime("%Y-%m-%d")))
        except Exception:
            pass

    # ── 기관 보유 ────────────────────────────────────────────────
    ih = df_safe(yf_data.get("institutional_holders"))
    if not ih.empty:
        try:
            sec("주요 기관 보유 현황(Top 10) [등급 A]")
            lines.append(ih.head(10).to_string())
        except Exception:
            pass

    # ── 내부자 거래 ──────────────────────────────────────────────
    it = df_safe(yf_data.get("insider_transactions"))
    if not it.empty:
        try:
            sec("최근 내부자 거래(최근 20건) [등급 A]")
            lines.append(it.head(20).to_string())
        except Exception:
            pass

    # ── 옵션 ────────────────────────────────────────────────────
    calls = df_safe(yf_data.get("options_calls"))
    puts  = df_safe(yf_data.get("options_puts"))
    expiry = yf_data.get("options_expiry")
    if not calls.empty and expiry:
        try:
            call_oi = int(calls["openInterest"].sum()) if "openInterest" in calls.columns else "N/A"
            put_oi  = int(puts["openInterest"].sum())  if ("openInterest" in puts.columns and not puts.empty) else "N/A"
            pc_ratio = f"{put_oi/call_oi:.2f}" if (isinstance(call_oi,int) and call_oi > 0 and isinstance(put_oi,int)) else "N/A"
            atm_iv = "N/A"
            if cur and "strike" in calls.columns and "impliedVolatility" in calls.columns:
                atm = calls.iloc[(calls["strike"] - cur).abs().argsort()[:3]]
                iv_val = atm["impliedVolatility"].mean()
                atm_iv = f"{iv_val*100:.1f}%" if not np.isnan(iv_val) else "N/A"
            sec(f"옵션 체인 요약(가장 가까운 만기: {expiry}) [등급 A]")
            lines += [
                _line("콜 옵션 총 오픈인터레스트", f"{call_oi:,}" if isinstance(call_oi,int) else call_oi),
                _line("풋 옵션 총 오픈인터레스트", f"{put_oi:,}" if isinstance(put_oi,int) else put_oi),
                _line("P/C Ratio(풋/콜 비율)", pc_ratio),
                _line("ATM 내재변동성(IV) 추정", atm_iv),
            ]
        except Exception:
            pass

    # ── 동종 기업 비교 ──────────────────────────────────────────
    if peers:
        sec("동종 기업 밸류에이션 비교 [등급 A]")
        lines.append(json.dumps(peers, ensure_ascii=False, indent=2, default=str))
  # ── FMP 어닝콜 트랜스크립트 ──────────────────────────────
    if fmp_data:
        transcript = fmp_data.get("transcript")
        t_quarter = fmp_data.get("transcript_quarter")
        t_year = fmp_data.get("transcript_year")
        surprises = fmp_data.get("earnings_surprises", [])

        if transcript:
            sec(f"어닝콜 트랜스크립트 (FY{t_year} Q{t_quarter}) [등급 A — FMP 직접 수집]")
            lines.append("아래는 가장 최근 어닝콜의 주요 내용입니다 (앞 8000자):")
            lines.append(transcript)

        if surprises:
            sec("어닝 서프라이즈 히스토리 (FMP) [등급 A — FMP 직접 수집]")
            for s in surprises:
                actual = s.get("actualEarningResult", "N/A")
                estimated = s.get("estimatedEarning", "N/A")
                surprise_pct = ""
                try:
                    if actual != "N/A" and estimated != "N/A" and float(estimated) != 0:
                        sp = (float(actual) - float(estimated)) / abs(float(estimated)) * 100
                        surprise_pct = f"  (서프라이즈: {sp:+.1f}%)"
                except Exception:
                    pass
                lines.append(
                    f"  {s.get('date','N/A')}: "
                    f"실제 EPS ${actual} vs 추정 EPS ${estimated}{surprise_pct}"
                )

    # ── 뉴스 헤드라인 ────────────────────────────────────────────
    if news:
        sec("최근 뉴스 헤드라인(최근 20건) [등급 B — 뉴스 파싱]")
        for n in news[:20]:
            dt = (n.get("date") or "")[:25]
            lines.append(f"[{dt}] {n.get('title','')}  |  {n.get('source','')}")
    else:
        sec("뉴스 헤드라인")
        lines.append("수집 실패 — LLM 일반 지식 기반 추정(⚠️ 미확인)")

    return "\n".join(lines)


_SYSTEM_PROMPT = """당신은 월스트리트 탑티어 헤지펀드의 수석 애널리스트이자, 해당 산업에서 10년 이상 경력의 섹터 스페셜리스트입니다.

[당신의 임무]
주어진 yfinance/FMP 실제 데이터 + 당신이 보유한 산업 전문 지식을 결합하여, 1번 항목(밸류에이션 갭 진단)을 기관 투자자 수준으로 분석합니다.

[데이터 출처 구분 — 반드시 준수]
모든 수치·팩트 인용 시 출처를 명시하라:
- [DATA] = yfinance/FMP에서 직접 수집된 수치.
- [LLM지식] = 당신의 학습 데이터 기반. 반드시 이 태그를 붙이고, "~로 추정된다" 형태로 서술하라.
- [추정] = 위 두 가지를 조합한 추론. 반드시 이 태그 + 추론 근거를 한 줄로 밝혀라.

[확신도 등급]
A = 제공 데이터로 직접 확인 가능. B = 데이터+LLM지식 혼합. C = LLM지식·추정이 주.

[포맷 규칙]
취소선(~~), 마크다운 헤더(###, ##, #) 사용 절대 금지. 순수 텍스트와 이모지만 사용.

[출력 규칙]
반드시 순수 JSON만 출력하라. 마크다운 코드블록, 설명 텍스트 절대 불가."""


def run_llm_analysis(ticker: str, company_name: str, data_context: str) -> Optional[Dict]:
    """12단계 LLM 분석 실행 → JSON Dict 반환"""
    try:
        api_key  = st.secrets["llm"]["api_key"]
        model    = st.secrets["llm"].get("model", "gpt-4o")
        provider = st.secrets["llm"].get("provider", "openai")
    except Exception:
        st.error("❌ LLM API 설정 오류: .streamlit/secrets.toml 의 [llm] 섹션을 확인하세요.")
        return None

    user_prompt = f"""
다음 데이터를 바탕으로 {ticker} ({company_name})에 대한 1번 항목(밸류에이션 갭 진단)만 분석하라.

{data_context}

===== 핵심 원칙 (TOP 3) =====

① 이 기업의 주가를 실제로 움직이는 단일 지표 하나를 특정하고, 그것에 집중하라.
② 모든 수치 뒤에 "그래서 이 기업에 무엇을 의미하는가"를 반드시 해석하라.
③ 이 기업에만 해당하는 고유한 분석을 하라. 어떤 기업에나 붙일 수 있는 문장은 쓰지 마라.

===== 분석 지시 =====

이 기업의 주가를 현재 시장에서 실제로 움직이고 있는 핵심 지표를 특정하라. '지표'는 전통적 배수(P/E, EV/EBITDA 등), 매출 성장률, 마진 변화, 가이던스, FCF 수익률 등 무엇이든 포함한다.

[무엇이 '실제로 움직이고 있다'인가]
아래 중 하나 이상의 근거가 있어야 한다:
(a) 직전 2개 분기 이내 실적 발표 후 주가 변동 — 변동폭(%)과 날짜를 가능한 한 구체적으로 제시하라
(b) 같은 기간 뉴스 헤드라인에서 직접 언급
(c) 같은 기간 애널리스트 목표가 또는 투자의견 변경
(d) 같은 기간 임원진(CEO, CFO 등) 직접 발언 — 어닝콜, IR, 공식 SNS, SEC 서한 포함. 제3자가 임원 발언을 해석·요약한 것은 (d)가 아니라 (b) 또는 (c)로 분류하라

2개 분기 이전 사건은 현재 주가의 근거로 사용하지 마라.

[1순위 지표 — 핵심]
주가에 가장 직접적 영향을 미친 지표 하나를 골라라. 왜 이것이 1순위인지 근거를 한 문장으로 밝혀라.

1순위 지표에 대해 아래를 모두 다루어라:
(가) 현재 수치와 비교 기준 (전분기 / 전년 동기 / 가이던스 / 동종 기업 중 최소 2개). 동종 비교 시 기업명과 수치를 함께 쓰라.
(나) 이 수치가 왜 이렇게 변했는가 — 원인 분석
(다) 실제 주가에 어떤 영향을 미쳤는가 — 변동 방향과 폭
(라) 다음 분기에 이 지표가 어떻게 될 가능성이 있는가 — 전망

[2순위 이하 — 보조 역할만]
2순위 이하 지표는 1순위를 설명하는 보조 근거로만 쓰라. "1순위인 X가 이렇게 된 이유 중 하나는 2순위 Z 때문이다"의 구조로, 해당 기업에서 구체적으로 어떤 메커니즘으로 연결되는지 설명하라.

[가이던스 — 정확성 최우선]
가이던스를 언급할 때는 구체적 수치(매출 범위, EPS 범위, 성장률 등)를 포함하라. 정확한 수치를 확신할 수 없으면 추측하지 말고 "가이던스 수치 미확인"으로 명시하라. 틀린 수치보다 "미확인"이 낫다. 가이던스 수치를 제시하지 못하면 확신도를 1단계 하향하라.

[긍정과 리스크]
긍정면과 리스크면은 서로 다른 데이터 포인트에서 도출하라. 같은 사실의 앞뒤 뒤집기는 분석이 아니다. 리스크는 이 기업에 고유한 것을 포함하라. "금리 인상", "경기 침체" 같은 거시 리스크만으로는 불충분하다 — 거시를 언급하려면 이 기업에 미치는 구체적 경로를 밝혀라.

데이터가 한 방향을 압도적으로 지지하면 솔직하게 반영하라. 균형을 맞추려고 억지 반대 의견을 만들지 마라. 대신 반대 측면이 약한 이유를 한 문장으로 설명하라.

[출처 표기]
모든 수치에 [DATA] 또는 [LLM지식] 태그를 붙여라. [DATA]는 제공된 yfinance/FMP/뉴스 데이터에서 직접 추출한 것, [LLM지식]은 LLM 학습 데이터에서 가져온 것이다. [LLM지식]으로 표기한 내용은 확정적으로 서술하지 말고 "~로 추정된다", "~한 것으로 알려져 있다" 형태를 쓰라. 애널리스트나 뉴스를 인용할 때는 가능한 한 구체적 출처(이름, 헤드라인, 목표가)를 제시하라.

[한줄관통]
한줄관통에는 이 기업 고유의 수치 1개 이상과 방향성 판단을 담아라.

[방향성과 확신도]
방향성 '중립'을 선택하면 긍정과 부정이 어떻게 상쇄되는지 구체적으로 설명하라. 확신도는 A(제공 데이터로 직접 확인 가능), B(데이터+LLM지식 혼합), C(LLM지식·추정이 주)로 구분하고 이유를 한 문장으로 적어라.

[우선순위 원칙]
정확성 > 완전성. 확실하지 않은 수치를 만들어내느니 "미확인"으로 표기하고 확신도를 낮추는 것이 이 분석에서 더 가치 있다.

===== 핵심 원칙 재확인 (TOP 3) =====

① 이 기업의 주가를 실제로 움직이는 단일 지표 하나를 특정하고, 그것에 집중하라.
② 모든 수치 뒤에 "그래서 이 기업에 무엇을 의미하는가"를 반드시 해석하라.
③ 이 기업에만 해당하는 고유한 분석을 하라. 어떤 기업에나 붙일 수 있는 문장은 쓰지 마라.

반드시 아래 JSON 구조로만 응답하라 (JSON 외 텍스트 절대 불가):
{{{{
  "items": [
    {{{{
      "항목번호": 1,
      "항목명": "밸류에이션 갭 진단",
      "한줄관통": "구체적 수치 포함 핵심 인사이트 한 줄",
      "방향성": "호재 또는 악재 또는 중립",
      "상세설명": "충분한 상세 분석 내용...",
      "데이터출처": "[DATA]/[LLM지식]/[추정]",
      "확신도": "A 또는 B 또는 C"
    }}}}
  ]
}}}}
"""


    raw = ""
    try:
        if provider == "openai":
            if not OPENAI_AVAILABLE:
                st.error("openai 패키지 미설치: pip install openai")
                return None
            client = OpenAI(api_key=api_key)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=16000,
            )
            raw = resp.choices[0].message.content

        elif provider == "anthropic":
            if not ANTHROPIC_AVAILABLE:
                st.error("anthropic 패키지 미설치: pip install anthropic")
                return None
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model=model,
                max_tokens=16000,
                system=_SYSTEM_PROMPT + "\n\n[중요] 반드시 순수 JSON만 출력하라. 마크다운 블록 절대 불가.",
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = resp.content[0].text
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                raw = match.group()

        else:
            st.error("지원하지 않는 LLM 제공자입니다. 'openai' 또는 'anthropic'을 설정하세요.")
            return None

        return json.loads(raw)

    except json.JSONDecodeError as e:
        st.error(f"LLM 응답 JSON 파싱 실패: {e}\n원본(일부): {raw[:400]}")
        return None
    except Exception as e:
        st.error(f"LLM API 호출 실패: {e}")
        return None
