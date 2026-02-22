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
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from bs4 import BeautifulSoup
import json
import re
import time
import datetime
from datetime import date
from typing import Optional, Dict, Any, List, Tuple

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

try:
    from supabase import create_client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

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
# HELPER UTILITIES
# ============================================================

def fmt_num(val, prefix="", suffix="", decimals=2) -> str:
    """숫자를 K/M/B/T 단위로 포맷팅"""
    if val is None:
        return "N/A"
    try:
        v = float(val)
        if np.isnan(v):
            return "N/A"
        if abs(v) >= 1e12:
            return f"{prefix}{v/1e12:.{decimals}f}T{suffix}"
        if abs(v) >= 1e9:
            return f"{prefix}{v/1e9:.{decimals}f}B{suffix}"
        if abs(v) >= 1e6:
            return f"{prefix}{v/1e6:.{decimals}f}M{suffix}"
        return f"{prefix}{v:.{decimals}f}{suffix}"
    except Exception:
        return "N/A"


def safe_pct(val) -> str:
    try:
        return f"{float(val)*100:.1f}%"
    except Exception:
        return "N/A"


def safe_float(val, decimals=2) -> str:
    try:
        return f"{float(val):.{decimals}f}"
    except Exception:
        return "N/A"


def df_safe(obj) -> pd.DataFrame:
    """None이면 빈 DataFrame 반환"""
    if obj is None:
        return pd.DataFrame()
    if isinstance(obj, pd.DataFrame):
        return obj
    return pd.DataFrame()


def serialize_obj(obj):
    """JSON 직렬화 가능하도록 변환"""
    if isinstance(obj, (pd.Timestamp, datetime.datetime, datetime.date)):
        return str(obj)
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {str(k): serialize_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [serialize_obj(i) for i in obj]
    return obj


# ============================================================
# DATA COLLECTION — yfinance
# ============================================================

def collect_yfinance_data(ticker: str, period: str = "1y") -> Dict[str, Any]:
    """yfinance 전체 데이터 수집 파이프라인 (에러 격리 구조)"""
    data: Dict[str, Any] = {"_status": {}}

    try:
        stock = yf.Ticker(ticker)

        # 기본 info
        try:
            data["info"] = stock.info
            data["_status"]["info"] = "ok"
        except Exception as e:
            data["info"] = {}
            data["_status"]["info"] = f"fail:{e}"

        # 주가 히스토리 (DataFrame 원본 보존)
        try:
            hist = stock.history(period=period)
            data["price_df"] = hist if not hist.empty else pd.DataFrame()
            data["_status"]["price"] = "ok" if not hist.empty else "empty"
        except Exception as e:
            data["price_df"] = pd.DataFrame()
            data["_status"]["price"] = f"fail:{e}"

        # 재무제표 3종
        for attr in ["income_stmt", "balance_sheet", "cashflow",
                     "quarterly_income_stmt", "quarterly_balance_sheet", "quarterly_cashflow"]:
            try:
                df = getattr(stock, attr)
                data[attr] = df if (df is not None and not df.empty) else pd.DataFrame()
                data["_status"][attr] = "ok" if (df is not None and not df.empty) else "empty"
            except Exception as e:
                data[attr] = pd.DataFrame()
                data["_status"][attr] = f"fail:{e}"

        # 어닝
        for attr in ["earnings_history", "earnings_dates"]:
            try:
                df = getattr(stock, attr)
                data[attr] = df if (df is not None and not df.empty) else pd.DataFrame()
                data["_status"][attr] = "ok" if (df is not None and not df.empty) else "empty"
            except Exception as e:
                data[attr] = pd.DataFrame()
                data["_status"][attr] = f"fail:{e}"

        # 기관/내부자
        for attr in ["institutional_holders", "major_holders", "insider_transactions"]:
            try:
                df = getattr(stock, attr)
                data[attr] = df if (df is not None and not df.empty) else pd.DataFrame()
                data["_status"][attr] = "ok" if (df is not None and not df.empty) else "empty"
            except Exception as e:
                data[attr] = pd.DataFrame()
                data["_status"][attr] = f"fail:{e}"

        # 애널리스트
        try:
            data["recommendations"] = df_safe(stock.recommendations)
        except Exception:
            data["recommendations"] = pd.DataFrame()

        try:
            apt = stock.analyst_price_targets
            data["analyst_price_targets"] = apt if apt is not None else {}
        except Exception:
            data["analyst_price_targets"] = {}

        # 옵션 체인
        try:
            exps = stock.options
            if exps:
                chain = stock.option_chain(exps[0])
                data["options_calls"] = chain.calls if not chain.calls.empty else pd.DataFrame()
                data["options_puts"] = chain.puts if not chain.puts.empty else pd.DataFrame()
                data["options_expiry"] = exps[0]
                data["_status"]["options"] = "ok"
            else:
                data["options_calls"] = pd.DataFrame()
                data["options_puts"] = pd.DataFrame()
                data["options_expiry"] = None
                data["_status"]["options"] = "empty"
        except Exception as e:
            data["options_calls"] = pd.DataFrame()
            data["options_puts"] = pd.DataFrame()
            data["options_expiry"] = None
            data["_status"]["options"] = f"fail:{e}"

    except Exception as e:
        data["_fatal"] = str(e)

    return data


def get_peer_data(ticker: str, yf_data: Dict) -> List[Dict]:
    """섹터 기반 동종 기업 최대 3곳 데이터 수집"""
    sector = yf_data.get("info", {}).get("sector", "")

    PEER_MAP = {
        "Technology":             ["MSFT","GOOGL","META","AMZN","NVDA","AMD","ORCL","CRM","ADBE","INTC"],
        "Healthcare":             ["JNJ","PFE","ABBV","MRK","LLY","BMY","AMGN","GILD","BIIB"],
        "Financial Services":     ["JPM","BAC","WFC","GS","MS","C","BLK","AXP","SCHW"],
        "Consumer Cyclical":      ["AMZN","HD","NKE","MCD","SBUX","TGT","BKNG","ABNB"],
        "Communication Services": ["META","GOOGL","NFLX","DIS","SNAP","T","VZ","PINS"],
        "Energy":                 ["XOM","CVX","COP","SLB","EOG","OXY","MPC","PSX"],
        "Industrials":            ["HON","MMM","GE","CAT","BA","RTX","LMT","UPS","FDX"],
        "Consumer Defensive":     ["WMT","PG","KO","PEP","COST","CL","GIS","KHC"],
        "Basic Materials":        ["LIN","APD","FCX","NEM","DOW","DD","ALB","CF"],
        "Real Estate":            ["AMT","PLD","CCI","EQIX","PSA","SPG","WELL"],
        "Utilities":              ["NEE","DUK","AEP","SO","EXC","SRE","D"],
    }

    candidates = [c for c in PEER_MAP.get(sector, []) if c.upper() != ticker.upper()][:6]
    peers = []
    for pt in candidates[:3]:
        try:
            pi = yf.Ticker(pt).info
            mc = pi.get("marketCap", 0)
            fcf = pi.get("freeCashflow")
            pfcf = (mc / fcf) if (fcf and fcf > 0 and mc) else None
            peers.append({
                "ticker":           pt,
                "name":             pi.get("shortName", pt),
                "market_cap":       mc,
                "pe_ratio":         pi.get("trailingPE"),
                "forward_pe":       pi.get("forwardPE"),
                "ev_ebitda":        pi.get("enterpriseToEbitda"),
                "price_to_fcf":     pfcf,
                "revenue_growth":   pi.get("revenueGrowth"),
                "operating_margin": pi.get("operatingMargins"),
            })
        except Exception:
            continue
    return peers


# ============================================================
# DATA COLLECTION — News (BeautifulSoup)
# ============================================================
# ============================================================
# DATA COLLECTION — FMP (Financial Modeling Prep)
# ============================================================

def _fmp_key() -> Optional[str]:
    """secrets.toml에서 FMP API 키 로드"""
    try:
        return st.secrets["fmp"]["api_key"]
    except Exception:
        return None


def collect_fmp_earnings_transcript(ticker: str) -> Dict[str, Any]:
    """FMP 어닝콜 트랜스크립트 + 어닝 서프라이즈 수집"""
    result: Dict[str, Any] = {
        "transcript": None,
        "transcript_quarter": None,
        "transcript_year": None,
        "earnings_surprises": [],
        "_status": {},
    }

    api_key = _fmp_key()
    if not api_key:
        result["_status"]["fmp"] = "no_api_key"
        return result

    base = "https://financialmodelingprep.com/stable"
    headers = {"User-Agent": "Mozilla/5.0"}

    # ── 1) 최근 어닝콜 트랜스크립트 ─────────────────────────
    try:
        # 먼저 사용 가능한 트랜스크립트 목록 조회
        list_url = f"{base}/earning_call_transcript?symbol={ticker}&apikey={api_key}"
        resp = requests.get(list_url, headers=headers, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                # 가장 최근 트랜스크립트의 year, quarter 추출
                latest = data[0]
                year = latest.get("year")
                quarter = latest.get("quarter")

                if year and quarter:
                    # 해당 분기 트랜스크립트 본문 조회
                    detail_url = (
                        f"{base}/earning_call_transcript"
                        f"?symbol={ticker}&year={year}&quarter={quarter}"
                        f"&apikey={api_key}"
                    )
                    resp2 = requests.get(detail_url, headers=headers, timeout=15)

                    if resp2.status_code == 200:
                        detail = resp2.json()
                        if isinstance(detail, list) and len(detail) > 0:
                            content = detail[0].get("content", "")
                            # 토큰 절약: 앞 8000자만 사용
                            result["transcript"] = content[:8000] if content else None
                            result["transcript_quarter"] = quarter
                            result["transcript_year"] = year
                            result["_status"]["transcript"] = "ok"
                        else:
                            result["_status"]["transcript"] = "empty_detail"
                    else:
                        result["_status"]["transcript"] = f"http_{resp2.status_code}"
                else:
                    result["_status"]["transcript"] = "no_year_quarter"
            else:
                result["_status"]["transcript"] = "no_transcripts_available"
        else:
            result["_status"]["transcript"] = f"http_{resp.status_code}"

    except Exception as e:
        result["_status"]["transcript"] = f"fail:{e}"

    # ── 2) 어닝 서프라이즈 (실적 vs 추정치) ──────────────────
    try:
        surprise_url = (
            f"{base}/earnings-surprises?symbol={ticker}&apikey={api_key}"
        )
        resp3 = requests.get(surprise_url, headers=headers, timeout=10)

        if resp3.status_code == 200:
            surprises = resp3.json()
            if isinstance(surprises, list) and len(surprises) > 0:
                # 최근 8분기만 저장
                result["earnings_surprises"] = surprises[:8]
                result["_status"]["earnings_surprises"] = "ok"
            else:
                result["_status"]["earnings_surprises"] = "empty"
        else:
            result["_status"]["earnings_surprises"] = f"http_{resp3.status_code}"

    except Exception as e:
        result["_status"]["earnings_surprises"] = f"fail:{e}"

    return result

def collect_news(ticker: str) -> List[Dict]:
    """Yahoo Finance RSS 기반 뉴스 헤드라인 수집"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    urls = [
        f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US",
        f"https://finance.yahoo.com/rss/headline?s={ticker}",
    ]
    items_out = []

    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                continue

            # html.parser로 먼저 시도, 실패 시 lxml-xml
            for parser in ["lxml-xml", "html.parser"]:
                try:
                    soup = BeautifulSoup(resp.content, parser)
                    raw_items = soup.find_all("item")
                    if raw_items:
                        break
                except Exception:
                    continue

            for it in raw_items[:20]:
                def txt(tag):
                    t = it.find(tag)
                    return t.get_text(strip=True) if t else ""
                title = txt("title")
                if not title:
                    continue
                items_out.append({
                    "title":  title,
                    "date":   txt("pubDate") or txt("pubdate"),
                    "source": txt("source") or "Yahoo Finance",
                    "link":   txt("link"),
                })
            if items_out:
                break
        except Exception:
            continue

    return items_out[:20]


# ============================================================
# LLM DATA CONTEXT BUILDER
# ============================================================

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


# ============================================================
# LLM ANALYSIS PIPELINE
# ============================================================

_SYSTEM_PROMPT = """당신은 월스트리트 탑티어 헤지펀드의 수석 애널리스트이자, 해당 산업에서 10년 이상 경력의 섹터 스페셜리스트입니다.

[최우선 지시] 핵심 투자포인트 3가지를 먼저 파악하고, 전체 12개 항목을 그 렌즈로 일관되게 분석하라.

[당신의 임무]
주어진 yfinance 실제 데이터 + 당신이 보유한 산업 전문 지식을 결합하여, 기관 투자자 수준의 12단계 딥 리서치 분석을 수행합니다.

[데이터 출처 구분 — 반드시 준수]
모든 수치·팩트 인용 시 출처를 명시하라:
- [DATA] = yfinance에서 직접 수집된 수치. 그대로 인용 가능.
- [LLM지식] = 당신의 학습 데이터 기반 산업 지식. 반드시 이 태그를 붙이고, 시점이 오래되었을 수 있음을 인지하라.
- [추정] = 위 두 가지를 조합한 당신의 추론. 반드시 이 태그 + 추론 근거를 한 줄로 밝혀라.

[LLM 자체 지식 활용 — 핵심 규칙]
항목 1~3: yfinance 데이터를 중심으로 분석하되, 해석과 맥락 설명에 LLM 지식을 적극 활용하라.
항목 4~11: yfinance에 없는 산업 심층 정보(어닝콜 발언, 경쟁사 동향, 공급망, 기술/특허, M&A, 정책)를 LLM 지식으로 적극 제공하라. 단, 모든 항목에 [LLM지식] 또는 [추정] 태그를 반드시 붙여라.
항목 12: 항목 1~11 전체를 종합하여 최종 판단을 내려라.
데이터가 진짜 없는 항목은 억지로 채우지 말고 "해당 기간 유의미한 정보 없음"으로 간결 처리하라.

[확신도 등급 정의 — 반드시 준수]
A = 투자 판단에 직접 영향. 수치적 근거가 있고 검증 가능. 액션: 매수/매도/비중조절 근거로 사용 가능.
B = 방향성은 맞으나 수치 정밀도가 불확실. 추가 확인 필요. 액션: 모니터링 대상.
C = 정황 추론 수준. 참고만 하고 이것만으로 판단 금지. 액션: 배경지식으로만 활용.

[한줄관통 작성 규칙]
① 반드시 구체적 수치 또는 팩트를 1개 이상 포함하라.
② "시장은 X인데 실제로는 Y" 같은 동일 구문을 반복하지 마라. 항목마다 주어와 구조를 달리하라.
   예시 변형:
   - "Forward P/E 12x는 FY2026 EPS $33 기준이며, 이는 메모리 사이클 고점 P/E 역사적 범위(8~15x)의 중단에 해당한다"
   - "내부자 매수 0건/매도 76건의 12개월 패턴은 10b5-1 계획 매매로 보이나, 클러스터 매수 부재는 경영진의 단기 확신 부족 시그널"
   - "ATM IV 72%는 21일 실현변동성 대비 1.4배이며, 이는 3/19 실적 발표 전 옵션 프리미엄이 과대 책정된 상태"
③ 일반론("AI 수요가 긍정적", "성장이 기대됨") 절대 금지. 해당 기업에만 적용되는 고유한 팩트를 써라.

[상세설명 작성 규칙]
① 한줄관통을 단순히 풀어쓰지 마라.
② 반드시 포함할 것: 원데이터 인용 → 계산/비교 과정 → 반대 논거(devil's advocate) → 결론.
③ yfinance 데이터의 구체적 숫자(기관명, 보유주수, 내부자 이름/날짜/주수, 옵션 OI 등)를 직접 인용하라.
④ 비교 기준 없는 단독 수치 금지. 반드시 시가총액 대비, 연매출 대비, 동종 평균 대비, 과거 대비 등 맥락을 붙여라.

[옵션 시장 해석 규칙]
ATM IV 수치를 제시할 때 반드시:
- 21일 실현변동성(RV) 대비 IV/RV 비율 계산
- IV가 높은지 낮은지 판단 기준 제시 (IV/RV > 1.2 = 높음, < 0.8 = 낮음)
- P/C Ratio 해석: > 1.2 = 하락 헤지 수요 높음, < 0.7 = 상승 베팅 우세
- "쉬운 번역" 한 문장 필수: 예) "옵션 시장은 향후 30일간 ±8% 움직임을 예상하며, 이는 평소보다 1.4배 큰 변동성이다"

[리스크 시나리오 규칙]
각 테일리스크마다 반드시 3가지를 포함:
- 발생 확률(%)
- 현실화 시 주가 영향(-X%)
- 예상 시점(YYYY-MM 또는 분기)

[내부자 거래 분석 규칙]
내부자 매도 시 반드시 10b5-1 사전 계획 매매인지, 재량적(discretionary) 매매인지 판별하라. 10b5-1은 중립, 재량적 대량 매도만 부정 시그널로 판단.

[경쟁 해자 분석 규칙]
해당 기업의 산업에서 가장 위협적인 경쟁자/대체재를 2~3개 특정하고, 분석 대상 기업의 핵심 해자(기술 생태계, 전환비용, 네트워크 효과, 규모의 경제 등)가 그 위협을 얼마나 방어할 수 있는지 구체적으로 평가하라.
예시: 반도체=ASIC경쟁(TPU/Trainium/Maia) vs CUDA 생태계, SaaS=오픈소스 대체재 vs 전환비용, 소비재=PB(자체브랜드) vs 브랜드 충성도, 금융=핀테크 vs 규제 해자.

[자본배분 규칙]
자본배분 분석 시 CAPEX, R&D, 자사주매입, 배당, M&A 각각 구체적 금액과 매출 대비 비율(%)을 명시하라.

[뉴스 감성 규칙]
뉴스 헤드라인 분석 시 단순 긍정/부정 분류가 아니라, "이 뉴스가 향후 실적에 미치는 함의"를 한 문장으로 연결하라.

[이모지 태깅 규칙]
한줄관통의 방향성 표시: 긍정 = 🟢, 부정 = 🔴, 중립/불확실 = 🟡

[포맷 금지 규칙]
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
다음 데이터를 바탕으로 {ticker} ({company_name})에 대한 12단계 투자 분석을 수행하라.

{data_context}

반드시 아래 JSON 구조로만 응답하라 (JSON 외 텍스트 절대 불가):
{{
  "items": [
    {{
      "항목번호": 1,
      "항목명": "밸류에이션 갭 진단",
      "한줄관통": "구체적 수치 포함 핵심 인사이트 한 줄",
      "방향성": "호재",
      "상세설명": "충분한 상세 분석 내용...",
      "데이터출처": "[DATA]/[LLM지식]/[추정]",
      "확신도": "A",
      "액션": "매수"
    }}
  ],
  "alpha_matrix": {{
    "variant_perception": [{{"항목번호": 1, "한줄관통": "..."}}],
    "earnings_leverage":  [{{"항목번호": 3, "한줄관통": "..."}}],
    "catalyst_timeline":  [{{"항목번호": 11, "한줄관통": "..."}}],
    "tail_risk":          [{{"항목번호": 10, "한줄관통": "..."}}],
    "top3_insights": [
      {{"순위": 1, "항목번호": 1, "인사이트": "시장과 가장 크게 다른 관점 한 줄", "액션": "매수"}},
      {{"순위": 2, "항목번호": 3, "인사이트": "...", "액션": "보유"}},
      {{"순위": 3, "항목번호": 7, "인사이트": "...", "액션": "관망"}}
    ]
  }},
  "final_opinion": {{
    "의견": "매수",
    "bull_case": "Bull 시나리오 한 줄 + 확률 X%",
    "base_case": "Base 시나리오 한 줄 + 확률 X%",
    "bear_case": "Bear 시나리오 한 줄 + 확률 X%",
    "upside_pct": 25,
    "downside_pct": 12,
    "trigger_condition": "구체적 수치 기준 포함 의견 변경 조건",
    "next_catalyst": "가장 가까운 주가 재평가 이벤트명",
    "next_catalyst_date": "YYYY-MM-DD"
  }}
}}

각 항목 분석 지침:

1번. 밸류에이션 갭 진단 — 시장이 뭘 놓치고 있나?
[DATA] P/E, Forward P/E, EV/EBITDA, PEG를 동종 기업 평균과 비교. 괴리가 있으면 그 원인을 추정하라. 애널리스트 목표가 vs 현재가 괴리율 계산. 역사적 밸류에이션 밴드 대비 현재 위치 판단.

2번. 실적/가이던스/경영진 크로스체크 — 숫자와 말이 일치하나?
[DATA] 어닝 서프라이즈 히스토리에서 최근 4분기 Beat/Miss 패턴 분석. [LLM지식] 최근 어닝콜에서 경영진이 강조한 포인트와 실제 수치의 일치 여부. 가이던스 상향/하향 이력. 내부자 매매와 가이던스 방향이 일치하는지 교차검증.

3번. 핵심 매출 드라이버 & 선행지표 — 다음 분기 이익을 움직이는 변수는?
해당 기업 비즈니스 모델의 핵심 선행지표 2~3개를 특정하라. [LLM지식] 산업별 선행지표 예시: 반도체=재고일수/ASP/HBM수급, SaaS=RPO/ARR/NRR, 제조업=Book-to-Bill/백로그, 소매=동일매장매출/재고회전. 각 선행지표의 현재 방향과 이익 레버리지 크기를 추정.

4번. 경쟁 해자 & 공급망 — 이 회사를 대체할 수 있나?
[LLM지식] 해당 기업의 핵심 해자 유형(기술생태계/전환비용/네트워크효과/규모의경제)을 특정하고 강도를 평가. 가장 위협적인 경쟁자/대체재 2~3개를 명시. 핵심 공급업체/고객 집중도 리스크. Time-to-Replicate(경쟁자가 따라잡는데 걸리는 시간) 추정.

5번. 산업 매크로 & 경쟁구도 — 업종 전체가 좋은가, 이 회사만 좋은가?
[DATA] 동종 기업 밸류에이션 비교에서 상대적 위치. [LLM지식] 업종 전체 사이클 위치(초기/중기/후기/침체). 경쟁사 최근 실적에서 역추적한 업종 수요 시그널. 해당 기업만의 차별적 성장 요인이 있는지 판별.

6번. 정책/규제/지정학 — 정부가 도울까 막을까?
[LLM지식] 해당 기업에 직접 영향을 미치는 정책/규제만 간결하게. 영향 없으면 "해당 기간 유의미한 정책 변화 없음"으로 처리. 영향 있으면 매출/이익 임팩트를 방향성+추정 수치로 한 줄 추가.

7번. 계약/M&A/사업전환 — 판을 바꿀 딜이 있나?
[LLM지식] 최근 대형 계약, 파트너십, 인수합병을 매출 기여도 순 정렬. 뉴스 헤드라인에서 관련 내용 확인. 없으면 "해당 기간 유의미한 딜 없음"으로 간결 처리.

8번. 자금흐름 (내부자/기관/옵션 통합) — 돈 아는 사람들이 뭘 하나?
[DATA] 내부자 거래에서 구체적 이름, 날짜, 주수 인용. 10b5-1 계획 매매 vs 재량적 매매 판별. 기관 Top 3 보유 변화. 옵션 P/C Ratio와 ATM IV 해석 + "쉬운 번역" 한 문장. 클러스터 매수(3인 이상 동시) 여부 확인.

9번. 자본배분 — 번 돈을 어디에 쓰나?
[DATA] FCF, CAPEX, R&D, 자사주매입, 배당, M&A 각각 구체적 금액과 매출 대비 비율(%) 명시. ROIC vs WACC 비교. 성장 투자 vs 주주환원 밸런스 평가. 부채 상환 계획.

10번. 리스크 시나리오 & 확률 — 최악엔 얼마나 잃나?
테일리스크 3~5개를 나열하고 각각: 발생 확률(%), 현실화 시 주가 영향(-X%), 예상 시점(YYYY-MM 또는 분기)을 반드시 포함. 가장 과소평가된 리스크 1개를 특정하라.

11번. 촉매 캘린더 & 타이밍 — 언제 움직이나?
[DATA] 다음 어닝 발표일. [LLM지식] 향후 1~6개월 주요 이벤트를 날짜순 정리. 각 이벤트별 주가 영향 방향과 크기 추정.

12번. 최종 비대칭 리스크/리워드 판단 — 사야 하나 말아야 하나?
항목 1~11을 종합. Bull/Base/Bear 3시나리오 각각 확률(%)과 목표가 제시. 기대수익률 계산. 의견 변경 트리거를 구체적 수치 기준으로 명시.
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
                temperature=0.2,
                max_tokens=16000,
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
# UI RENDERING FUNCTIONS
# ============================================================

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

        # ── (E) 1~20번 분석 항목 ──────────────────────────────
        st.markdown("## 🧠 12단계 딥 리서치 분석")

        st.markdown("### Part A. 데이터 기반 분석 (1~3번)")
        for it in items[:3]:
            render_analysis_item(it)
            st.markdown(
                "<hr style='border:none;border-top:1px solid #2D2D3F;margin:6px 0;'>",
                unsafe_allow_html=True,
            )

        st.markdown("### Part B. 산업 심층 분석 (4~11번)")
        for it in items[3:11]:
            render_analysis_item(it)
            st.markdown(
                "<hr style='border:none;border-top:1px solid #2D2D3F;margin:6px 0;'>",
                unsafe_allow_html=True,
            )

        # ── (F) 21~22번 종합 ──────────────────────────────────
        st.markdown("### Part C. 최종 판단 (12번)")
        if alpha_mat:
            render_alpha_matrix(alpha_mat)
        if final_op:
            render_final_opinion_box(final_op)

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
