# data_collectors.py — 모든 데이터 수집 함수들
import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, List

from utils import df_safe


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
