"""Outils d'information en ligne (sans cle API) : meteo, actualites, crypto, devises, bourse, Wikipedia, heure mondiale."""

from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote, quote_plus

import httpx

from . import ToolError, tool

UA = {"User-Agent": "Mozilla/5.0 (JARVIS assistant)", "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"}

WMO = {
    0: "ciel degage", 1: "plutot degage", 2: "partiellement nuageux", 3: "couvert", 45: "brouillard",
    48: "brouillard givrant", 51: "bruine legere", 53: "bruine", 55: "bruine dense", 56: "bruine verglacante",
    57: "bruine verglacante dense", 61: "pluie faible", 63: "pluie", 65: "forte pluie", 66: "pluie verglacante",
    67: "forte pluie verglacante", 71: "neige faible", 73: "neige", 75: "forte neige", 77: "grains de neige",
    80: "averses faibles", 81: "averses", 82: "violentes averses", 85: "averses de neige", 86: "fortes averses de neige",
    95: "orage", 96: "orage avec grele", 99: "violent orage avec grele",
}

_cache: dict[str, tuple[float, object]] = {}


async def _get_json(url: str, params: dict | None = None, ttl: float = 120, headers: dict | None = None):
    key = url + repr(sorted((params or {}).items()))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    async with httpx.AsyncClient(timeout=10, headers=headers or UA, follow_redirects=True) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
    _cache[key] = (time.time(), data)
    return data


async def ip_location() -> dict:
    try:
        j = await _get_json("https://ipwho.is/", ttl=3600)
        if j.get("success", True):
            return {"name": j.get("city"), "lat": j.get("latitude"), "lon": j.get("longitude"),
                    "country": j.get("country"), "timezone": (j.get("timezone") or {}).get("id")}
    except (httpx.HTTPError, ValueError):
        pass
    return {"name": "Paris", "lat": 48.8566, "lon": 2.3522, "country": "France", "timezone": "Europe/Paris"}


async def geocode(city: str) -> dict:
    j = await _get_json("https://geocoding-api.open-meteo.com/v1/search",
                        {"name": city, "count": 1, "language": "fr", "format": "json"}, ttl=86400)
    res = (j or {}).get("results") or []
    if not res:
        raise ToolError(f"Ville introuvable : {city}")
    r = res[0]
    return {"name": r["name"], "lat": r["latitude"], "lon": r["longitude"], "country": r.get("country"),
            "timezone": r.get("timezone")}


@tool(
    "get_weather",
    "Meteo precise (Open-Meteo) : conditions actuelles, ressenti, vent, humidite, UV, qualite de l'air, "
    "previsions heure par heure et sur plusieurs jours. Sans ville : position detectee automatiquement.",
    {
        "city": {"type": "string", "description": "Ville (vide = position actuelle)."},
        "days": {"type": "integer", "description": "Jours de prevision 1-14 (defaut 3)."},
    },
    category="infos",
)
async def get_weather(city: str = "", days: int = 3) -> dict:
    from ..config import get_settings

    city = city or get_settings().city
    place = await geocode(city) if city else await ip_location()
    days = max(1, min(int(days or 3), 14))
    params = {
        "latitude": place["lat"], "longitude": place["lon"], "timezone": "auto", "forecast_days": days,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,"
                   "cloud_cover,wind_speed_10m,wind_direction_10m,wind_gusts_10m,pressure_msl,uv_index",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                 "precipitation_sum,sunrise,sunset,uv_index_max,wind_speed_10m_max",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
    }
    try:
        j = await _get_json("https://api.open-meteo.com/v1/forecast", params, ttl=300)
    except httpx.HTTPError as exc:
        raise ToolError(f"Service meteo indisponible : {exc}") from exc
    cur = j["current"]
    out = {
        "lieu": f"{place['name']}, {place.get('country') or ''}".strip(", "),
        "actuel": {
            "temperature_c": cur["temperature_2m"], "ressenti_c": cur["apparent_temperature"],
            "conditions": WMO.get(cur["weather_code"], "?"), "code": cur["weather_code"], "jour": bool(cur["is_day"]),
            "humidite_pct": cur["relative_humidity_2m"], "vent_kmh": cur["wind_speed_10m"],
            "rafales_kmh": cur["wind_gusts_10m"], "direction_vent_deg": cur["wind_direction_10m"],
            "nuages_pct": cur["cloud_cover"], "pression_hpa": cur["pressure_msl"], "uv": cur.get("uv_index"),
            "precipitations_mm": cur["precipitation"],
        },
        "jours": [],
        "prochaines_heures": [],
    }
    d = j["daily"]
    for i, day in enumerate(d["time"]):
        out["jours"].append({
            "date": day, "conditions": WMO.get(d["weather_code"][i], "?"), "code": d["weather_code"][i],
            "min_c": d["temperature_2m_min"][i], "max_c": d["temperature_2m_max"][i],
            "proba_pluie_pct": d["precipitation_probability_max"][i], "pluie_mm": d["precipitation_sum"][i],
            "lever": d["sunrise"][i][-5:], "coucher": d["sunset"][i][-5:], "uv_max": d["uv_index_max"][i],
            "vent_max_kmh": d["wind_speed_10m_max"][i],
        })
    h = j["hourly"]
    now_iso = cur["time"][:13]
    start = next((i for i, t in enumerate(h["time"]) if t[:13] >= now_iso), 0)
    for i in range(start, min(start + 12, len(h["time"]))):
        out["prochaines_heures"].append({
            "heure": h["time"][i][-5:], "temp_c": h["temperature_2m"][i],
            "proba_pluie_pct": h["precipitation_probability"][i], "conditions": WMO.get(h["weather_code"][i], "?"),
        })
    try:
        aq = await _get_json("https://air-quality-api.open-meteo.com/v1/air-quality",
                             {"latitude": place["lat"], "longitude": place["lon"], "current": "european_aqi,pm10,pm2_5"},
                             ttl=900)
        c = aq.get("current", {})
        out["qualite_air"] = {"indice_europeen": c.get("european_aqi"), "pm10": c.get("pm10"), "pm2_5": c.get("pm2_5")}
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    return out


NEWS_TOPICS = {
    "une": "", "monde": "WORLD", "france": "NATION", "economie": "BUSINESS", "tech": "TECHNOLOGY",
    "divertissement": "ENTERTAINMENT", "sport": "SPORTS", "science": "SCIENCE", "sante": "HEALTH",
}


def _parse_rss(xml_text: str, limit: int) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for item in root.iter("item"):
        title = html.unescape(item.findtext("title") or "").strip()
        source = item.findtext("source") or ""
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        desc = re.sub(r"<[^>]+>", " ", html.unescape(item.findtext("description") or "")).strip()
        items.append({
            "titre": title, "source": source, "lien": item.findtext("link"),
            "date": item.findtext("pubDate"), "resume": re.sub(r"\s+", " ", desc)[:280] if not source else "",
        })
        if len(items) >= limit:
            break
    return items


@tool(
    "get_news",
    "Dernieres actualites (Google Actualites, en francais) : a la une, par rubrique (monde, france, economie, "
    "tech, sport, science, sante, divertissement) ou sur un sujet precis.",
    {
        "topic": {"type": "string", "enum": list(NEWS_TOPICS), "description": "Rubrique (defaut: une)."},
        "query": {"type": "string", "description": "Sujet libre, ex: 'intelligence artificielle', 'PSG'."},
        "count": {"type": "integer", "description": "Nombre d'articles (defaut 8)."},
    },
    category="infos",
)
async def get_news(topic: str = "une", query: str = "", count: int = 8) -> list[dict]:
    count = max(1, min(int(count or 8), 25))
    suffix = "hl=fr&gl=FR&ceid=FR:fr"
    if query:
        url = f"https://news.google.com/rss/search?q={quote_plus(query)}&{suffix}"
    elif NEWS_TOPICS.get(topic):
        url = f"https://news.google.com/rss/headlines/section/topic/{NEWS_TOPICS[topic]}?{suffix}"
    else:
        url = f"https://news.google.com/rss?{suffix}"
    try:
        async with httpx.AsyncClient(timeout=10, headers=UA, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
        return _parse_rss(r.text, count)
    except (httpx.HTTPError, ET.ParseError) as exc:
        raise ToolError(f"Actualites indisponibles : {exc}") from exc


CRYPTO_IDS = {
    "btc": "bitcoin", "bitcoin": "bitcoin", "eth": "ethereum", "ethereum": "ethereum", "sol": "solana",
    "solana": "solana", "xrp": "ripple", "ada": "cardano", "doge": "dogecoin", "dogecoin": "dogecoin",
    "bnb": "binancecoin", "dot": "polkadot", "ltc": "litecoin", "usdt": "tether", "usdc": "usd-coin",
    "avax": "avalanche-2", "link": "chainlink", "matic": "matic-network", "trx": "tron", "ton": "the-open-network",
    "shib": "shiba-inu", "pepe": "pepe", "sui": "sui",
}


@tool(
    "get_crypto_prices",
    "Cours des cryptomonnaies en temps reel (CoinGecko) avec variation sur 24h et capitalisation.",
    {
        "symbols": {"type": "array", "items": {"type": "string"}, "description": "Ex: ['BTC', 'ETH', 'solana']."},
        "currency": {"type": "string", "description": "Devise (defaut eur)."},
    },
    required=["symbols"],
    category="infos",
)
async def get_crypto_prices(symbols: list, currency: str = "eur") -> dict:
    cur = (currency or "eur").lower()
    ids = []
    for s in symbols[:15]:
        key = str(s).lower().strip()
        if key in CRYPTO_IDS:
            ids.append(CRYPTO_IDS[key])
        else:
            try:
                found = await _get_json("https://api.coingecko.com/api/v3/search", {"query": key}, ttl=86400)
                coins = found.get("coins") or []
                ids.append(coins[0]["id"] if coins else key)
            except (httpx.HTTPError, ValueError):
                ids.append(key)
    try:
        j = await _get_json("https://api.coingecko.com/api/v3/simple/price", {
            "ids": ",".join(ids), "vs_currencies": cur, "include_24hr_change": "true", "include_market_cap": "true",
        }, ttl=60)
    except httpx.HTTPError as exc:
        raise ToolError(f"CoinGecko indisponible : {exc}") from exc
    return {cid: {"prix": v.get(cur), "variation_24h_pct": round(v.get(f"{cur}_24h_change") or 0, 2),
                  "capitalisation": v.get(f"{cur}_market_cap"), "devise": cur.upper()} for cid, v in j.items()}


@tool(
    "convert_currency",
    "Conversion de devises au taux du jour (BCE via Frankfurter), ex: 100 USD -> EUR.",
    {
        "amount": {"type": "number"},
        "from_currency": {"type": "string", "description": "Code ISO, ex: USD"},
        "to_currency": {"type": "string", "description": "Code ISO, ex: EUR"},
    },
    required=["amount", "from_currency", "to_currency"],
    category="infos",
)
async def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
    src, dst = from_currency.upper().strip(), to_currency.upper().strip()
    if src == dst:
        return f"{amount} {src} = {amount} {dst}"
    try:
        j = await _get_json("https://api.frankfurter.app/latest", {"amount": amount, "from": src, "to": dst}, ttl=1800)
        value = j["rates"][dst]
        date = j.get("date")
    except (httpx.HTTPError, KeyError, ValueError):
        try:
            j = await _get_json(f"https://open.er-api.com/v6/latest/{src}", ttl=1800)
            value = amount * j["rates"][dst]
            date = j.get("time_last_update_utc", "")[:16]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ToolError(f"Conversion impossible : {exc}") from exc
    return f"{amount:,.2f} {src} = {value:,.2f} {dst} (taux du {date})".replace(",", " ")


@tool(
    "get_stock_quote",
    "Cours de bourse d'une action ou d'un indice (ex: AAPL, MSFT, TSLA, MC.PA pour LVMH, ^FCHI pour le CAC 40).",
    {"symbol": {"type": "string"}},
    required=["symbol"],
    category="infos",
)
async def get_stock_quote(symbol: str) -> dict:
    sym = symbol.strip().upper()
    try:
        j = await _get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(sym)}",
                            {"range": "5d", "interval": "1d"}, ttl=60)
        meta = j["chart"]["result"][0]["meta"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise ToolError(f"Cours introuvable pour {sym} (utilisez web_search si besoin).") from exc
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    change = ((price - prev) / prev * 100) if price and prev else None
    return {"symbole": sym, "nom": meta.get("longName") or meta.get("shortName"), "prix": price,
            "devise": meta.get("currency"), "cloture_precedente": prev,
            "variation_pct": round(change, 2) if change is not None else None,
            "plus_haut_jour": meta.get("regularMarketDayHigh"), "plus_bas_jour": meta.get("regularMarketDayLow"),
            "marche": meta.get("exchangeName")}


@tool(
    "wikipedia_summary",
    "Resume Wikipedia d'un sujet, d'une personne, d'un lieu (langue configurable).",
    {"topic": {"type": "string"}, "lang": {"type": "string", "description": "Code langue (defaut fr)."}},
    required=["topic"],
    category="infos",
)
async def wikipedia_summary(topic: str, lang: str = "fr") -> dict:
    lang = re.sub(r"[^a-z]", "", (lang or "fr").lower())[:3] or "fr"
    try:
        search = await _get_json(f"https://{lang}.wikipedia.org/w/api.php",
                                 {"action": "opensearch", "search": topic, "limit": 1, "format": "json"}, ttl=3600)
        title = search[1][0] if search and len(search) > 1 and search[1] else topic
        j = await _get_json(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'))}",
                            ttl=3600)
    except (httpx.HTTPError, ValueError, IndexError) as exc:
        raise ToolError(f"Article introuvable : {topic}") from exc
    return {"titre": j.get("title"), "description": j.get("description"), "resume": j.get("extract"),
            "lien": (j.get("content_urls") or {}).get("desktop", {}).get("page")}


CITY_TZ = {
    "paris": "Europe/Paris", "londres": "Europe/London", "london": "Europe/London", "new york": "America/New_York",
    "los angeles": "America/Los_Angeles", "san francisco": "America/Los_Angeles", "montreal": "America/Toronto",
    "montréal": "America/Toronto", "tokyo": "Asia/Tokyo", "pekin": "Asia/Shanghai", "shanghai": "Asia/Shanghai",
    "dubai": "Asia/Dubai", "sydney": "Australia/Sydney", "berlin": "Europe/Berlin", "madrid": "Europe/Madrid",
    "rome": "Europe/Rome", "moscou": "Europe/Moscow", "dakar": "Africa/Dakar", "alger": "Africa/Algiers",
    "casablanca": "Africa/Casablanca", "tunis": "Africa/Tunis", "abidjan": "Africa/Abidjan", "kinshasa": "Africa/Kinshasa",
    "mumbai": "Asia/Kolkata", "delhi": "Asia/Kolkata", "singapour": "Asia/Singapore", "hong kong": "Asia/Hong_Kong",
    "seoul": "Asia/Seoul", "chicago": "America/Chicago", "mexico": "America/Mexico_City", "sao paulo": "America/Sao_Paulo",
    "buenos aires": "America/Argentina/Buenos_Aires", "la reunion": "Indian/Reunion", "martinique": "America/Martinique",
    "guadeloupe": "America/Guadeloupe", "tahiti": "Pacific/Tahiti", "bruxelles": "Europe/Brussels", "geneve": "Europe/Zurich",
    "zurich": "Europe/Zurich", "lisbonne": "Europe/Lisbon", "istanbul": "Europe/Istanbul", "le caire": "Africa/Cairo",
    "johannesburg": "Africa/Johannesburg", "honolulu": "Pacific/Honolulu", "vancouver": "America/Vancouver",
}


@tool(
    "world_clock",
    "Heure actuelle dans d'autres villes / fuseaux horaires (ex: ['Tokyo', 'New York', 'America/Lima']).",
    {"places": {"type": "array", "items": {"type": "string"}}},
    required=["places"],
    category="infos",
)
def world_clock(places: list) -> dict:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    out = {}
    for place in places[:12]:
        tzname = CITY_TZ.get(str(place).lower().strip(), str(place).strip())
        try:
            now = datetime.now(ZoneInfo(tzname))
            out[str(place)] = now.strftime("%A %d/%m %H:%M (UTC%z)")
        except (ZoneInfoNotFoundError, ValueError):
            out[str(place)] = "fuseau inconnu - preciser un fuseau IANA, ex: 'Asia/Bangkok'"
    return out
