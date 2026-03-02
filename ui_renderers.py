# ui_renderers.py — UI 렌더링 함수들 전부
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
from typing import Optional, Dict, List

from utils import fmt_num, safe_pct, safe_float, df_safe


def render_top_summary(fo: Dict):
    """(C) 메인 화면 최상단 — 최종 의견 요약"""
    opinion       = fo.get("의견", "")
    upside        = fo.get("upside_pct", 0) or 0
    downside      = fo.get("downside_pct", 0) or 0
    bull          = fo.get("bull_case", "")
    bear          = fo.get("bear_case", "")
    trigger       = fo.get("trigger_condition", "")
    catalyst      = fo.get("next_catalyst", "")
    catalyst_date = fo.get("next_catalyst_date", "")

    cls = {"매수": "opinion-buy", "보유": "opinion-hold", "매도": "opinion-sell"}.get(opinion, "opinion-hold")
    st.markdown(f'<span class="{cls}">최종 투자 의견: {opinion}</span>', unsafe_allow_html=True)
    st.markdown("")

    c1, c2, c3 = st.columns(3)
    with c1:
        ratio = f"{upside/downside:.1f}x" if downside else "∞"
        st.metric("비대칭 리스크/리워드",
                  f"상방 +{upside}% / 하방 -{downside}%",
                  delta=f"리워드:리스크 = {ratio}",
                  delta_color="normal" if upside >= downside else "inverse")
    with c2:
        st.markdown("**⚡ 의견 변경 트리거**")
        st.markdown(f"> {trigger}")
    with c3:
        st.markdown("**🗓️ 가장 가까운 촉매 이벤트**")
        st.markdown(f"> **{catalyst}**  `{catalyst_date}`")

    st.markdown("")
    col1, col2 = st.columns(2)
    with col1:
        st.success(f"🟢 **Bull Case:** {bull}")
    with col2:
        st.error(f"🔴 **Bear Case:** {bear}")


def render_price_chart(price_df: pd.DataFrame, ticker: str, company_name: str):
    """캔들스틱 주가 차트 + 거래량 + MA선"""
    if price_df is None or price_df.empty:
        st.warning("주가 데이터를 불러올 수 없습니다.")
        return

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.04, row_heights=[0.75, 0.25])

    fig.add_trace(go.Candlestick(
        x=price_df.index,
        open=price_df["Open"], high=price_df["High"],
        low=price_df["Low"],   close=price_df["Close"],
        name=ticker,
        increasing_line_color="#00C851", decreasing_line_color="#FF4444",
    ), row=1, col=1)

    for window, color, dash in [(50, "#FFB300", "dot"), (200, "#7C3AED", "dash")]:
        if len(price_df) >= window:
            ma = price_df["Close"].rolling(window).mean()
            fig.add_trace(go.Scatter(
                x=price_df.index, y=ma, mode="lines",
                name=f"MA{window}",
                line=dict(color=color, width=1.5, dash=dash), opacity=0.85,
            ), row=1, col=1)

    colors = ["#00C851" if c >= o else "#FF4444"
              for c, o in zip(price_df["Close"], price_df["Open"])]
    fig.add_trace(go.Bar(
        x=price_df.index, y=price_df["Volume"],
        name="거래량", marker_color=colors, opacity=0.65,
    ), row=2, col=1)

    fig.update_layout(
        title=dict(text=f"{company_name} ({ticker}) 주가 차트",
                   font=dict(size=16, color="#E8E8E8")),
        height=500, template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(14,14,22,1)",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.02),
        margin=dict(t=50, b=10),
    )
    fig.update_xaxes(gridcolor="#2D2D3F")
    fig.update_yaxes(gridcolor="#2D2D3F")
    st.plotly_chart(fig, use_container_width=True)


def render_financial_cards(info: dict):
    """핵심 재무 지표 2행 카드"""
    st.markdown("#### 핵심 재무 지표")

    def _v(val, prefix="", suffix="", pct=False):
        if val is None:
            return "N/A"
        try:
            v = float(val)
            if np.isnan(v):
                return "N/A"
            if pct:
                return f"{v*100:.1f}%"
            return fmt_num(v, prefix, suffix)
        except Exception:
            return "N/A"

    row1 = [
        ("시가총액",    _v(info.get("marketCap"), "$")),
        ("P/E (TTM)",  safe_float(info.get("trailingPE")) + "x"),
        ("EV/EBITDA",  safe_float(info.get("enterpriseToEbitda")) + "x"),
        ("FCF",        _v(info.get("freeCashflow"), "$")),
        ("부채/자본(D/E)", safe_float(info.get("debtToEquity"))),
        ("ROE",        _v(info.get("returnOnEquity"), pct=True)),
    ]
    row2 = [
        ("Forward P/E",  safe_float(info.get("forwardPE")) + "x"),
        ("영업이익률",     _v(info.get("operatingMargins"), pct=True)),
        ("매출성장(YoY)", _v(info.get("revenueGrowth"), pct=True)),
        ("EPS (TTM)",    f"${info.get('trailingEps','N/A')}"),
        ("배당수익률",     _v(info.get("dividendYield"), pct=True) if info.get("dividendYield") else "무배당"),
        ("Beta",         safe_float(info.get("beta"))),
    ]
    for row in [row1, row2]:
        cols = st.columns(len(row))
        for col, (lbl, val) in zip(cols, row):
            with col:
                st.metric(lbl, val)


def render_institutional_insider(inst_df: pd.DataFrame, major_df: pd.DataFrame,
                                  insider_df: pd.DataFrame, info: dict):
    """기관 보유 현황 + 내부자 거래 (요약 코멘트 포함)"""
    st.markdown("#### 기관 보유 현황 & 내부자 거래")
    c1, c2 = st.columns(2)

    with c1:
        # ── 기관 보유 요약 코멘트 ──────────────────────────────
        inst_pct = info.get("heldPercentInstitutions")
        insider_pct = info.get("heldPercentInsiders")

        if inst_pct is not None:
            try:
                ip = float(inst_pct) * 100
                if ip >= 70:
                    level, color = "높음 (기관 지배적 보유)", "#00C851"
                elif ip >= 40:
                    level, color = "보통", "#FFB300"
                else:
                    level, color = "낮음 (소매 투자자 비중 높음)", "#FF4444"
                st.markdown(
                    f'<div style="background:#1E1E2E;border-radius:8px;padding:10px 14px;margin-bottom:8px;">'
                    f'📊 <b>기관 보유 비중:</b> 전체 주식의 '
                    f'<span style="font-size:1.1rem;font-weight:700;color:{color};">{ip:.1f}%</span>'
                    f' &nbsp;→&nbsp; <span style="color:{color};">{level}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            except Exception:
                pass

        if insider_pct is not None:
            try:
                iip = float(insider_pct) * 100
                st.markdown(
                    f'<div style="background:#1E1E2E;border-radius:8px;padding:8px 14px;margin-bottom:8px;">'
                    f'👤 <b>내부자(임원) 보유:</b> 전체 주식의 '
                    f'<span style="font-weight:700;">{iip:.2f}%</span>'
                    f'{"&nbsp; ✅ 경영진 이해관계 일치" if iip >= 5 else ""}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            except Exception:
                pass

        st.caption("**주요 기관 보유 (Top 10)**")
        if isinstance(inst_df, pd.DataFrame) and not inst_df.empty:
            st.dataframe(inst_df.head(10), use_container_width=True)
        else:
            st.info("기관 보유 데이터 없음")

        # ── 대주주 현황 (한국어 라벨 재구성) ──────────────────
        if isinstance(major_df, pd.DataFrame) and not major_df.empty:
            st.caption("**대주주 구성**")
            label_map = {
                "insidersPercentHeld":      "내부자(임원) 보유 비율",
                "institutionsPercentHeld":  "기관 투자자 보유 비율",
                "institutionsCount":        "보유 기관 수",
                "institutionsFloat":        "유통 주식 중 기관 비율",
            }
            try:
                display_df = major_df.copy()
                # major_holders는 보통 Value/Breakdown 2열 구조
                if "Value" in display_df.columns:
                    display_df.index = [
                        label_map.get(str(i), str(i)) for i in display_df.index
                    ]
                st.dataframe(display_df, use_container_width=True)
            except Exception:
                st.dataframe(major_df, use_container_width=True)

    with c2:
        # ── 내부자 거래 요약 코멘트 ───────────────────────────
        if isinstance(insider_df, pd.DataFrame) and not insider_df.empty:
            try:
                # 최근 3개월 필터
                three_months_ago = pd.Timestamp.now() - pd.DateOffset(months=3)
                df_copy = insider_df.copy()

                # 날짜 컬럼 자동 탐지
                date_col = next(
                    (c for c in df_copy.columns
                     if "date" in c.lower() or "start" in c.lower() or "transaction" in c.lower()),
                    None
                )
                recent = df_copy
                if date_col:
                    try:
                        df_copy[date_col] = pd.to_datetime(df_copy[date_col], errors="coerce")
                        recent = df_copy[df_copy[date_col] >= three_months_ago]
                    except Exception:
                        pass

                # 매수/매도 구분 컬럼 자동 탐지
                trans_col = next(
                    (c for c in recent.columns
                     if "transaction" in c.lower() or "type" in c.lower()
                     or "sale" in c.lower() or "purchase" in c.lower()),
                    None
                )
                buys = sells = 0
                if trans_col:
                    trans_vals = recent[trans_col].astype(str).str.lower()
                    buys  = trans_vals.str.contains("buy|purchase|acqui").sum()
                    sells = trans_vals.str.contains("sell|sale|dispos").sum()

                total_recent = len(recent)
                if buys > sells:
                    summary_txt = "매수 우세 🟢"
                    summary_color = "#00C851"
                elif sells > buys:
                    summary_txt = "매도 우세 🔴"
                    summary_color = "#FF4444"
                else:
                    summary_txt = "균형 / 데이터 부족 🟡"
                    summary_color = "#FFB300"

                st.markdown(
                    f'<div style="background:#1E1E2E;border-radius:8px;padding:10px 14px;margin-bottom:8px;">'
                    f'🏦 <b>최근 3개월 내부자 거래:</b> 총 {total_recent}건'
                    f'&nbsp;|&nbsp; 매수 <b style="color:#00C851">{buys}건</b>'
                    f' vs 매도 <b style="color:#FF4444">{sells}건</b>'
                    f'&nbsp;→&nbsp; <span style="color:{summary_color};font-weight:700;">{summary_txt}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                # 대규모 거래 하이라이트
                shares_col = next(
                    (c for c in insider_df.columns
                     if "share" in c.lower() or "quantity" in c.lower() or "volume" in c.lower()),
                    None
                )
                if shares_col:
                    try:
                        insider_df[shares_col] = pd.to_numeric(insider_df[shares_col], errors="coerce")
                        top_trade = insider_df.nlargest(1, shares_col)
                        if not top_trade.empty:
                            row = top_trade.iloc[0]
                            st.caption(
                                f"💡 최대 단일 거래: {row.get(shares_col, '?'):,.0f}주 "
                                f"({row.get(trans_col, '?') if trans_col else ''} "
                                f"by {str(row.get(list(insider_df.columns)[0], '?'))[:20]})"
                            )
                    except Exception:
                        pass
            except Exception:
                pass

        st.caption("**최근 내부자 거래 (최근 15건)**")
        if isinstance(insider_df, pd.DataFrame) and not insider_df.empty:
            st.dataframe(insider_df.head(15), use_container_width=True)
        else:
            st.info("내부자 거래 데이터 없음")


def render_peer_table(peers: List[Dict], ticker: str, info: dict):
    """동종 기업 밸류에이션 비교 테이블 (색상 하이라이트 + 요약 문장)"""
    if not peers:
        return
    st.markdown("#### 동종 기업 밸류에이션 비교")

    mc   = info.get("marketCap", 0) or 0
    fcf  = info.get("freeCashflow")
    pfcf = (mc / fcf) if (fcf and fcf > 0 and mc) else None

    # ── 원시 숫자값 보존 (하이라이트 계산용) ──────────────────
    def _to_f(v):
        try:
            return float(v) if v is not None else None
        except Exception:
            return None

    target_vals = {
        "P/E":       _to_f(info.get("trailingPE")),
        "Fwd P/E":   _to_f(info.get("forwardPE")),
        "EV/EBITDA": _to_f(info.get("enterpriseToEbitda")),
        "Price/FCF": _to_f(pfcf),
        "매출성장":   _to_f(info.get("revenueGrowth")),
        "영업이익률":  _to_f(info.get("operatingMargins")),
    }

    rows_raw = []  # 원시 숫자
    rows_disp = [] # 표시용 문자열

    def _add(label, name, pe, fpe, ev, pf, rg, om):
        rows_raw.append({
            "티커": label, "기업명": name,
            "P/E": _to_f(pe), "Fwd P/E": _to_f(fpe),
            "EV/EBITDA": _to_f(ev), "Price/FCF": _to_f(pf),
            "매출성장": _to_f(rg), "영업이익률": _to_f(om),
        })
        rows_disp.append({
            "티커": label, "기업명": name,
            "P/E":       safe_float(pe) + "x",
            "Fwd P/E":   safe_float(fpe) + "x",
            "EV/EBITDA": safe_float(ev) + "x",
            "Price/FCF": safe_float(pf) + "x",
            "매출성장":   safe_pct(rg),
            "영업이익률":  safe_pct(om),
        })

    _add(f"★ {ticker} (분석 대상)",
         info.get("shortName", ticker),
         info.get("trailingPE"), info.get("forwardPE"),
         info.get("enterpriseToEbitda"), pfcf,
         info.get("revenueGrowth"), info.get("operatingMargins"))

    for p in peers:
        _add(p["ticker"], p["name"],
             p.get("pe_ratio"), p.get("forward_pe"),
             p.get("ev_ebitda"), p.get("price_to_fcf"),
             p.get("revenue_growth"), p.get("operating_margin"))

    df_disp = pd.DataFrame(rows_disp)
    df_raw  = pd.DataFrame(rows_raw)

    # ── 동종 평균 계산 ────────────────────────────────────────
    peer_rows_raw = df_raw.iloc[1:]  # 분석 대상 제외
    val_cols = ["P/E", "Fwd P/E", "EV/EBITDA", "Price/FCF", "매출성장", "영업이익률"]

    def peer_avg(col):
        vals = [v for v in peer_rows_raw[col] if v is not None]
        return sum(vals) / len(vals) if vals else None

    peer_avgs = {c: peer_avg(c) for c in val_cols}

    # ── 행 스타일링 함수 ──────────────────────────────────────
    # 밸류에이션 지표(P/E, EV/EBITDA, Price/FCF): 분석 대상이 높으면 빨강(고평가), 낮으면 초록(저평가)
    # 성장/이익 지표(매출성장, 영업이익률): 분석 대상이 높으면 초록(좋음), 낮으면 빨강
    VALUATION_COLS = {"P/E", "Fwd P/E", "EV/EBITDA", "Price/FCF"}
    GROWTH_COLS    = {"매출성장", "영업이익률"}

    def style_row(row):
        styles = [""] * len(row)
        if row["티커"].startswith("★"):
            return styles
        tgt_idx = list(df_disp.columns).index
        for ci, col in enumerate(df_disp.columns):
            if col not in val_cols:
                continue
            peer_v = df_raw.iloc[list(df_disp["티커"]).index(row["티커"])][col]
            tgt_v  = target_vals.get(col)
            if peer_v is None or tgt_v is None:
                continue
            if col in VALUATION_COLS:
                # peer가 target보다 낮으면 → peer 입장에서 저평가(초록), 높으면 고평가(빨강)
                color = "#0d3b1f" if peer_v < tgt_v else "#3b0d0d"
            else:
                # peer가 target보다 낮으면 → peer가 열등(빨강), 높으면 우수(초록)
                color = "#3b0d0d" if peer_v < tgt_v else "#0d3b1f"
            styles[ci] = f"background-color:{color}"
        return styles

    try:
        styled = df_disp.style.apply(style_row, axis=1)
        # 분석 대상 행(첫 행) 굵게
        styled = styled.apply(
            lambda x: ["font-weight:700;background-color:#1a1a3e" if i == 0 else ""
                       for i in range(len(x))],
            axis=0
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)
    except Exception:
        st.dataframe(df_disp, use_container_width=True, hide_index=True)

    # ── 한줄 요약 문장 ────────────────────────────────────────
    summary_parts = []
    for col in ["P/E", "EV/EBITDA"]:
        tgt_v = target_vals.get(col)
        avg_v = peer_avgs.get(col)
        if tgt_v and avg_v and avg_v > 0:
            prem = (tgt_v - avg_v) / avg_v * 100
            sign = "프리미엄 🔴" if prem > 0 else "디스카운트 🟢"
            summary_parts.append(f"**{col}** 기준 동종 대비 **{abs(prem):.0f}% {sign}**")
    if summary_parts:
        st.caption("📌 밸류에이션 요약: " + " | ".join(summary_parts)
                   + " (초록=분석 대상보다 저평가, 빨강=고평가)")


def calc_realized_vol(price_df: pd.DataFrame, window: int = 21) -> Optional[float]:
    """연율화 실현 변동성(Realized Volatility) 계산"""
    if price_df is None or price_df.empty or len(price_df) < window + 1:
        return None
    try:
        rets = price_df["Close"].pct_change().dropna()
        return float(rets.tail(window).std() * np.sqrt(252))
    except Exception:
        return None


def render_options_summary(yf_data: Dict):
    """옵션 ATM IV vs 실현 변동성 비교 디스플레이"""
    calls  = df_safe(yf_data.get("options_calls"))
    puts   = df_safe(yf_data.get("options_puts"))
    expiry = yf_data.get("options_expiry")
    info   = yf_data.get("info", {})
    cur    = info.get("currentPrice") or info.get("regularMarketPrice")
    price_df = yf_data.get("price_df")

    if calls.empty or not expiry or not cur:
        return

    try:
        # ATM IV
        atm_iv = None
        if "strike" in calls.columns and "impliedVolatility" in calls.columns:
            atm = calls.iloc[(calls["strike"] - cur).abs().argsort()[:3]]
            iv_val = atm["impliedVolatility"].mean()
            if not np.isnan(iv_val):
                atm_iv = float(iv_val)

        if atm_iv is None:
            return

        # 실현 변동성
        rv_21d = calc_realized_vol(price_df, 21) if isinstance(price_df, pd.DataFrame) else None

        # 만기까지 남은 일수
        try:
            days_to_exp = (pd.Timestamp(expiry) - pd.Timestamp.now()).days
        except Exception:
            days_to_exp = None

        # Implied Move 계산 (±1σ, 만기까지)
        implied_move_pct = None
        if days_to_exp and days_to_exp > 0:
            implied_move_pct = atm_iv * np.sqrt(days_to_exp / 365) * 100

        # IV vs RV 비교
        if rv_21d:
            iv_rv_ratio = atm_iv / rv_21d
            if iv_rv_ratio > 1.2:
                iv_level = "높음 — 옵션이 과대 책정(비쌈)"
                iv_color = "#FF4444"
            elif iv_rv_ratio < 0.8:
                iv_level = "낮음 — 옵션이 과소 책정(저렴)"
                iv_color = "#00C851"
            else:
                iv_level = "보통 — 역사적 수준과 유사"
                iv_color = "#FFB300"
        else:
            iv_rv_ratio = None
            iv_level = "실현 변동성 데이터 부족"
            iv_color = "#888"

        st.markdown("#### 📐 옵션 시장 내재변동성(IV) 분석")
        cols = st.columns(3)

        with cols[0]:
            st.metric("ATM 내재변동성 (IV)", f"{atm_iv*100:.1f}%",
                      help="At-The-Money 옵션 기준 연율화 내재변동성")
        with cols[1]:
            if rv_21d:
                st.metric("21일 실현 변동성 (RV)", f"{rv_21d*100:.1f}%",
                          delta=f"IV/RV = {iv_rv_ratio:.2f}x",
                          delta_color="inverse" if iv_rv_ratio and iv_rv_ratio > 1.2 else "normal")
            else:
                st.metric("21일 실현 변동성 (RV)", "N/A")
        with cols[2]:
            if implied_move_pct:
                st.metric(f"내재 예상 변동폭 (만기: {expiry})",
                          f"±{implied_move_pct:.1f}%",
                          help="옵션 IV 기준, 만기까지 ±1σ 예상 범위")
            else:
                st.metric("내재 예상 변동폭", "N/A")

        # 해설 박스
        explanation = (
            f"**현재 IV({atm_iv*100:.1f}%)는 {iv_level}입니다.**  \n"
        )
        if rv_21d:
            explanation += (
                f"21일 실현 변동성 {rv_21d*100:.1f}% 대비 IV/RV 비율 = **{iv_rv_ratio:.2f}x** — "
            )
            if iv_rv_ratio > 1.2:
                explanation += "옵션 매도 전략이 유리한 환경(변동성 프리미엄 존재).  \n"
            elif iv_rv_ratio < 0.8:
                explanation += "옵션 매수 전략이 유리한 환경(변동성 저평가).  \n"
            else:
                explanation += "특별한 방향성 신호 없음.  \n"
        if implied_move_pct:
            explanation += (
                f"만기 {expiry}까지 시장은 **±{implied_move_pct:.1f}%** 범위의 주가 움직임을 내포하고 있습니다."
            )

        if iv_rv_ratio and iv_rv_ratio > 1.2:
            st.warning(explanation)
        elif iv_rv_ratio and iv_rv_ratio < 0.8:
            st.success(explanation)
        else:
            st.info(explanation)

        # P/C 비율
        if not puts.empty and "openInterest" in calls.columns and "openInterest" in puts.columns:
            call_oi = calls["openInterest"].sum()
            put_oi  = puts["openInterest"].sum()
            if call_oi > 0:
                pc = put_oi / call_oi
                pc_txt = f"P/C Ratio(풋/콜 비율): **{pc:.2f}** "
                if pc > 1.2:
                    pc_txt += "→ 풋 우세, 하락 헤지 수요 높음 ⚠️"
                elif pc < 0.7:
                    pc_txt += "→ 콜 우세, 상승 베팅 수요 높음 📈"
                else:
                    pc_txt += "→ 중립적 포지셔닝"
                st.caption(pc_txt)

    except Exception:
        pass


def render_news(news: List[Dict]):
    st.markdown("#### 최근 뉴스 헤드라인")
    if not news:
        st.info("뉴스 수집 실패")
        return
    for n in news[:12]:
        dt  = (n.get("date") or "")[:20]
        lnk = n.get("link", "")
        ttl = n.get("title", "")
        src = n.get("source", "")
        if lnk:
            st.markdown(f"- [{ttl}]({lnk}) &nbsp; *{src}* &nbsp; `{dt}`")
        else:
            st.markdown(f"- {ttl} &nbsp; *{src}* &nbsp; `{dt}`")


# 항목번호 → 한국어 해설 부제 매핑
ITEM_TITLE_MAP = {
    1:  "밸류에이션 갭 진단 (시장이 뭘 놓치고 있나)",
    2:  "실적/가이던스/경영진 크로스체크 (숫자와 말이 일치하나)",
    3:  "핵심 매출 드라이버 & 선행지표 (다음 분기 이익을 움직이는 변수)",
    4:  "경쟁 해자 & 공급망 (이 회사를 대체할 수 있나)",
    5:  "산업 매크로 & 경쟁구도 (업종 전체가 좋은가, 이 회사만 좋은가)",
    6:  "정책/규제/지정학 (정부가 도울까 막을까)",
    7:  "계약/M&A/사업전환 (판을 바꿀 딜이 있나)",
    8:  "자금흐름: 내부자/기관/옵션 통합 (돈 아는 사람들이 뭘 하나)",
    9:  "자본배분 (번 돈을 어디에 쓰나)",
    10: "리스크 시나리오 & 확률 (최악엔 얼마나 잃나)",
    11: "촉매 캘린더 & 타이밍 (언제 움직이나)",
    12: "최종 비대칭 리스크/리워드 판단 (사야 하나 말아야 하나)",
}


def render_analysis_item(item: Dict):
    """단일 분석 항목 — 한줄 관통 callout + 상세 expander"""
    num        = item.get("항목번호", "?")
    # LLM이 반환한 항목명 대신 ITEM_TITLE_MAP의 정확한 한국어 제목 사용
    name       = ITEM_TITLE_MAP.get(num, item.get("항목명", f"항목 {num}"))
    one_liner  = item.get("한줄관통", "분석 결과 없음").replace("~~", "")
    direction  = item.get("방향성", "불확실")
    detail     = item.get("상세설명", "").replace("~~", "")
    source     = item.get("데이터출처", "N/A")
    confidence = item.get("확신도", "중")

    conf_icon   = {"상": "🟢", "중": "🟡", "하": "🔴"}.get(confidence, "⚪")
    source_icon = {"yfinance": "📊", "뉴스파싱": "📰",
                   "LLM추정(⚠️)": "⚠️", "복합": "🔀"}.get(source, "📌")

    st.markdown(
        f'<div class="item-header"><h4>{num}. {name}</h4></div>',
        unsafe_allow_html=True,
    )

    body = f"**[한줄 관통]** {one_liner}"
    if direction == "호재":
        st.success(f"🟢 {body}")
    elif direction == "악재":
        st.error(f"🔴 {body}")
    elif direction == "불확실":
        st.warning(f"🟡 {body}")
    else:
        st.info(f"🔵 {body}")

    m1, m2 = st.columns(2)
    m1.caption(f"{source_icon} 데이터 출처: **{source}**")
    m2.caption(f"{conf_icon} 확신도: **{confidence}**")

    if detail:
        # ── 상세설명 가독성 필터 ──
        detail = detail.replace("**", "")
        detail = detail.replace("###", "").replace("##", "").replace("# ", "")
        # 주요 구분점에서 강제 줄바꿈
        detail = detail.replace(". 1순위", ".\n\n**1순위**")
        detail = detail.replace(". 2순위", ".\n\n**2순위**")
        detail = detail.replace(". 리스크", ".\n\n**리스크**")
        detail = detail.replace(". 긍정", ".\n\n**긍정**")
        # 마침표+공백 뒤에서 줄바꿈 (문장 단위 분리)
        detail = re.sub(r'\. ([가-힣A-Z\[])', r'.\n\n\1', detail)
        # 빈 줄 과다 방지
        detail = re.sub(r'\n{4,}', '\n\n\n', detail)

        with st.expander("📋 상세 근거 보기"):
            st.markdown(detail)

def render_alpha_matrix(am: Dict):
    """21번: 알파 소스 종합 매트릭스"""
    st.markdown("---")
    st.markdown(
        '<div class="item-header"><h3>21. 알파 소스 종합 매트릭스</h3></div>',
        unsafe_allow_html=True,
    )

    top3 = am.get("top3_insights", [])
    if top3:
        st.markdown("#### ★ 시장과 가장 크게 다른 인사이트 Top 3")
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for ins in sorted(top3, key=lambda x: x.get("순위", 99)):
            r = ins.get("순위", "?")
            n = ins.get("항목번호", "?")
            t = ins.get("인사이트", "")
            st.markdown(
                f'<div class="top-insight">'
                f'{medals.get(r,"📌")} <strong>#{r} [항목 {n}번]</strong><br>{t}'
                f'</div>',
                unsafe_allow_html=True,
            )
        st.markdown("")

    cats = [
        ("🔍 Variant Perception — 시장과 다른 시각", "variant_perception"),
        ("📈 이익 레버리지 시그널",                   "earnings_leverage"),
        ("🗓️ 촉매 & 타임라인",                       "catalyst_timeline"),
        ("⚠️ 테일 리스크 경고",                       "tail_risk"),
    ]
    c1, c2 = st.columns(2)
    for i, (title, key) in enumerate(cats):
        col = c1 if i % 2 == 0 else c2
        items = am.get(key, [])
        with col:
            st.markdown(f"**{title}**")
            if items:
                for it in items:
                    st.markdown(f"- **[{it.get('항목번호','?')}번]** {it.get('한줄관통','')}")
            else:
                st.caption("해당 항목 없음")
            st.markdown("")


def render_final_opinion_box(fo: Dict):
    """22번: 최종 투자 의견 박스"""
    st.markdown("---")
    st.markdown(
        '<div class="item-header"><h3>22. 최종 투자 의견 — 비대칭 리스크/리워드 판단</h3></div>',
        unsafe_allow_html=True,
    )
    opinion  = fo.get("의견", "")
    upside   = fo.get("upside_pct", 0) or 0
    downside = fo.get("downside_pct", 0) or 0
    bull     = fo.get("bull_case", "")
    bear     = fo.get("bear_case", "")
    trigger  = fo.get("trigger_condition", "")
    catalyst = fo.get("next_catalyst", "")
    cat_date = fo.get("next_catalyst_date", "")

    cls = {"매수": "opinion-buy", "보유": "opinion-hold", "매도": "opinion-sell"}.get(opinion, "opinion-hold")

    cl, cr = st.columns([1, 2])
    with cl:
        st.markdown(
            f'<div style="text-align:center;padding:20px 0;">'
            f'<span class="{cls}">{opinion}</span><br><br>'
            f'<span style="font-size:1.4rem;color:#00C851;font-weight:700;">▲ +{upside}%</span>'
            f'&nbsp;&nbsp;vs&nbsp;&nbsp;'
            f'<span style="font-size:1.4rem;color:#FF4444;font-weight:700;">▼ -{downside}%</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with cr:
        st.success(f"🟢 **Bull Case (매수 논거):** {bull}")
        st.error(f"🔴 **Bear Case (리스크 논거):** {bear}")
        st.warning(f"⚡ **의견 변경 트리거:** {trigger}")
        st.info(f"🗓️ **가장 가까운 촉매:** {catalyst}  ({cat_date})")
