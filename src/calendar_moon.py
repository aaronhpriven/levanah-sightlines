#!/usr/bin/env python3
"""
Pure-Python Hebrew calendar (5787), Kiddush Levanah windows (3d to 15d after molad),
shkiah + 50 min tzeis, and high-precision topocentric Moon azimuth/altitude (Meeus).
Zero external dependencies.
"""

from __future__ import annotations

import datetime
import math
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# 210 West 91st Street, New York, NY 10024 (will be refined from NYC/OSM data)
DEFAULT_SHUL_LAT = 40.79104
DEFAULT_SHUL_LON = -73.97330
DEFAULT_SHUL_ELEV_M = 25.0

# ---------------------------------------------------------------------------
# 1. Exact Hebrew Calendar & Molad (traditional halachic calculation)
# ---------------------------------------------------------------------------

CHALAKIM_PER_HOUR = 1080
CHALAKIM_PER_DAY = 25920
CHALAKIM_PER_MONTH = 29 * CHALAKIM_PER_DAY + 12 * CHALAKIM_PER_HOUR + 793

# Jerusalem Mean Time offset from UTC (KosherJava standard: 35.2354° E = 2h 20m 56.496s)
JERUSALEM_OFFSET_SECONDS = 2 * 3600 + 20 * 60 + 56.496


def is_hebrew_leap_year(year: int) -> bool:
    return (year * 7 + 1) % 19 < 7


def months_before_hebrew_year(year: int) -> int:
    return (235 * year - 234) // 19


def hebrew_new_year_elapsed_days(year: int) -> int:
    """Days elapsed from epoch (1 Tishrei Year 1) to Rosh Hashanah of `year`, with all 4 dechiot."""
    months = months_before_hebrew_year(year)
    parts = 13753 * months + 5604
    #Wait: let's use exact chalakim from Beharad (Day 2, 5h, 204ch => 1 day + 5h + 204ch after Day 1 0h)
    # Using exact chalakim avoids any rounding:
    total_chalakim = (1 * CHALAKIM_PER_DAY + 5 * CHALAKIM_PER_HOUR + 204) + months * CHALAKIM_PER_MONTH
    days = total_chalakim // CHALAKIM_PER_DAY
    rem_chalakim = total_chalakim % CHALAKIM_PER_DAY
    hours = rem_chalakim // CHALAKIM_PER_HOUR
    chalakim = rem_chalakim % CHALAKIM_PER_HOUR

    # Day of week: 0=Sat? Let's check:
    # Epoch day 0 = Sunday (Day 1). So days=1 => Monday (Day 2, Beharad).
    # dow: 0=Sun, 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat
    dow = days % 7

    # Dechiah 1: Molad Zaken (at or after 18 hours = noon)
    if hours >= 18:
        days += 1
        dow = (dow + 1) % 7
    # Dechiah 3: GaTRaD (non-leap year, Tuesday >= 9h 204ch)
    elif (not is_hebrew_leap_year(year)) and dow == 2 and (hours > 9 or (hours == 9 and chalakim >= 204)):
        days += 2
        dow = (dow + 2) % 7
    # Dechiah 4: BeTuTaKPaT (year after leap year, Monday >= 15h 589ch)
    elif is_hebrew_leap_year(year - 1) and dow == 1 and (hours > 15 or (hours == 15 and chalakim >= 589)):
        days += 1
        dow = (dow + 1) % 7

    # Dechiah 2: Lo ADU Rosh (not Sun=0, Wed=3, Fri=5)
    if dow in (0, 3, 5):
        days += 1

    return days


def rosh_hashanah_date(year: int) -> datetime.date:
    """Gregorian date of 1 Tishrei for Hebrew `year`."""
    # Anchor: 1 Tishrei 5787 — let's compute from verified epoch:
    # Epoch day 1 (Monday Oct 7, 3761 BCE Julian = JD 347997 at noon -> 347996.5 at 00:00).
    # In Python ordinal (1 = 0001-01-01 Gregorian = JD 1721425.5):
    # Wait: JD of 1 Tishrei 1 (Monday, Oct 7, 3761 BCE Julian) = 347997.5 (at 00:00? Let's verify!).
    # Easier: anchor to 1 Tishrei 5780 = 2019-09-30 (verified) and verify 5787 = 2026-09-12!
    days_5780 = hebrew_new_year_elapsed_days(5780)
    days_y = hebrew_new_year_elapsed_days(year)
    return datetime.date(2019, 9, 30) + datetime.timedelta(days=(days_y - days_5780))


def hebrew_year_months(year: int) -> list[tuple[int, str, int]]:
    """
    Return list of (month_num, month_name, num_days) in order from Tishrei to Elul.
    month_num follows standard convention: 7=Tishrei..12=Adar(I), 13=Adar II, 1=Nissan..6=Elul.
    """
    year_len = (rosh_hashanah_date(year + 1) - rosh_hashanah_date(year)).days
    leap = is_hebrew_leap_year(year)
    # Year length: 353/383 (deficient: Cheshvan=29, Kislev=29)
    #              354/384 (regular:   Cheshvan=29, Kislev=30)
    #              355/385 (complete:  Cheshvan=30, Kislev=30)
    rem = year_len % 10
    cheshvan_days = 30 if rem == 5 else 29
    kislev_days = 29 if rem == 3 else 30

    months = [
        (7, "Tishrei", 30),
        (8, "Cheshvan", cheshvan_days),
        (9, "Kislev", kislev_days),
        (10, "Teves", 29),
        (11, "Shevat", 30),
    ]
    if leap:
        months.append((12, "Adar I", 30))
        months.append((13, "Adar II", 29))
    else:
        months.append((12, "Adar", 29))
    months.extend([
        (1, "Nissan", 30),
        (2, "Iyar", 29),
        (3, "Sivan", 30),
        (4, "Tammuz", 29),
        (5, "Av", 30),
        (6, "Elul", 29),
    ])
    return months


def build_hebrew_date_map(year: int) -> dict[datetime.date, tuple[int, str, int]]:
    """Map civil date -> (month_num, month_name, day_of_month) for daytime of that civil date."""
    mapping = {}
    cur = rosh_hashanah_date(year)
    for m_num, m_name, m_len in hebrew_year_months(year):
        for d in range(1, m_len + 1):
            mapping[cur] = (m_num, m_name, d)
            cur += datetime.timedelta(days=1)
    return mapping


def get_molad_utc(year: int, month_index_from_tishrei: int) -> datetime.datetime:
    """
    Return the traditional Hebrew calendar molad as a timezone-aware UTC datetime.
    """
    total_months = months_before_hebrew_year(year) + month_index_from_tishrei
    # Beharad = Day 2 (Monday), 5h, 204ch after Sunday 18:00 JMT (Oct 6, 3761 BCE Julian).
    # JD of Saturday Oct 5, 3761 BCE 18:00 = 347995.25 -> Sunday Oct 6 18:00 = 347996.25.
    jd_molad_jmt = 347996.25 + (5 * CHALAKIM_PER_HOUR + 204 + total_months * CHALAKIM_PER_MONTH) / CHALAKIM_PER_DAY
    unix_seconds_jmt = (jd_molad_jmt - 2440587.5) * 86400.0
    unix_seconds_utc = unix_seconds_jmt - JERUSALEM_OFFSET_SECONDS
    return datetime.datetime.fromtimestamp(unix_seconds_utc, tz=UTC)


def is_yom_tov_night(civil_date: datetime.date, heb_m_num: int, heb_day: int) -> str | None:
    """
    Check if the evening starting at sunset on `civil_date` (which is Hebrew night `heb_m_num`, `heb_day`)
    is Shabbos or Yom Tov in Diaspora (NYC) when Kiddush Levanah is normally not recited.
    """
    if civil_date.weekday() == 4:  # Friday night = Leil Shabbos
        return "Shabbos"
    if heb_m_num == 7:
        if heb_day in (1, 2):
            return "Rosh Hashanah"
        if heb_day == 10:
            return "Yom Kippur"
        if heb_day in (15, 16):
            return "Sukkos"
        if heb_day == 22:
            return "Shemini Atzeres"
        if heb_day == 23:
            return "Simchas Torah"
    elif heb_m_num == 1:
        if heb_day in (15, 16, 21, 22):
            return "Pesach"
    elif heb_m_num == 3:
        if heb_day in (6, 7):
            return "Shavuos"
    return None


# ---------------------------------------------------------------------------
# 2. High-Precision Solar Sunset & Topocentric Lunar Position (Meeus)
# ---------------------------------------------------------------------------

DEG = math.pi / 180.0
RAD = 180.0 / math.pi


def dt_to_jd(dt_utc: datetime.datetime) -> float:
    return dt_utc.timestamp() / 86400.0 + 2440587.5


def gmst_deg(jd: float) -> float:
    """Greenwich Mean Sidereal Time in degrees (Meeus Ch. 12)."""
    T = (jd - 2451545.0) / 36525.0
    theta = (
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * T * T
        - (T * T * T) / 38710000.0
    )
    return theta % 360.0


def mean_obliquity_deg(T: float) -> float:
    return 23.439291111 - (46.8150 * T + 0.00059 * T * T - 0.001813 * T * T * T) / 3600.0


def sun_alt_az(dt_utc: datetime.datetime, lat_deg: float, lon_deg: float) -> tuple[float, float, float]:
    """Return (apparent_alt_deg, az_deg, ecliptic_lon_deg) of the Sun."""
    jd = dt_to_jd(dt_utc)
    T = (jd - 2451545.0) / 36525.0
    L0 = (280.46646 + 36000.76983 * T + 0.0003032 * T * T) % 360.0
    M = (357.52911 + 35999.05029 * T - 0.0001537 * T * T) % 360.0
    M_rad = M * DEG
    C = (
        (1.914602 - 0.004817 * T - 0.000014 * T * T) * math.sin(M_rad)
        + (0.019993 - 0.000101 * T) * math.sin(2 * M_rad)
        + 0.000289 * math.sin(3 * M_rad)
    )
    sun_lon = (L0 + C) % 360.0
    omega = 125.04 - 1934.136 * T
    app_lon = sun_lon - 0.00569 - 0.00478 * math.sin(omega * DEG)
    eps = mean_obliquity_deg(T) + 0.00256 * math.cos(omega * DEG)

    lam_r = app_lon * DEG
    eps_r = eps * DEG
    ra = math.atan2(math.cos(eps_r) * math.sin(lam_r), math.cos(lam_r))
    dec = math.asin(math.sin(eps_r) * math.sin(lam_r))

    lst = (gmst_deg(jd) + lon_deg) * DEG
    H = lst - ra
    phi = lat_deg * DEG

    sin_alt = math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(H)
    alt = math.asin(max(-1.0, min(1.0, sin_alt))) * RAD
    az = (math.atan2(math.sin(H), math.cos(H) * math.sin(phi) - math.tan(dec) * math.cos(phi)) * RAD + 180.0) % 360.0
    return alt, az, app_lon


def get_sunset_ny(civil_date: datetime.date, lat_deg: float, lon_deg: float) -> datetime.datetime:
    """Find exact sunset (solar center geometric altitude = -0.8333°) in NY timezone."""
    # Search between 15:30 and 21:30 NY time
    lo = datetime.datetime(civil_date.year, civil_date.month, civil_date.day, 15, 30, tzinfo=NY_TZ).astimezone(UTC)
    hi = datetime.datetime(civil_date.year, civil_date.month, civil_date.day, 21, 30, tzinfo=NY_TZ).astimezone(UTC)
    target = -0.833333  # standard 34' refraction + 16' solar semi-diameter
    for _ in range(30):
        mid = lo + (hi - lo) / 2
        alt, _, _ = sun_alt_az(mid, lat_deg, lon_deg)
        if alt > target:
            lo = mid
        else:
            hi = mid
    return (lo + (hi - lo) / 2).astimezone(NY_TZ)


# Meeus Chapter 47 periodic terms (top terms for <0.01° accuracy)
# (D, M, M', F, coeff_l [1e-6 deg], coeff_r [0.001 km])
_MOON_LR_TERMS = [
    (0, 0, 1, 0, 6288774, -20905355),
    (2, 0, -1, 0, 1274027, -3699111),
    (2, 0, 0, 0, 658314, -2955968),
    (0, 0, 2, 0, 213618, -569925),
    (0, 1, 0, 0, -185116, 48888),
    (0, 0, 0, 2, -114332, -3149),
    (2, 0, -2, 0, 58793, 246158),
    (2, -1, -1, 0, 57066, -152138),
    (2, 0, 1, 0, 53322, -170733),
    (2, -1, 0, 0, 45758, -204586),
    (0, 1, -1, 0, -40923, -129620),
    (1, 0, 0, 0, -34720, 108743),
    (0, 1, 1, 0, -30383, 104755),
    (2, 0, 0, -2, 15327, 10321),
    (0, 0, 1, 2, -12528, 0),
    (0, 0, 1, -2, 10980, 79661),
    (4, 0, -1, 0, 10675, -34782),
    (0, 0, 3, 0, 10034, -23210),
    (4, 0, -2, 0, 8548, -21636),
    (2, 1, -1, 0, -7888, 24208),
    (2, 1, 0, 0, -6766, 30824),
    (1, 0, -1, 0, -5163, -8379),
    (1, 1, 0, 0, 4987, -16675),
    (2, -1, 1, 0, 4036, -12831),
    (2, 0, 2, 0, 3994, -10445),
    (4, 0, 0, 0, 3861, -11650),
    (2, 0, -3, 0, 3665, 14403),
    (0, 1, -2, 0, -2689, -7003),
    (2, 0, -1, 2, -2602, 0),
    (2, -1, -2, 0, 2390, 10056),
]

# (D, M, M', F, coeff_b [1e-6 deg])
_MOON_B_TERMS = [
    (0, 0, 0, 1, 5128122),
    (0, 0, 1, 1, 280602),
    (0, 0, 1, -1, 277693),
    (2, 0, 0, -1, 173237),
    (2, 0, -1, 1, 55413),
    (2, 0, -1, -1, 46271),
    (2, 0, 0, 1, 32573),
    (0, 0, 2, 1, 17198),
    (2, 0, 1, -1, 9266),
    (0, 0, 2, -1, 8822),
    (2, -1, 0, -1, 8216),
    (2, 0, -2, -1, 4324),
    (2, 0, 1, 1, 4200),
    (2, 1, 0, -1, -3359),
    (2, -1, -1, 1, 2463),
    (2, -1, 0, 1, 2211),
    (2, -1, -1, -1, 2065),
    (0, 1, -1, -1, -1870),
    (4, 0, -1, -1, 1828),
    (0, 1, 0, 1, -1794),
]


def moon_alt_az(
    dt_utc: datetime.datetime,
    lat_deg: float,
    lon_deg: float,
    elev_m: float = 25.0,
) -> tuple[float, float, float]:
    """
    Compute topocentric apparent (altitude_deg, azimuth_deg, illumination_pct) of the Moon
    using Meeus Ch. 47 + Ch. 40 (topocentric parallax) + Bennett atmospheric refraction.
    """
    jd = dt_to_jd(dt_utc)
    # Approximate TT = UTC + 69.2s for 2026-2027
    jd_tt = jd + 69.2 / 86400.0
    T = (jd_tt - 2451545.0) / 36525.0
    T2 = T * T
    T3 = T2 * T
    T4 = T3 * T

    Lp = (218.3164477 + 481267.88123421 * T - 0.0015786 * T2 + T3 / 538841.0 - T4 / 65194000.0) % 360.0
    D = (297.8501921 + 445267.1114034 * T - 0.0018819 * T2 + T3 / 545868.0 - T4 / 113065000.0) % 360.0
    M = (357.5291092 + 35999.0502909 * T - 0.0001536 * T2 + T3 / 24490000.0) % 360.0
    Mp = (134.9633964 + 477198.8675055 * T + 0.0087414 * T2 + T3 / 69699.0 - T4 / 14712000.0) % 360.0
    F = (93.2720950 + 483202.0175233 * T - 0.0036539 * T2 - T3 / 3526000.0 + T4 / 863310000.0) % 360.0

    A1 = (119.75 + 131.849 * T) % 360.0
    A2 = (53.09 + 479264.290 * T) % 360.0
    A3 = (313.45 + 481266.484 * T) % 360.0
    E = 1.0 - 0.002516 * T - 0.0000074 * T2

    sum_l = 0.0
    sum_r = 0.0
    for cD, cM, cMp, cF, cl, cr in _MOON_LR_TERMS:
        arg = (cD * D + cM * M + cMp * Mp + cF * F) * DEG
        e_fac = E if abs(cM) == 1 else (E * E if abs(cM) == 2 else 1.0)
        if cl:
            sum_l += cl * e_fac * math.sin(arg)
        if cr:
            sum_r += cr * e_fac * math.cos(arg)

    sum_l += (
        3958.0 * math.sin(A1 * DEG)
        + 1962.0 * math.sin((Lp - F) * DEG)
        + 318.0 * math.sin(A2 * DEG)
    )

    sum_b = 0.0
    for cD, cM, cMp, cF, cb in _MOON_B_TERMS:
        arg = (cD * D + cM * M + cMp * Mp + cF * F) * DEG
        e_fac = E if abs(cM) == 1 else (E * E if abs(cM) == 2 else 1.0)
        sum_b += cb * e_fac * math.sin(arg)

    sum_b += (
        -2235.0 * math.sin(Lp * DEG)
        + 382.0 * math.sin(A3 * DEG)
        + 175.0 * math.sin((A1 - F) * DEG)
        + 175.0 * math.sin((A1 + F) * DEG)
        + 127.0 * math.sin((Lp - Mp) * DEG)
        - 115.0 * math.sin((Lp + Mp) * DEG)
    )

    lam = (Lp + sum_l / 1e6) % 360.0
    beta = sum_b / 1e6
    dist_km = 385000.56 + sum_r / 1000.0

    # Obliquity with nutation
    omega = 125.04452 - 1934.136261 * T
    eps = mean_obliquity_deg(T) + 0.00256 * math.cos(omega * DEG)

    lam_r = lam * DEG
    beta_r = beta * DEG
    eps_r = eps * DEG

    # Geocentric RA and Dec
    ra = math.atan2(
        math.sin(lam_r) * math.cos(eps_r) - math.tan(beta_r) * math.sin(eps_r),
        math.cos(lam_r),
    )
    dec = math.asin(
        math.sin(beta_r) * math.cos(eps_r) + math.cos(beta_r) * math.sin(eps_r) * math.sin(lam_r)
    )

    # Topocentric correction (Meeus Ch. 40)
    sin_pi = 6378.14 / dist_km
    phi = lat_deg * DEG
    u = math.atan(0.99664719 * math.tan(phi))
    rho_sin_phi = 0.99664719 * math.sin(u) + (elev_m / 6378140.0) * math.sin(phi)
    rho_cos_phi = math.cos(u) + (elev_m / 6378140.0) * math.cos(phi)

    lst = (gmst_deg(jd) + lon_deg) * DEG
    H = lst - ra

    dra = math.atan2(
        -rho_cos_phi * sin_pi * math.sin(H),
        math.cos(dec) - rho_cos_phi * sin_pi * math.cos(H),
    )
    ra_topo = ra + dra
    dec_topo = math.atan2(
        (math.sin(dec) - rho_sin_phi * sin_pi) * math.cos(dra),
        math.cos(dec) - rho_cos_phi * sin_pi * math.cos(H),
    )
    H_topo = lst - ra_topo

    sin_alt = math.sin(phi) * math.sin(dec_topo) + math.cos(phi) * math.cos(dec_topo) * math.cos(H_topo)
    alt_deg = math.asin(max(-1.0, min(1.0, sin_alt))) * RAD
    az_deg = (
        math.atan2(
            math.sin(H_topo),
            math.cos(H_topo) * math.sin(phi) - math.tan(dec_topo) * math.cos(phi),
        )
        * RAD
        + 180.0
    ) % 360.0

    # Atmospheric refraction (Bennett's formula) for alt > -1°
    if alt_deg > -1.0:
        refrac_arcmin = 1.02 / math.tan((alt_deg + 10.3 / (alt_deg + 5.11)) * DEG)
        alt_deg += refrac_arcmin / 60.0

    # Illumination percentage from elongation
    _, _, sun_lon = sun_alt_az(dt_utc, lat_deg, lon_deg)
    elong = math.acos(max(-1.0, min(1.0, math.cos(beta_r) * math.cos((lam - sun_lon) * DEG))))
    illum = 50.0 * (1.0 - math.cos(elong))

    return alt_deg, az_deg, illum


def find_moon_rise_set(civil_date: datetime.date, lat_deg: float, lon_deg: float, elev_m: float = 25.0):
    """Find moonrise and moonset between 12:00 PM civil_date and 6:00 AM next day (NY time)."""
    start = datetime.datetime(civil_date.year, civil_date.month, civil_date.day, 12, 0, tzinfo=NY_TZ).astimezone(UTC)
    rise_dt, set_dt = None, None
    step = datetime.timedelta(minutes=10)
    prev_t = start
    prev_alt, _, _ = moon_alt_az(prev_t, lat_deg, lon_deg, elev_m)
    for i in range(1, 18 * 6 + 1):
        cur_t = start + i * step
        cur_alt, _, _ = moon_alt_az(cur_t, lat_deg, lon_deg, elev_m)
        if prev_alt <= 0 < cur_alt and rise_dt is None:
            # Refine with bisection
            lo, hi = prev_t, cur_t
            for _ in range(12):
                mid = lo + (hi - lo) / 2
                a, _, _ = moon_alt_az(mid, lat_deg, lon_deg, elev_m)
                if a <= 0:
                    lo = mid
                else:
                    hi = mid
            rise_dt = (lo + (hi - lo) / 2).astimezone(NY_TZ)
        elif prev_alt > 0 >= cur_alt and set_dt is None:
            lo, hi = prev_t, cur_t
            for _ in range(12):
                mid = lo + (hi - lo) / 2
                a, _, _ = moon_alt_az(mid, lat_deg, lon_deg, elev_m)
                if a > 0:
                    lo = mid
                else:
                    hi = mid
            set_dt = (lo + (hi - lo) / 2).astimezone(NY_TZ)
        prev_t, prev_alt = cur_t, cur_alt
    return rise_dt, set_dt


def compass_direction(az_deg: float) -> str:
    dirs = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW",
    ]
    idx = int(((az_deg % 360) + 11.25) // 22.5) % 16
    return dirs[idx]


def uws_street_direction(az_deg: float) -> str:
    """
    Translate true compass azimuth into intuitive Upper West Side street-grid language.
    Manhattan grid north ("Uptown" along Broadway/Amsterdam) is ~29° east of true north.
    """
    rel = (az_deg - 29.0) % 360
    if rel < 22.5 or rel >= 337.5:
        return "Uptown (along Broadway/Amsterdam)"
    elif rel < 67.5:
        return "Uptown & East (toward Central Park)"
    elif rel < 112.5:
        return "East (toward Amsterdam / Central Park)"
    elif rel < 157.5:
        return "Downtown & East (toward Amsterdam & 90th)"
    elif rel < 202.5:
        return "Downtown (toward W 90th / 89th)"
    elif rel < 247.5:
        return "Downtown & West (toward Broadway & 90th)"
    elif rel < 292.5:
        return "West (toward Broadway / Hudson)"
    else:
        return "Uptown & West (toward Broadway & 92nd)"


def compute_year(
    year: int = 5787,
    shul_lat: float = DEFAULT_SHUL_LAT,
    shul_lon: float = DEFAULT_SHUL_LON,
    shul_elev_m: float = DEFAULT_SHUL_ELEV_M,
    tzeis_minutes: int = 50,
):
    heb_map = build_hebrew_date_map(year)
    # Also include first few days of year+1 in case Elul overlaps
    heb_map.update(build_hebrew_date_map(year + 1))

    months_info = hebrew_year_months(year)
    results = []

    for idx, (m_num, m_name, _m_len) in enumerate(months_info):
        molad_utc = get_molad_utc(year, idx)
        molad_ny = molad_utc.astimezone(NY_TZ)

        earliest_ny = molad_ny + datetime.timedelta(days=3)
        latest_ny = molad_ny + datetime.timedelta(days=15)

        special_note = None
        if m_num == 7:
            # Yom Kippur = 10 Tishrei
            yk_civil = rosh_hashanah_date(year) + datetime.timedelta(days=9)
            yk_tzeis = get_sunset_ny(yk_civil, shul_lat, shul_lon) + datetime.timedelta(minutes=tzeis_minutes)
            if yk_tzeis > earliest_ny:
                earliest_ny = yk_tzeis
                special_note = "Recited after Yom Kippur"
        elif m_num == 5:
            # Find 9 Av
            tb_civil = next(d for d, (mn, _, hd) in heb_map.items() if mn == 5 and hd == 9)
            if tb_civil.weekday() == 5:  # Saturday -> pushed to Sunday 10 Av
                tb_civil += datetime.timedelta(days=1)
            tb_tzeis = get_sunset_ny(tb_civil, shul_lat, shul_lon) + datetime.timedelta(minutes=tzeis_minutes)
            if tb_tzeis > earliest_ny:
                earliest_ny = tb_tzeis
                special_note = "Recited after Tisha B'Av"

        start_d = earliest_ny.date() - datetime.timedelta(days=1)
        end_d = latest_ny.date()

        nights = []
        d = start_d
        while d <= end_d:
            shkiah = get_sunset_ny(d, shul_lat, shul_lon)
            tzeis = shkiah + datetime.timedelta(minutes=tzeis_minutes)
            next_dawn = datetime.datetime(d.year, d.month, d.day, 2, 0, tzinfo=NY_TZ) + datetime.timedelta(days=1)

            win_start = max(tzeis, earliest_ny)
            win_end = min(next_dawn, latest_ny)

            if win_start < win_end and earliest_ny <= datetime.datetime(d.year, d.month, d.day, 23, 59, tzinfo=NY_TZ):
                # Evening on civil date d is the night of Hebrew date of d+1
                heb_m_num, heb_m_name, heb_day = heb_map[d + datetime.timedelta(days=1)]
                yt = is_yom_tov_night(d, heb_m_num, heb_day)
                is_motzaei_shabbos = (d.weekday() == 5)

                eval_time = max(tzeis, earliest_ny)
                alt, az, illum = moon_alt_az(eval_time.astimezone(UTC), shul_lat, shul_lon, shul_elev_m)
                rise_dt, set_dt = find_moon_rise_set(d, shul_lat, shul_lon, shul_elev_m)

                moon_note = None
                if alt <= 0:
                    if rise_dt and tzeis < rise_dt < win_end:
                        eval_time = min(rise_dt + datetime.timedelta(minutes=30), win_end - datetime.timedelta(minutes=5))
                        alt, az, illum = moon_alt_az(eval_time.astimezone(UTC), shul_lat, shul_lon, shul_elev_m)
                        moon_note = f"Rises {rise_dt.strftime('%-I:%M %p')}; pos. at {eval_time.strftime('%-I:%M %p')}"
                    elif set_dt and set_dt <= tzeis:
                        moon_note = f"Sets {set_dt.strftime('%-I:%M %p')} (before tzeis)"
                    else:
                        moon_note = "Below horizon at tzeis"

                window_note = None
                if earliest_ny > tzeis and earliest_ny.date() == d:
                    window_note = f"Opens {earliest_ny.strftime('%-I:%M %p')}"
                elif latest_ny < next_dawn and latest_ny > tzeis:
                    window_note = f"Ends {latest_ny.strftime('%-I:%M %p')}"

                nights.append({
                    "civil_date": d.isoformat(),
                    "day_of_week": d.strftime("%a"),
                    "heb_date_str": f"{heb_day} {heb_m_name}",
                    "heb_day": heb_day,
                    "is_motzaei_shabbos": is_motzaei_shabbos,
                    "yom_tov_or_shabbos": yt,
                    "shkiah": shkiah.isoformat(),
                    "tzeis": tzeis.isoformat(),
                    "eval_time": eval_time.isoformat(),
                    "moon_alt_deg": round(alt, 1),
                    "moon_az_deg": round(az, 1),
                    "moon_compass": compass_direction(az),
                    "moon_uws_dir": uws_street_direction(az),
                    "moon_illum_pct": round(illum, 0),
                    "moon_rise": rise_dt.isoformat() if rise_dt else None,
                    "moon_set": set_dt.isoformat() if set_dt else None,
                    "moon_note": moon_note,
                    "window_note": window_note,
                })

            d += datetime.timedelta(days=1)

        results.append({
            "hebrew_year": year,
            "month_num": m_num,
            "month_name": m_name,
            "molad_ny": molad_ny.isoformat(),
            "earliest_ny": earliest_ny.isoformat(),
            "latest_ny": latest_ny.isoformat(),
            "special_note": special_note,
            "nights": nights,
        })

    return results


if __name__ == "__main__":
    data = compute_year(5787)
    print(f"Rosh Hashanah 5787: {rosh_hashanah_date(5787)} (leap={is_hebrew_leap_year(5787)}, months={len(data)})")
    for m in data:
        print(
            f"{m['month_name']:8s} | Molad: {m['molad_ny'][:16]} | "
            f"Earliest: {m['earliest_ny'][:16]} | Latest: {m['latest_ny'][:16]} | {len(m['nights'])} nights"
        )
