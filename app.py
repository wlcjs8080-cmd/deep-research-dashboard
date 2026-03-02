"""
================================================================================
기관용 딥 리서치 투자 분석 대시보드 (Institutional Deep Research Dashboard)
================================================================================

[STEP 1] Supabase 테이블 생성 SQL — Supabase 대시보드 > SQL Editor 에서 실행
--------------------------------------------------------------------------------
CREATE TABLE analysis_reports (
    id              BIGSERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    analysis_date   DATE NOT NULL,
    final_opinion   TEXT,
    upside_pct      NUMERIC,
    downside_pct    NUMERIC,
    trigger_condition TEXT,
    full_analysis_json  JSONB,
    raw_data_snapshot   JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_reports_ticker ON analysis_reports(ticker);
CREATE INDEX idx_reports_date   ON analysis_reports(analysis_date DESC);
--------------------------------------------------------------------------------

[STEP 2] .streamlit/secrets.toml 설정 예시
--------------------------------------------------------------------------------
[supabase]
url = "https://your-project-id.supabase.co"
key = "your-anon-key-here"

[llm]
api_key  = "your-openai-or-anthropic-api-key"
model    = "gpt-4o"        # OpenAI: "gpt-4o" / Anthropic: "claude-opus-4-5"
provider = "openai"        # "openai" 또는 "anthropic"
--------------------------------------------------------------------------------
"""

# ============================================================
# IMPORTS
# ============================================================
import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import json
import re
import time
import datetime
from datetime import date
from typing import Optional, Dict, Any, List, Tuple

try:
    from supabase import create_client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

from utils import df_safe, serialize_obj
from data_collectors import collect_yfinance_data, get_peer_data, _fmp_key, collect_fmp_earnings_transcript, collect_news
from llm_pipeline import prepare_data_context, run_llm_analysis
from ui_renderers import (
    render_top_summary, render_price_chart, render_financial_cards,
    render_institutional_insider, render_peer_table,
    render_options_summary, render_news,
    render_analysis_item, render_alpha_matrix, render_final_opinion_box,
)

# ============================================================
# PAGE CONFIG & GLOBAL CSS
# ============================================================
st.set_page_config(
    page_title="딥 리서치 투자 분석",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main-header { font-size:2.2rem; font-weight:900; color:#E8E8E8; margin-bottom:4px; }
    .opinion-buy  { background:linear-gradient(135deg,#00C851,#007E33); color:#fff;
                    padding:10px 28px; border-radius:50px; font-size:1.6rem; font-weight:900;
                    display:inline-block; box-shadow:0 4px 15px rgba(0,200,81,.4); letter-spacing:2px; }
    .opinion-hold { background:linear-gradient(135deg,#FFB300,#FF6D00); color:#fff;
                    padding:10px 28px; border-radius:50px; font-size:1.6rem; font-weight:900;
                    display:inline-block; box-shadow:0 4px 15px rgba(255,179,0,.4); letter-spacing:2px; }
    .opinion-sell { background:linear-gradient(135deg,#FF4444,#CC0000); color:#fff;
                    padding:10px 28px; border-radius:50px; font-size:1.6rem; font-weight:900;
                    display:inline-block; box-shadow:0 4px 15px rgba(255,68,68,.4); letter-spacing:2px; }
    .item-header  { border-left:4px solid #7C3AED; padding-left:12px; margin:20px 0 8px 0; }
    .top-insight  { background:linear-gradient(135deg,#1A1A2E,#16213E); border:1px solid #7C3AED;
                    border-radius:12px; padding:14px 16px; margin:6px 0; }
    .section-divider { border:none; border-top:1px solid #2D2D3F; margin:28px 0; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# SUPABASE FUNCTIONS
# ============================================================

@st.cache_resource
def _get_supabase():
    if not SUPABASE_AVAILABLE:
        return None
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception:
        return None


def save_to_supabase(ticker: str, result: Dict, yf_data: Dict) -> Tuple[bool, str]:
    client = _get_supabase()
    if not client:
        return False, "Supabase 미설정 또는 연결 실패"
    try:
        info = yf_data.get("info", {})
        fo = result.get("final_opinion", {})
        safe_info = {k: v for k, v in info.items() if isinstance(v, (str, int, float, bool, type(None)))}
        record = {
            "ticker":            ticker.upper(),
            "analysis_date":     date.today().isoformat(),
            "final_opinion":     fo.get("의견", ""),
            "upside_pct":        float(fo.get("upside_pct", 0) or 0),
            "downside_pct":      float(fo.get("downside_pct", 0) or 0),
            "trigger_condition": str(fo.get("trigger_condition", "")),
            "full_analysis_json": result,
            "raw_data_snapshot":  {"info": safe_info},
        }
        res = client.table("analysis_reports").insert(record).execute()
        rid = res.data[0].get("id", "N/A") if res.data else "N/A"
        return True, f"저장 완료 (ID: {rid})"
    except Exception as e:
        return False, str(e)


def load_past_reports(ticker: Optional[str] = None, limit: int = 20) -> List[Dict]:
    client = _get_supabase()
    if not client:
        return []
    try:
        q = (client.table("analysis_reports")
             .select("id,ticker,analysis_date,final_opinion,upside_pct,downside_pct,created_at")
             .order("created_at", desc=True))
        if ticker:
            q = q.eq("ticker", ticker.upper())
        return (q.limit(limit).execute()).data or []
    except Exception:
        return []


def load_full_report(report_id: int) -> Optional[Dict]:
    client = _get_supabase()
    if not client:
        return None
    try:
        return (client.table("analysis_reports").select("*").eq("id", report_id).single().execute()).data
    except Exception:
        return None


# ============================================================
# MAIN APP
# ============================================================

def _init_session():
    defaults = {
        "analysis_complete": False,
        "analysis_result":   None,
        "yf_data":           None,
        "news_data":         [],
        "peer_data":         [],
        "fmp_data":          {},

        "current_ticker":    "",
        "company_name":      "",
        "period_label":      "1년 (기본)",
        "saved_to_db":       False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def main():
    _init_session()

    # ── 사이드바 ───────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## 📊 딥 리서치 대시보드")
        st.markdown("---")

        tab_new, tab_hist = st.tabs(["🔍 새 분석", "📁 과거 기록"])

        with tab_new:
            ticker_input = st.text_input(
                "티커 입력",
                placeholder="예: AAPL, MSFT, NVDA",
                help="미국 주식 티커 심볼 (대소문자 무관)",
            ).strip().upper()

            PERIOD_MAP = {
                "3개월": "3mo", "6개월": "6mo",
                "1년 (기본)": "1y", "2년": "2y", "5년": "5y",
            }
            period_label = st.selectbox("분석 기간", list(PERIOD_MAP.keys()), index=2)
            period = PERIOD_MAP[period_label]

            analyze_btn = st.button(
                "🚀 딥 리서치 분석 시작",
                use_container_width=True,
                type="primary",
                disabled=not bool(ticker_input),
            )

            st.markdown("---")
            st.markdown("**⚙️ 시스템 상태**")
            sb_ok = _get_supabase() is not None
            st.markdown(f"Supabase: {'✅ 연결됨' if sb_ok else '⚠️ 미설정'}")
            try:
                prov  = st.secrets["llm"].get("provider", "N/A")
                mdl   = st.secrets["llm"].get("model", "N/A")
                st.markdown(f"LLM: ✅ {prov} / {mdl}")
                fmp_ok = _fmp_key() is not None
                st.markdown(f"FMP: {'✅ 연결됨' if fmp_ok else '⚠️ 미설정'}")

            except Exception:
                st.markdown("LLM: ⚠️ API 키 미설정")

        with tab_hist:
            st.markdown("**과거 분석 기록 검색**")
            hist_ticker = st.text_input(
                "티커 필터 (선택)", placeholder="예: AAPL", key="hist_filter"
            ).strip().upper() or None
            load_btn = st.button("📋 기록 불러오기", use_container_width=True)

            if load_btn:
                with st.spinner("기록 조회 중..."):
                    rpts = load_past_reports(ticker=hist_ticker, limit=20)
                if rpts:
                    st.markdown(f"**{len(rpts)}건 발견**")
                    for r in rpts:
                        emoji = {"매수": "🟢", "보유": "🟡", "매도": "🔴"}.get(
                            r.get("final_opinion", ""), "⚪")
                        lbl = (f"{emoji} {r['ticker']} | {r['analysis_date']} "
                               f"| {r.get('final_opinion','N/A')}")
                        if st.button(lbl, key=f"load_{r['id']}", use_container_width=True):
                            with st.spinner("리포트 불러오는 중..."):
                                full = load_full_report(r["id"])
                            if full and full.get("full_analysis_json"):
                                st.session_state.analysis_result   = full["full_analysis_json"]
                                st.session_state.current_ticker    = full["ticker"]
                                st.session_state.company_name      = full["ticker"]
                                st.session_state.analysis_complete = True
                                st.session_state.saved_to_db       = True
                                st.session_state.yf_data = {
                                    "info": (full.get("raw_data_snapshot") or {}).get("info", {}),
                                    "price_df": pd.DataFrame(),
                                }
                                st.session_state.news_data = []
                                st.session_state.peer_data = []
                                st.rerun()
                else:
                    st.info("저장된 기록이 없습니다.")

    # ── 분석 실행 ──────────────────────────────────────────────
    if analyze_btn and ticker_input:
                # ── 티커 유효성 검증 (강화) ──────────────────────────
        # 1) 영문+숫자+점만 허용 (한글, 특수문자 차단)
        if not re.match(r'^[A-Z0-9.\-]{1,10}$', ticker_input):
            st.error(f"❌ '{ticker_input}'은(는) 유효하지 않은 티커입니다. 영문 티커를 입력하세요. (예: AAPL, MSFT, NVDA)")
            st.stop()

        # 2) yfinance에서 실제 데이터 존재 여부 확인
        try:
            _test = yf.Ticker(ticker_input)
            _test_info = _test.info
            _test_price = _test_info.get("currentPrice") or _test_info.get("regularMarketPrice")
            _test_mc = _test_info.get("marketCap")
            _test_name = _test_info.get("shortName") or _test_info.get("longName")
            if not _test_price and not _test_mc:
                st.error(f"❌ '{ticker_input}'에 대한 시장 데이터가 없습니다. 미국 주식 티커를 입력하세요. (예: AAPL, MSFT, NVDA)")
                st.stop()
        except Exception:
            st.error(f"❌ '{ticker_input}'을(를) 찾을 수 없습니다. 티커를 확인해주세요.")

        # 상태 초기화
        for k in ["analysis_complete", "analysis_result", "saved_to_db"]:
            st.session_state[k] = False if k != "analysis_result" else None
        st.session_state.current_ticker = ticker_input
        st.session_state.period_label   = period_label

        prog = st.progress(0)
        stat = st.empty()

        stat.markdown("⏳ **[1/4] yfinance 데이터 수집 중...**")
        yf_data = collect_yfinance_data(ticker_input, period)
        st.session_state.yf_data = yf_data
        prog.progress(25)
        name = (yf_data.get("info", {}).get("longName") or
                yf_data.get("info", {}).get("shortName") or ticker_input)
        st.session_state.company_name = name

        stat.markdown("⏳ **[2/5] 뉴스 헤드라인 파싱 중...**")
        news = collect_news(ticker_input)
        st.session_state.news_data = news
        prog.progress(30)

        stat.markdown("⏳ **[3/5] 동종 기업 데이터 수집 중...**")
        peers = get_peer_data(ticker_input, yf_data)
        st.session_state.peer_data = peers
        prog.progress(45)

        stat.markdown("⏳ **[4/5] FMP 어닝콜 트랜스크립트 수집 중...**")
        fmp_data = collect_fmp_earnings_transcript(ticker_input)
        st.session_state.fmp_data = fmp_data
        prog.progress(55)

        stat.markdown("⏳ **[5/5] LLM 12단계 심층 분석 중... (60~120초 소요)**")
        ctx    = prepare_data_context(ticker_input, yf_data, news, peers, fmp_data)
        result = run_llm_analysis(ticker_input, name, ctx)
        prog.progress(100)

        if result:
            st.session_state.analysis_result   = result
            st.session_state.analysis_complete = True
            stat.markdown("✅ **분석 완료!**")
            time.sleep(0.4)
            st.rerun()
        else:
            stat.markdown("❌ **분석 실패. 위 오류 메시지를 확인하세요.**")

    # ── 결과 렌더링 ────────────────────────────────────────────
    if st.session_state.analysis_complete and st.session_state.analysis_result:
        res         = st.session_state.analysis_result
        ticker      = st.session_state.current_ticker
        cname       = st.session_state.company_name
        yf_data     = st.session_state.yf_data or {}
        news        = st.session_state.news_data or []
        peers       = st.session_state.peer_data or []
        fmp_data    = st.session_state.get("fmp_data", {})

        info        = yf_data.get("info", {})
        items       = res.get("items", [])
        alpha_mat   = res.get("alpha_matrix", {})
        final_op    = res.get("final_opinion", {})

        # ── 메인 헤더 + 저장 버튼 ──────────────────────────────
        h_col, s_col = st.columns([5, 1])
        with h_col:
            st.markdown(f'<h1 class="main-header">📊 {cname} ({ticker})</h1>',
                        unsafe_allow_html=True)
            st.caption(f"분석 일시: {date.today().strftime('%Y년 %m월 %d일')}  |  "
                       f"분석 기간: {st.session_state.period_label}")
        with s_col:
            if not st.session_state.saved_to_db:
                if st.button("☁️ 클라우드에\n리포트 저장", use_container_width=True):
                    with st.spinner("Supabase 저장 중..."):
                        ok, msg = save_to_supabase(ticker, res, yf_data)
                    if ok:
                        st.success(f"✅ {msg}")
                        st.session_state.saved_to_db = True
                    else:
                        st.warning(f"⚠️ 저장 실패: {msg}")
                        json_bytes = json.dumps(
                            res, ensure_ascii=False, indent=2, default=str
                        ).encode("utf-8")
                        st.download_button(
                            "💾 로컬 JSON 다운로드",
                            data=json_bytes,
                            file_name=f"{ticker}_{date.today()}_analysis.json",
                            mime="application/json",
                        )
            else:
                st.success("✅ 저장됨")
                json_bytes = json.dumps(
                    res, ensure_ascii=False, indent=2, default=str
                ).encode("utf-8")
                st.download_button(
                    "💾 JSON 다운로드",
                    data=json_bytes,
                    file_name=f"{ticker}_{date.today()}_analysis.json",
                    mime="application/json",
                    use_container_width=True,
                )

        st.markdown("---")

        # ── (C) 최상단: 최종 투자 의견 요약 ────────────────────
        if final_op:
            render_top_summary(final_op)

        st.markdown("---")

        # ── (D) 데이터 시각화 ──────────────────────────────────
        st.markdown("## 📈 시장 데이터")
        price_df = yf_data.get("price_df")
        if isinstance(price_df, pd.DataFrame) and not price_df.empty:
            render_price_chart(price_df, ticker, cname)

        render_financial_cards(info)
        st.markdown("")

        render_institutional_insider(
            df_safe(yf_data.get("institutional_holders")),
            df_safe(yf_data.get("major_holders")),
            df_safe(yf_data.get("insider_transactions")),
            info,
        )

        if peers:
            render_peer_table(peers, ticker, info)

        render_options_summary(yf_data)

        render_news(news)

        st.markdown("---")

        # ── (E) 1번 분석 항목만 표시 (테스트 모드) ──────────────
        st.markdown("## 🧠 딥 리서치 분석 — 1번 항목 테스트")

        for it in items[:1]:
            render_analysis_item(it)


        st.markdown("---")
        st.caption(
            "⚠️ 본 분석은 투자 참고 자료이며, 실제 투자 결정에 대한 책임은 "
            "전적으로 투자자 본인에게 있습니다. 과거 수익률이 미래를 보장하지 않습니다."
        )

    elif not st.session_state.analysis_complete:
        # ── 초기 안내 화면 ────────────────────────────────────
        st.markdown("# 📊 기관용 딥 리서치 투자 분석 대시보드")
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        c1.info("**🎯 핵심 철학 1**\n\n정보 피로도 제거: '한줄 관통'을 강제하는 UI와 백엔드 로직")
        c2.info("**🔍 핵심 철학 2**\n\nVariant Perception(시장 기대치와 실제의 괴리)으로 Alpha(초과수익) 근거 제공")
        c3.info("**⚡ 12단계 분석**\n\nyfinance + 뉴스 파싱 + LLM으로 기관급 딥 리서치 수행")
        st.markdown("---")
        st.markdown("### 시작하기")
        st.markdown("1. 좌측 사이드바에서 **티커**를 입력하세요 (예: AAPL, MSFT, NVDA, TSLA)")
        st.markdown("2. **분석 기간**을 설정하세요 (기본값: 1년)")
        st.markdown("3. **🚀 딥 리서치 분석 시작** 버튼을 클릭하세요")
        st.markdown("4. 분석 완료 후 **☁️ 클라우드에 리포트 저장** 으로 영구 보관하거나, JSON으로 다운로드 가능합니다")
        st.markdown("---")
        st.markdown("""
**필요한 API 키 설정** (`.streamlit/secrets.toml`):
```toml
[supabase]
url = "https://your-project.supabase.co"
key = "your-anon-key"

[llm]
api_key  = "your-openai-or-anthropic-api-key"
model    = "gpt-4o"
provider = "openai"
```
        """)


if __name__ == "__main__":
    main()
