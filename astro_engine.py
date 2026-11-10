import swisseph as swe
from datetime import datetime, timedelta, time
import pytz
import pandas as pd
from geopy.geocoders import Nominatim

swe.set_sid_mode(swe.SIDM_LAHIRI)

DASHA_YEARS = {
    "Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10,
    "Mars": 7, "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17
}
PLANET_ORDER = list(DASHA_YEARS.keys())
TOTAL_CYCLE_YEARS = 120.0
NAKSHATRA_SPAN_DEG = 360.0 / 27.0
SOLAR_YEAR_DAYS = 365.25

SIGN_LORDS = {
    0: "Mars", 1: "Venus", 2: "Mercury", 3: "Moon",
    4: "Sun", 5: "Mercury", 6: "Venus", 7: "Mars",
    8: "Jupiter", 9: "Saturn", 10: "Saturn", 11: "Jupiter"
}

HOUSE_FINANCIAL_SCORES = {
    1: 1.0, 2: 2.5, 3: 0.0, 4: 0.5, 5: 2.0, 6: -2.0,
    7: 0.0, 8: -3.0, 9: 2.0, 10: 1.5, 11: 3.0, 12: -2.5
}

def resolve_location(pob_str):
    geolocator = Nominatim(user_agent="stock_astro_engine")
    loc = geolocator.geocode(pob_str, timeout=10)
    if not loc:
        return 18.9220, 72.8347, "Mumbai, India (Default)"
    return loc.latitude, loc.longitude, loc.address

def datetime_to_jd(dt_utc):
    return swe.julday(
        dt_utc.year, dt_utc.month, dt_utc.day,
        dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    )

def calculate_natal_chart(jd_birth, lat, lon):
    cusps, ascmc = swe.houses_ex(jd_birth, lat, lon, b'W', swe.FLG_SIDEREAL)
    asc_lon = ascmc[0]
    lagna_sign = int(asc_lon / 30.0) % 12

    planet_ownership = {p: [] for p in PLANET_ORDER}
    for house_num in range(1, 13):
        sign = (lagna_sign + (house_num - 1)) % 12
        ruler = SIGN_LORDS[sign]
        planet_ownership[ruler].append(house_num)

    res_rahu, _ = swe.calc_ut(jd_birth, swe.MEAN_NODE, swe.FLG_SIDEREAL)
    rahu_lon = res_rahu[0]
    ketu_lon = (rahu_lon + 180.0) % 360.0

    rahu_disp = SIGN_LORDS[int(rahu_lon / 30.0) % 12]
    ketu_disp = SIGN_LORDS[int(ketu_lon / 30.0) % 12]
    planet_ownership["Rahu"] = list(planet_ownership[rahu_disp])
    planet_ownership["Ketu"] = list(planet_ownership[ketu_disp])

    planet_scores = {
        p: sum(HOUSE_FINANCIAL_SCORES.get(h, 0.0) for h in houses)
        for p, houses in planet_ownership.items()
    }
    return lagna_sign, asc_lon, planet_scores, planet_ownership

def get_natal_moon(jd_birth):
    res, _ = swe.calc_ut(jd_birth, swe.MOON, swe.FLG_SIDEREAL)
    lon = res[0]
    idx = int(lon / NAKSHATRA_SPAN_DEG)
    balance_ratio = 1.0 - ((lon - (idx * NAKSHATRA_SPAN_DEG)) / NAKSHATRA_SPAN_DEG)
    lord = PLANET_ORDER[idx % 9]
    balance_days = balance_ratio * DASHA_YEARS[lord] * SOLAR_YEAR_DAYS
    return lord, balance_days, idx % 9

def get_sub_lords(target_time, span_start, span_end, parent_lord, current_level=2, max_level=6):
    if current_level > max_level:
        return []
    total_sec = (span_end - span_start).total_seconds()
    start_idx = PLANET_ORDER.index(parent_lord)
    cycle = [PLANET_ORDER[(start_idx + i) % 9] for i in range(9)]
    
    cursor = span_start
    duration = 0.0
    for lord in cycle:
        duration = total_sec * (DASHA_YEARS[lord] / TOTAL_CYCLE_YEARS)
        end_cursor = cursor + timedelta(seconds=duration)
        if cursor <= target_time < end_cursor:
            return [lord] + get_sub_lords(target_time, cursor, end_cursor, lord, current_level + 1, max_level)
        cursor = end_cursor
    return [cycle[-1]] + get_sub_lords(target_time, cursor - timedelta(seconds=duration), span_end, cycle[-1], current_level + 1, max_level)

def get_active_dashas(target_dt, birth_dt, first_lord, balance_days, start_idx):
    cursor_start = birth_dt
    cursor_end = cursor_start + timedelta(days=balance_days)
    curr_idx = start_idx
    
    while True:
        curr_lord = PLANET_ORDER[curr_idx]
        if cursor_start <= target_dt < cursor_end:
            active_md, md_start, md_end = curr_lord, cursor_start, cursor_end
            break
        cursor_start = cursor_end
        curr_idx = (curr_idx + 1) % 9
        next_lord = PLANET_ORDER[curr_idx]
        cursor_end = cursor_start + timedelta(days=DASHA_YEARS[next_lord] * SOLAR_YEAR_DAYS)
        
    sub_lords = get_sub_lords(target_dt, md_start, md_end, active_md, 2, 6)
    return [active_md] + sub_lords

def evaluate_slot_trend(dashas, planet_scores):
    _, _, pd_lord, sd_lord, pad_lord, dd_lord = dashas
    composite = (
        0.45 * planet_scores.get(dd_lord, 0.0) +
        0.35 * planet_scores.get(pad_lord, 0.0) +
        0.12 * planet_scores.get(sd_lord, 0.0) +
        0.08 * planet_scores.get(pd_lord, 0.0)
    )
    if composite >= 1.5:
        sentiment = "STRONG BULLISH"
    elif composite >= 0.5:
        sentiment = "BULLISH"
    elif composite <= -1.5:
        sentiment = "STRONG BEARISH"
    elif composite <= -0.5:
        sentiment = "BEARISH"
    else:
        sentiment = "NEUTRAL"
    return composite, sentiment