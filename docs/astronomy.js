// Pure-JavaScript Hebrew Calendar, Molad, Kiddush Levanah windows,
// Solar Sunset (Shkiah), and Meeus Topocentric Lunar Position.
// Ported from src/calendar_moon.py with worldwide timezone & Israel/Diaspora support.

const Astro = (() => {
  const DEG = Math.PI / 180.0;
  const RAD = 180.0 / Math.PI;

  const CHALAKIM_PER_HOUR = 1080;
  const CHALAKIM_PER_DAY = 25920;
  const CHALAKIM_PER_MONTH = 29 * CHALAKIM_PER_DAY + 12 * CHALAKIM_PER_HOUR + 793;
  // Jerusalem Mean Time offset from UTC (35.2354° E = 2h 20m 56.496s)
  const JERUSALEM_OFFSET_MS = (2 * 3600 + 20 * 60 + 56.496) * 1000;

  function mod(a, b) {
    return ((a % b) + b) % b;
  }

  function isHebrewLeapYear(year) {
    return mod(year * 7 + 1, 19) < 7;
  }

  function monthsBeforeHebrewYear(year) {
    return Math.floor((235 * year - 234) / 19);
  }

  function hebrewNewYearElapsedDays(year) {
    const months = monthsBeforeHebrewYear(year);
    const totalChalakim = (1 * CHALAKIM_PER_DAY + 5 * CHALAKIM_PER_HOUR + 204) + months * CHALAKIM_PER_MONTH;
    let days = Math.floor(totalChalakim / CHALAKIM_PER_DAY);
    const remChalakim = totalChalakim - days * CHALAKIM_PER_DAY;
    const hours = Math.floor(remChalakim / CHALAKIM_PER_HOUR);
    const chalakim = remChalakim - hours * CHALAKIM_PER_HOUR;

    // 0=Sun, 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat
    let dow = mod(days, 7);

    // Dechiah 1: Molad Zaken (>= 18h = noon)
    if (hours >= 18) {
      days += 1;
      dow = (dow + 1) % 7;
    } else if (!isHebrewLeapYear(year) && dow === 2 && (hours > 9 || (hours === 9 && chalakim >= 204))) {
      // Dechiah 3: GaTRaD
      days += 2;
      dow = (dow + 2) % 7;
    } else if (isHebrewLeapYear(year - 1) && dow === 1 && (hours > 15 || (hours === 15 && chalakim >= 589))) {
      // Dechiah 4: BeTuTaKPaT
      days += 1;
      dow = (dow + 1) % 7;
    }

    // Dechiah 2: Lo ADU Rosh (Sun=0, Wed=3, Fri=5)
    if (dow === 0 || dow === 3 || dow === 5) {
      days += 1;
    }
    return days;
  }

  // Returns UTC midnight Date for 1 Tishrei of Hebrew year
  function roshHashanahUtcDate(year) {
    const days5780 = hebrewNewYearElapsedDays(5780);
    const daysY = hebrewNewYearElapsedDays(year);
    // Anchor: 1 Tishrei 5780 = 2019-09-30
    const anchorMs = Date.UTC(2019, 8, 30);
    return new Date(anchorMs + (daysY - days5780) * 86400000);
  }

  function addUtcDays(utcDate, days) {
    return new Date(utcDate.getTime() + days * 86400000);
  }

  function isoDateStr(utcDate) {
    const y = utcDate.getUTCFullYear();
    const m = String(utcDate.getUTCMonth() + 1).padStart(2, "0");
    const d = String(utcDate.getUTCDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }

  function hebrewYearMonths(year) {
    const rh0 = roshHashanahUtcDate(year);
    const rh1 = roshHashanahUtcDate(year + 1);
    const yearLen = Math.round((rh1 - rh0) / 86400000);
    const leap = isHebrewLeapYear(year);
    const rem = yearLen % 10;
    const cheshvanDays = rem === 5 ? 30 : 29;
    const kislevDays = rem === 3 ? 29 : 30;

    const months = [
      [7, "Tishrei", 30],
      [8, "Cheshvan", cheshvanDays],
      [9, "Kislev", kislevDays],
      [10, "Teves", 29],
      [11, "Shevat", 30],
    ];
    if (leap) {
      months.push([12, "Adar I", 30], [13, "Adar II", 29]);
    } else {
      months.push([12, "Adar", 29]);
    }
    months.push(
      [1, "Nissan", 30],
      [2, "Iyar", 29],
      [3, "Sivan", 30],
      [4, "Tammuz", 29],
      [5, "Av", 30],
      [6, "Elul", 29]
    );
    return months;
  }

  function buildHebrewDateMap(year) {
    const map = new Map();
    let cur = roshHashanahUtcDate(year);
    for (const [mNum, mName, mLen] of hebrewYearMonths(year)) {
      for (let d = 1; d <= mLen; d++) {
        map.set(isoDateStr(cur), { mNum, mName, day: d });
        cur = addUtcDays(cur, 1);
      }
    }
    return map;
  }

  function getMoladUtcMs(year, monthIndexFromTishrei) {
    const totalMonths = monthsBeforeHebrewYear(year) + monthIndexFromTishrei;
    const jdMoladJmt = 347996.25 + (5 * CHALAKIM_PER_HOUR + 204 + totalMonths * CHALAKIM_PER_MONTH) / CHALAKIM_PER_DAY;
    const unixMsJmt = (jdMoladJmt - 2440587.5) * 86400000.0;
    return unixMsJmt - JERUSALEM_OFFSET_MS;
  }

  function isYomTovNight(civilUtcDate, hebMNum, hebDay, isIsrael = false) {
    // getUTCDay(): 0=Sun, 5=Fri, 6=Sat
    if (civilUtcDate.getUTCDay() === 5) return "Shabbos";
    if (hebMNum === 7) {
      if (hebDay === 1 || hebDay === 2) return "Rosh Hashanah";
      if (hebDay === 10) return "Yom Kippur";
      if (hebDay === 15 || (!isIsrael && hebDay === 16)) return "Sukkos";
      if (hebDay === 22) return "Shemini Atzeres";
      if (!isIsrael && hebDay === 23) return "Simchas Torah";
    } else if (hebMNum === 1) {
      if (hebDay === 15 || hebDay === 21 || (!isIsrael && (hebDay === 16 || hebDay === 22))) return "Pesach";
    } else if (hebMNum === 3) {
      if (hebDay === 6 || (!isIsrael && hebDay === 7)) return "Shavuos";
    }
    return null;
  }

  // Approximate Israel check for 1-day vs 2-day Yom Tov
  function isLikelyIsrael(lat, lon) {
    return lat >= 29.45 && lat <= 33.35 && lon >= 34.2 && lon <= 35.9;
  }

  // Approximate current Hebrew year from a JS Date
  function currentHebrewYear(date = new Date()) {
    const gYear = date.getUTCFullYear();
    let hYear = gYear + 3760;
    const rhNext = roshHashanahUtcDate(hYear + 1);
    if (date.getTime() >= rhNext.getTime()) hYear += 1;
    return hYear;
  }

  // ---------------------------------------------------------------------------
  // Astronomy (Meeus Sun & Topocentric Moon)
  // ---------------------------------------------------------------------------
  function msToJd(ms) {
    return ms / 86400000.0 + 2440587.5;
  }

  function gmstDeg(jd) {
    const T = (jd - 2451545.0) / 36525.0;
    const theta =
      280.46061837 +
      360.98564736629 * (jd - 2451545.0) +
      0.000387933 * T * T -
      (T * T * T) / 38710000.0;
    return mod(theta, 360.0);
  }

  function meanObliquityDeg(T) {
    return 23.439291111 - (46.8150 * T + 0.00059 * T * T - 0.001813 * T * T * T) / 3600.0;
  }

  function sunAltAz(ms, latDeg, lonDeg) {
    const jd = msToJd(ms);
    const T = (jd - 2451545.0) / 36525.0;
    const L0 = mod(280.46646 + 36000.76983 * T + 0.0003032 * T * T, 360.0);
    const M = mod(357.52911 + 35999.05029 * T - 0.0001537 * T * T, 360.0);
    const Mr = M * DEG;
    const C =
      (1.914602 - 0.004817 * T - 0.000014 * T * T) * Math.sin(Mr) +
      (0.019993 - 0.000101 * T) * Math.sin(2 * Mr) +
      0.000289 * Math.sin(3 * Mr);
    const sunLon = mod(L0 + C, 360.0);
    const omega = 125.04 - 1934.136 * T;
    const appLon = sunLon - 0.00569 - 0.00478 * Math.sin(omega * DEG);
    const eps = meanObliquityDeg(T) + 0.00256 * Math.cos(omega * DEG);

    const lamR = appLon * DEG;
    const epsR = eps * DEG;
    const ra = Math.atan2(Math.cos(epsR) * Math.sin(lamR), Math.cos(lamR));
    const dec = Math.asin(Math.sin(epsR) * Math.sin(lamR));

    const lst = (gmstDeg(jd) + lonDeg) * DEG;
    const H = lst - ra;
    const phi = latDeg * DEG;

    const sinAlt = Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(H);
    const alt = Math.asin(Math.max(-1.0, Math.min(1.0, sinAlt))) * RAD;
    const az = mod(
      Math.atan2(Math.sin(H), Math.cos(H) * Math.sin(phi) - Math.tan(dec) * Math.cos(phi)) * RAD + 180.0,
      360.0
    );
    return { alt, az, appLon };
  }

  // Find sunset (alt = -0.8333°) for a given civil date (UTC midnight) at any (lat, lon)
  function getSunsetUtcMs(civilUtcDate, latDeg, lonDeg) {
    // Solar noon in UTC is approximately 12:00 - lon/15 hours
    const approxNoonMs = civilUtcDate.getTime() + (12.0 - lonDeg / 15.0) * 3600000.0;
    const target = -0.833333;
    // Scan forward in 30-min steps from solar noon up to +13 hours to bracket sunset
    let prevT = approxNoonMs;
    let prevAlt = sunAltAz(prevT, latDeg, lonDeg).alt;
    for (let step = 1; step <= 26; step++) {
      const curT = approxNoonMs + step * 1800000.0;
      const curAlt = sunAltAz(curT, latDeg, lonDeg).alt;
      if (prevAlt >= target && curAlt < target) {
        let lo = prevT, hi = curT;
        for (let i = 0; i < 24; i++) {
          const mid = 0.5 * (lo + hi);
          if (sunAltAz(mid, latDeg, lonDeg).alt > target) lo = mid;
          else hi = mid;
        }
        return 0.5 * (lo + hi);
      }
      prevT = curT;
      prevAlt = curAlt;
    }
    // Fallback for polar regions (no sunset)
    return approxNoonMs + 6 * 3600000.0;
  }

  // Sunrise (alt = -0.8333°) on a civil date (UTC midnight) at (lat, lon)
  function getSunriseUtcMs(civilUtcDate, latDeg, lonDeg) {
    const approxNoonMs = civilUtcDate.getTime() + (12.0 - lonDeg / 15.0) * 3600000.0;
    const target = -0.833333;
    let prevT = approxNoonMs;
    let prevAlt = sunAltAz(prevT, latDeg, lonDeg).alt;
    for (let step = 1; step <= 26; step++) {
      const curT = approxNoonMs - step * 1800000.0;
      const curAlt = sunAltAz(curT, latDeg, lonDeg).alt;
      if (prevAlt >= target && curAlt < target) {
        let lo = curT, hi = prevT; // alt(lo) < target <= alt(hi)
        for (let i = 0; i < 24; i++) {
          const mid = 0.5 * (lo + hi);
          if (sunAltAz(mid, latDeg, lonDeg).alt < target) lo = mid;
          else hi = mid;
        }
        return 0.5 * (lo + hi);
      }
      prevT = curT;
      prevAlt = curAlt;
    }
    return approxNoonMs - 6 * 3600000.0;
  }

  // Meeus Chapter 47 periodic terms
  const MOON_LR_TERMS = [
    [0, 0, 1, 0, 6288774, -20905355],
    [2, 0, -1, 0, 1274027, -3699111],
    [2, 0, 0, 0, 658314, -2955968],
    [0, 0, 2, 0, 213618, -569925],
    [0, 1, 0, 0, -185116, 48888],
    [0, 0, 0, 2, -114332, -3149],
    [2, 0, -2, 0, 58793, 246158],
    [2, -1, -1, 0, 57066, -152138],
    [2, 0, 1, 0, 53322, -170733],
    [2, -1, 0, 0, 45758, -204586],
    [0, 1, -1, 0, -40923, -129620],
    [1, 0, 0, 0, -34720, 108743],
    [0, 1, 1, 0, -30383, 104755],
    [2, 0, 0, -2, 15327, 10321],
    [0, 0, 1, 2, -12528, 0],
    [0, 0, 1, -2, 10980, 79661],
    [4, 0, -1, 0, 10675, -34782],
    [0, 0, 3, 0, 10034, -23210],
    [4, 0, -2, 0, 8548, -21636],
    [2, 1, -1, 0, -7888, 24208],
    [2, 1, 0, 0, -6766, 30824],
    [1, 0, -1, 0, -5163, -8379],
    [1, 1, 0, 0, 4987, -16675],
    [2, -1, 1, 0, 4036, -12831],
    [2, 0, 2, 0, 3994, -10445],
    [4, 0, 0, 0, 3861, -11650],
    [2, 0, -3, 0, 3665, 14403],
    [0, 1, -2, 0, -2689, -7003],
    [2, 0, -1, 2, -2602, 0],
    [2, -1, -2, 0, 2390, 10056],
  ];

  const MOON_B_TERMS = [
    [0, 0, 0, 1, 5128122],
    [0, 0, 1, 1, 280602],
    [0, 0, 1, -1, 277693],
    [2, 0, 0, -1, 173237],
    [2, 0, -1, 1, 55413],
    [2, 0, -1, -1, 46271],
    [2, 0, 0, 1, 32573],
    [0, 0, 2, 1, 17198],
    [2, 0, 1, -1, 9266],
    [0, 0, 2, -1, 8822],
    [2, -1, 0, -1, 8216],
    [2, 0, -2, -1, 4324],
    [2, 0, 1, 1, 4200],
    [2, 1, 0, -1, -3359],
    [2, -1, -1, 1, 2463],
    [2, -1, 0, 1, 2211],
    [2, -1, -1, -1, 2065],
    [0, 1, -1, -1, -1870],
    [4, 0, -1, -1, 1828],
    [0, 1, 0, 1, -1794],
  ];

  function moonAltAz(ms, latDeg, lonDeg, elevM = 25.0) {
    const jd = msToJd(ms);
    const jdTt = jd + 69.2 / 86400.0;
    const T = (jdTt - 2451545.0) / 36525.0;
    const T2 = T * T, T3 = T2 * T, T4 = T3 * T;

    const Lp = mod(218.3164477 + 481267.88123421 * T - 0.0015786 * T2 + T3 / 538841.0 - T4 / 65194000.0, 360.0);
    const D = mod(297.8501921 + 445267.1114034 * T - 0.0018819 * T2 + T3 / 545868.0 - T4 / 113065000.0, 360.0);
    const M = mod(357.5291092 + 35999.0502909 * T - 0.0001536 * T2 + T3 / 24490000.0, 360.0);
    const Mp = mod(134.9633964 + 477198.8675055 * T + 0.0087414 * T2 + T3 / 69699.0 - T4 / 14712000.0, 360.0);
    const F = mod(93.2720950 + 483202.0175233 * T - 0.0036539 * T2 - T3 / 3526000.0 + T4 / 863310000.0, 360.0);

    const A1 = mod(119.75 + 131.849 * T, 360.0);
    const A2 = mod(53.09 + 479264.290 * T, 360.0);
    const A3 = mod(313.45 + 481266.484 * T, 360.0);
    const E = 1.0 - 0.002516 * T - 0.0000074 * T2;
    const E2 = E * E;

    let sumL = 0.0, sumR = 0.0;
    for (let i = 0; i < MOON_LR_TERMS.length; i++) {
      const t = MOON_LR_TERMS[i];
      const arg = (t[0] * D + t[1] * M + t[2] * Mp + t[3] * F) * DEG;
      const absM = Math.abs(t[1]);
      const eFac = absM === 1 ? E : (absM === 2 ? E2 : 1.0);
      if (t[4]) sumL += t[4] * eFac * Math.sin(arg);
      if (t[5]) sumR += t[5] * eFac * Math.cos(arg);
    }
    sumL += 3958.0 * Math.sin(A1 * DEG) + 1962.0 * Math.sin((Lp - F) * DEG) + 318.0 * Math.sin(A2 * DEG);

    let sumB = 0.0;
    for (let i = 0; i < MOON_B_TERMS.length; i++) {
      const t = MOON_B_TERMS[i];
      const arg = (t[0] * D + t[1] * M + t[2] * Mp + t[3] * F) * DEG;
      const absM = Math.abs(t[1]);
      const eFac = absM === 1 ? E : (absM === 2 ? E2 : 1.0);
      sumB += t[4] * eFac * Math.sin(arg);
    }
    sumB +=
      -2235.0 * Math.sin(Lp * DEG) +
      382.0 * Math.sin(A3 * DEG) +
      175.0 * Math.sin((A1 - F) * DEG) +
      175.0 * Math.sin((A1 + F) * DEG) +
      127.0 * Math.sin((Lp - Mp) * DEG) -
      115.0 * Math.sin((Lp + Mp) * DEG);

    const lam = mod(Lp + sumL / 1e6, 360.0);
    const beta = sumB / 1e6;
    const distKm = 385000.56 + sumR / 1000.0;

    const omega = 125.04452 - 1934.136261 * T;
    const eps = meanObliquityDeg(T) + 0.00256 * Math.cos(omega * DEG);

    const lamR = lam * DEG, betaR = beta * DEG, epsR = eps * DEG;
    const ra = Math.atan2(
      Math.sin(lamR) * Math.cos(epsR) - Math.tan(betaR) * Math.sin(epsR),
      Math.cos(lamR)
    );
    const dec = Math.asin(
      Math.sin(betaR) * Math.cos(epsR) + Math.cos(betaR) * Math.sin(epsR) * Math.sin(lamR)
    );

    // Topocentric correction (Meeus Ch. 40)
    const sinPi = 6378.14 / distKm;
    const phi = latDeg * DEG;
    const u = Math.atan(0.99664719 * Math.tan(phi));
    const rhoSinPhi = 0.99664719 * Math.sin(u) + (elevM / 6378140.0) * Math.sin(phi);
    const rhoCosPhi = Math.cos(u) + (elevM / 6378140.0) * Math.cos(phi);

    const lst = (gmstDeg(jd) + lonDeg) * DEG;
    const H = lst - ra;
    const dra = Math.atan2(
      -rhoCosPhi * sinPi * Math.sin(H),
      Math.cos(dec) - rhoCosPhi * sinPi * Math.cos(H)
    );
    const raTopo = ra + dra;
    const decTopo = Math.atan2(
      (Math.sin(dec) - rhoSinPhi * sinPi) * Math.cos(dra),
      Math.cos(dec) - rhoCosPhi * sinPi * Math.cos(H)
    );
    const HTopo = lst - raTopo;

    const sinAlt = Math.sin(phi) * Math.sin(decTopo) + Math.cos(phi) * Math.cos(decTopo) * Math.cos(HTopo);
    let altDeg = Math.asin(Math.max(-1.0, Math.min(1.0, sinAlt))) * RAD;
    const azDeg = mod(
      Math.atan2(Math.sin(HTopo), Math.cos(HTopo) * Math.sin(phi) - Math.tan(decTopo) * Math.cos(phi)) * RAD + 180.0,
      360.0
    );

    if (altDeg > -1.0) {
      const refracArcmin = 1.02 / Math.tan((altDeg + 10.3 / (altDeg + 5.11)) * DEG);
      altDeg += refracArcmin / 60.0;
    }

    const sunLon = sunAltAz(ms, latDeg, lonDeg).appLon;
    const elong = Math.acos(Math.max(-1.0, Math.min(1.0, Math.cos(betaR) * Math.cos((lam - sunLon) * DEG))));
    const illum = 50.0 * (1.0 - Math.cos(elong));

    return { alt: altDeg, az: azDeg, illum };
  }

  function findMoonRiseSet(civilUtcDate, latDeg, lonDeg, elevM) {
    // Search from local solar noon to +18h
    const startMs = civilUtcDate.getTime() + (12.0 - lonDeg / 15.0) * 3600000.0;
    const stepMs = 10 * 60000;
    let riseMs = null, setMs = null;
    let prevT = startMs;
    let prevAlt = moonAltAz(prevT, latDeg, lonDeg, elevM).alt;
    for (let i = 1; i <= 18 * 6; i++) {
      const curT = startMs + i * stepMs;
      const curAlt = moonAltAz(curT, latDeg, lonDeg, elevM).alt;
      if (prevAlt <= 0 && curAlt > 0 && riseMs === null) {
        let lo = prevT, hi = curT;
        for (let k = 0; k < 12; k++) {
          const mid = 0.5 * (lo + hi);
          if (moonAltAz(mid, latDeg, lonDeg, elevM).alt <= 0) lo = mid;
          else hi = mid;
        }
        riseMs = 0.5 * (lo + hi);
      } else if (prevAlt > 0 && curAlt <= 0 && setMs === null) {
        let lo = prevT, hi = curT;
        for (let k = 0; k < 12; k++) {
          const mid = 0.5 * (lo + hi);
          if (moonAltAz(mid, latDeg, lonDeg, elevM).alt > 0) lo = mid;
          else hi = mid;
        }
        setMs = 0.5 * (lo + hi);
      }
      prevT = curT;
      prevAlt = curAlt;
    }
    return { riseMs, setMs };
  }

  const COMPASS_DIRS = [
    "N", "NNE", "NE", "ENE",
    "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW",
    "W", "WNW", "NW", "NNW",
  ];

  function compassDirection(azDeg) {
    const idx = Math.floor((mod(azDeg, 360) + 11.25) / 22.5) % 16;
    return COMPASS_DIRS[idx];
  }

  // Timezone formatting helpers
  function formatTime(ms, tzName) {
    try {
      return new Intl.DateTimeFormat("en-US", {
        timeZone: tzName,
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      }).format(new Date(ms));
    } catch {
      return new Date(ms).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
    }
  }

  function formatCompactDt(ms, tzName) {
    try {
      return new Intl.DateTimeFormat("en-US", {
        timeZone: tzName,
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      }).format(new Date(ms));
    } catch {
      return new Date(ms).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    }
  }

  function formatCivilDateDisp(utcDate) {
    return new Intl.DateTimeFormat("en-US", {
      timeZone: "UTC",
      weekday: "short",
      month: "short",
      day: "numeric",
      year: "numeric",
    }).format(utcDate);
  }

  function formatCivilDateShort(utcDate) {
    return new Intl.DateTimeFormat("en-US", {
      timeZone: "UTC",
      month: "short",
      day: "numeric",
    }).format(utcDate);
  }

  // Convert local YYYY-MM-DD in timezone `tzName` from a UTC timestamp
  function localIsoDate(ms, tzName) {
    try {
      const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: tzName,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).formatToParts(new Date(ms));
      const y = parts.find(p => p.type === "year").value;
      const m = parts.find(p => p.type === "month").value;
      const d = parts.find(p => p.type === "day").value;
      return `${y}-${m}-${d}`;
    } catch {
      return isoDateStr(new Date(ms));
    }
  }

  function parseIsoUtc(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d));
  }

  function computeYear({
    year = 5787,
    lat,
    lon,
    elevM = 25.0,
    tzName = "America/New_York",
    tzeisMinutes = 50,
    minDaysAfterMolad = 3,
    sofZman = "15d",
    isIsrael = null,
  }) {
    const israelMode = isIsrael !== null ? isIsrael : isLikelyIsrael(lat, lon);
    const hebMap = buildHebrewDateMap(year);
    const nextMap = buildHebrewDateMap(year + 1);
    for (const [k, v] of nextMap.entries()) hebMap.set(k, v);

    const monthsInfo = hebrewYearMonths(year);
    const nights = [];

    for (let idx = 0; idx < monthsInfo.length; idx++) {
      const [mNum, mName] = monthsInfo[idx];
      const moladMs = getMoladUtcMs(year, idx);
      let earliestMs = moladMs + minDaysAfterMolad * 86400000.0;
      let latestMs;
      if (sofZman === "half") {
        // Half of the mean lunar month (29d 12h 793ch) = 14d 18h 396.5ch ≈ 14d 18h 22m (Rema / Maharil)
        latestMs = moladMs + (CHALAKIM_PER_MONTH / 2) * (86400000.0 / CHALAKIM_PER_DAY);
      } else if (sofZman === "lel15") {
        // Through the night of the 15th of the Hebrew month (ends at dawn of the 15th)
        let d14 = null;
        for (const [iso, info] of hebMap.entries()) {
          if (info.mNum === mNum && info.day === 14) { d14 = parseIsoUtc(iso); break; }
        }
        latestMs = d14 ? getSunriseUtcMs(addUtcDays(d14, 1), lat, lon) - 72 * 60000 : moladMs + 15 * 86400000.0;
      } else {
        latestMs = moladMs + 15 * 86400000.0; // 15 full days (Shulchan Aruch)
      }

      if (mNum === 7) {
        // Yom Kippur = 10 Tishrei (9 days after RH)
        const ykCivil = addUtcDays(roshHashanahUtcDate(year), 9);
        const ykTzeisMs = getSunsetUtcMs(ykCivil, lat, lon) + tzeisMinutes * 60000;
        if (ykTzeisMs > earliestMs) earliestMs = ykTzeisMs;
      } else if (mNum === 5) {
        // Find 9 Av
        let tbCivil = null;
        for (const [iso, info] of hebMap.entries()) {
          if (info.mNum === 5 && info.day === 9) {
            tbCivil = parseIsoUtc(iso);
            break;
          }
        }
        if (tbCivil) {
          if (tbCivil.getUTCDay() === 6) tbCivil = addUtcDays(tbCivil, 1); // Sat -> Sun 10 Av
          const tbTzeisMs = getSunsetUtcMs(tbCivil, lat, lon) + tzeisMinutes * 60000;
          if (tbTzeisMs > earliestMs) earliestMs = tbTzeisMs;
        }
      }

      const winEarliest = formatCompactDt(earliestMs, tzName);
      const winLatest = formatCompactDt(latestMs, tzName);

      const startIso = localIsoDate(earliestMs, tzName);
      const endIso = localIsoDate(latestMs, tzName);
      let d = addUtcDays(parseIsoUtc(startIso), -1);
      const endD = parseIsoUtc(endIso);

      while (d.getTime() <= endD.getTime()) {
        const shkiahMs = getSunsetUtcMs(d, lat, lon);
        const tzeisMs = shkiahMs + tzeisMinutes * 60000;
        // Cutoff ~8 hours after sunset (~2 AM)
        const nextDawnMs = shkiahMs + 8.5 * 3600000;

        const winStartMs = Math.max(tzeisMs, earliestMs);
        const winEndMs = Math.min(nextDawnMs, latestMs);

        // Make sure earliestMs isn't past midnight of civil date d
        const lateEveningMs = shkiahMs + 6 * 3600000;
        if (winStartMs < winEndMs && earliestMs <= lateEveningMs) {
          const nextIso = isoDateStr(addUtcDays(d, 1));
          const hebInfo = hebMap.get(nextIso);
          if (hebInfo) {
            const yt = isYomTovNight(d, hebInfo.mNum, hebInfo.day, israelMode);
            if (!yt) {
              const isMotzaeiShabbos = d.getUTCDay() === 6;
              const isYk = mNum === 7 && hebInfo.day === 11;
              const isTb = mNum === 5 && (hebInfo.day === 10 || (hebInfo.day === 11 && d.getUTCDay() === 0));
              const isMotzaei = isMotzaeiShabbos || isYk || isTb;
              const specialTag = isYk ? "Motzaei YK" : (isTb ? "Motzaei 9 Av" : (isMotzaeiShabbos ? "Motzaei Shabbos" : null));

              let evalMs = Math.max(tzeisMs, earliestMs);
              let moon = moonAltAz(evalMs, lat, lon, elevM);
              let moonNote = null;

              if (moon.alt <= 0) {
                const { riseMs, setMs } = findMoonRiseSet(d, lat, lon, elevM);
                if (riseMs && riseMs > tzeisMs && riseMs < winEndMs) {
                  evalMs = Math.min(riseMs + 30 * 60000, winEndMs - 5 * 60000);
                  moon = moonAltAz(evalMs, lat, lon, elevM);
                  moonNote = `Rises ${formatTime(riseMs, tzName)}; pos. at ${formatTime(evalMs, tzName)}`;
                } else if (setMs && setMs <= tzeisMs) {
                  moonNote = `Sets ${formatTime(setMs, tzName)} (before tzeis)`;
                } else {
                  moonNote = "Below horizon at tzeis";
                }
              }

              nights.push({
                id: nights.length,
                hebrew_year: year,
                is_motzaei: isMotzaei,
                month_name: mName,
                win_earliest: winEarliest,
                win_latest: winLatest,
                civil_date: isoDateStr(d),
                date_disp: formatCivilDateDisp(d),
                date_short: formatCivilDateShort(d),
                heb_date: `${hebInfo.day} ${hebInfo.mName}`,
                special_tag: specialTag,
                tzeis_str: formatTime(evalMs, tzName),
                eval_ms: evalMs,
                end_ms: Math.min(getSunriseUtcMs(addUtcDays(d, 1), lat, lon), latestMs),
                latest_ms: latestMs,
                wait_min: 0,
                wait_time_str: null,
                illum_pct: Math.round(moon.illum),
                moon_alt_deg: Math.round(moon.alt * 10) / 10,
                moon_az_deg: Math.round(moon.az * 10) / 10,
                moon_note: moonNote,
                spot: null,
                frames: null, // populated when solved
                solved: false,
              });
            }
          }
        }
        d = addUtcDays(d, 1);
      }
    }
    return nights;
  }

  // Instant status for "Find the Moon Right Now" at arbitrary (lat, lon, nowMs)
  function getNowStatus({ lat, lon, elevM = 25, tzName = null, minDaysAfterMolad = 3, sofZman = "15d", tzeisMinutes = 50, nowMs = Date.now() }) {
    const tz = tzName || Intl.DateTimeFormat().resolvedOptions().timeZone;
    const moon = moonAltAz(nowMs, lat, lon, elevM);
    const localIso = localIsoDate(nowMs, tz);
    const dCivil = parseIsoUtc(localIso);
    const sunsetMs = getSunsetUtcMs(dCivil, lat, lon);
    const isAfterSunset = nowMs >= sunsetMs;
    const hebDateIso = isAfterSunset ? isoDateStr(addUtcDays(dCivil, 1)) : localIso;

    const hYear = currentHebrewYear(new Date(nowMs));
    const hebMap = buildHebrewDateMap(hYear);
    for (const [k, v] of buildHebrewDateMap(hYear - 1).entries()) if (!hebMap.has(k)) hebMap.set(k, v);
    for (const [k, v] of buildHebrewDateMap(hYear + 1).entries()) if (!hebMap.has(k)) hebMap.set(k, v);
    const hebInfo = hebMap.get(hebDateIso) || { mNum: 0, mName: "", day: 0 };

    // Check if nowMs is inside any Kiddush Levanah window around hYear
    let inWindow = false;
    for (const y of [hYear - 1, hYear, hYear + 1]) {
      const mList = hebrewYearMonths(y);
      for (let idx = 0; idx < mList.length; idx++) {
        const [mNum] = mList[idx];
        const moladMs = getMoladUtcMs(y, idx);
        let earliestMs = moladMs + minDaysAfterMolad * 86400000.0;
        let latestMs;
        if (sofZman === "half") latestMs = moladMs + (CHALAKIM_PER_MONTH / 2) * (86400000.0 / CHALAKIM_PER_DAY);
        else if (sofZman === "lel15") {
          let d14 = null;
          for (const [iso, info] of hebMap.entries()) { if (info.mNum === mNum && info.day === 14) { d14 = parseIsoUtc(iso); break; } }
          latestMs = d14 ? getSunriseUtcMs(addUtcDays(d14, 1), lat, lon) - 72 * 60000 : moladMs + 15 * 86400000.0;
        } else latestMs = moladMs + 15 * 86400000.0;

        if (mNum === 7) {
          const ykTzeis = getSunsetUtcMs(addUtcDays(roshHashanahUtcDate(y), 9), lat, lon) + tzeisMinutes * 60000;
          if (ykTzeis > earliestMs) earliestMs = ykTzeis;
        }
        if (nowMs >= earliestMs && nowMs <= latestMs) { inWindow = true; break; }
      }
      if (inWindow) break;
    }

    // Find next moonrise / moonset over next 24h from nowMs
    const stepMs = 15 * 60000;
    let riseMs = null, setMs = null;
    let prevT = nowMs, prevAlt = moon.alt;
    for (let i = 1; i <= 96; i++) {
      const curT = nowMs + i * stepMs;
      const curAlt = moonAltAz(curT, lat, lon, elevM).alt;
      if (prevAlt <= 0 && curAlt > 0 && riseMs === null) {
        let lo = prevT, hi = curT;
        for (let k = 0; k < 10; k++) { const mid = 0.5 * (lo + hi); if (moonAltAz(mid, lat, lon, elevM).alt <= 0) lo = mid; else hi = mid; }
        riseMs = 0.5 * (lo + hi);
      } else if (prevAlt > 0 && curAlt <= 0 && setMs === null) {
        let lo = prevT, hi = curT;
        for (let k = 0; k < 10; k++) { const mid = 0.5 * (lo + hi); if (moonAltAz(mid, lat, lon, elevM).alt > 0) lo = mid; else hi = mid; }
        setMs = 0.5 * (lo + hi);
      }
      if (riseMs && setMs) break;
      prevT = curT; prevAlt = curAlt;
    }

    return {
      alt: moon.alt,
      az: moon.az,
      illum: Math.round(moon.illum),
      compass: compassDirection(moon.az),
      hebDate: hebInfo.day ? `${hebInfo.day} ${hebInfo.mName}` : "",
      inWindow,
      riseMs,
      setMs,
      tz,
    };
  }

  return {
    DEG,
    RAD,
    currentHebrewYear,
    isLikelyIsrael,
    moonAltAz,
    compassDirection,
    formatTime,
    computeYear,
    getNowStatus,
  };
})();
