// "Find the Moon Right Now" — instant on-the-spot sky compass + elevation helper.
// Uses pure client-side astronomy (<1 ms, no map-server wait) + optional live DeviceOrientation compass
// + optional 1-tap 3D building check for the user's current spot.

const NowFinder = (() => {
  const DEG = Math.PI / 180;
  let open = false;
  let loc = null;        // { lat, lon, label, fromGps }
  let liveHeading = null; // degrees clockwise from true/magnetic north (0..360)
  let livePitch = null;   // phone tilt elevation above horizon (-90..90)
  let compassActive = false;
  let refreshTimer = null;
  let lastStatus = null;

  const $ = id => document.getElementById(id);

  function normDeg(d) { return ((d % 360) + 360) % 360; }
  function angleDiff(target, current) {
    let d = normDeg(target - current);
    if (d > 180) d -= 360;
    return d; // -180..+180 (+ = turn right, - = turn left)
  }

  function fistsGuide(alt) {
    if (alt < 7) return I18N.t("nowFistHorizon");
    if (alt > 60) return I18N.t("nowFistHigh");
    const n = Math.max(1, Math.round(alt / 10));
    return n === 1 ? I18N.t("nowFist1") : I18N.t("nowFistN", { n });
  }

  function drawCompass() {
    const cv = $("cNow");
    if (!cv || !lastStatus) return;
    const rect = cv.parentElement.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.floor(rect.width * dpr);
    cv.height = Math.floor(rect.height * dpr);
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const w = rect.width, h = rect.height;

    ctx.fillStyle = "#0b1120";
    ctx.fillRect(0, 0, w, h);

    const cx = w * 0.5;
    const cy = h * 0.5;
    const r = Math.min(w, h) * 0.41;
    const rotDeg = compassActive && liveHeading !== null ? -liveHeading : 0;
    const toPt = (azDeg, rad) => {
      const a = (azDeg + rotDeg) * DEG;
      return [cx + Math.sin(a) * rad, cy - Math.cos(a) * rad];
    };

    // Outer dial ring
    ctx.strokeStyle = "#334155";
    ctx.fillStyle = "#0f172a";
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill(); ctx.stroke();

    // Inner altitude rings (30° and 60° visual guides)
    ctx.strokeStyle = "rgba(148,163,184,0.16)";
    ctx.lineWidth = 1;
    for (const frac of [0.33, 0.66]) {
      ctx.beginPath(); ctx.arc(cx, cy, r * frac, 0, Math.PI * 2); ctx.stroke();
    }

    // Degree ticks
    for (let deg = 0; deg < 360; deg += 15) {
      const major = deg % 90 === 0;
      const mid = deg % 45 === 0;
      const [x1, y1] = toPt(deg, r - (major ? 12 : mid ? 8 : 5));
      const [x2, y2] = toPt(deg, r);
      ctx.strokeStyle = major ? "#94a3b8" : "rgba(148,163,184,0.35)";
      ctx.lineWidth = major ? 2 : 1;
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    }

    // Cardinal letters
    ctx.font = "800 14px -apple-system, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const cardinals = [
      [I18N.compass("N"), 0, "#f87171"],
      [I18N.compass("E"), 90, "#cbd5e1"],
      [I18N.compass("S"), 180, "#cbd5e1"],
      [I18N.compass("W"), 270, "#cbd5e1"],
    ];
    for (const [lbl, deg, col] of cardinals) {
      const [lx, ly] = toPt(deg, r - 24);
      ctx.fillStyle = col;
      ctx.fillText(lbl, lx, ly);
    }

    // Phone "forward" indicator at top when live compass is active
    if (compassActive && liveHeading !== null) {
      ctx.fillStyle = "#38bdf8";
      ctx.beginPath();
      ctx.moveTo(cx, cy - r - 10);
      ctx.lineTo(cx - 6, cy - r - 1);
      ctx.lineTo(cx + 6, cy - r - 1);
      ctx.closePath();
      ctx.fill();
    }

    const { az, alt } = lastStatus;
    const isUp = alt > 0;

    // Direction ray from center to Moon azimuth
    const [mxRim, myRim] = toPt(az, r - 4);
    ctx.save();
    ctx.strokeStyle = isUp ? "rgba(253,224,71,0.85)" : "rgba(148,163,184,0.45)";
    ctx.lineWidth = 3;
    if (!isUp) ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(mxRim, myRim); ctx.stroke();
    ctx.restore();

    // Moon disc placed radially by altitude (rim = 0° horizon, center = 90° zenith)
    const radialFrac = isUp ? Math.max(0.1, 1 - alt / 90) : 1.0;
    const [mx, my] = toPt(az, r * radialFrac);
    ctx.save();
    ctx.fillStyle = isUp ? "#fef08a" : "#64748b";
    if (isUp) { ctx.shadowColor = "#fde047"; ctx.shadowBlur = 16; }
    ctx.beginPath(); ctx.arc(mx, my, 10, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = "#0f172a"; ctx.lineWidth = 2; ctx.stroke();
    ctx.restore();

    // Center dot
    ctx.fillStyle = "#38bdf8";
    ctx.beginPath(); ctx.arc(cx, cy, 4, 0, Math.PI * 2); ctx.fill();
  }

  function render() {
    if (!open) return;
    if (!loc) return;
    const settings = typeof readSettingsFromUI === "function" ? readSettingsFromUI() : { minDays: 3, sofZman: "15d", tzeis: 50 };
    const st = Astro.getNowStatus({
      lat: loc.lat,
      lon: loc.lon,
      elevM: (MODEL && SHUL && Math.hypot(loc.lat - PLACE.lat, loc.lon - PLACE.lon) < 0.01) ? SHUL.g / Geo.FT : 25,
      tzName: (MODEL && Math.hypot(loc.lat - PLACE.lat, loc.lon - PLACE.lon) < 0.01) ? MODEL.tz : null,
      minDaysAfterMolad: settings.minDays,
      sofZman: settings.sofZman,
      tzeisMinutes: settings.tzeis,
    });
    lastStatus = st;

    const compLoc = I18N.compass(st.compass);
    $("nowDirVal").textContent = `${compLoc} (${st.az.toFixed(0)}°)`;
    $("nowAltVal").textContent = `${st.alt.toFixed(1)}°`;
    $("nowIllumVal").textContent = `${st.illum}%`;

    // Window status pill
    const hebDisp = I18N.hebDate(st.hebDate);
    const winEl = $("nowWindowPill");
    winEl.className = "now-pill " + (st.inWindow ? "clear" : "neutral");
    winEl.textContent = st.inWindow
      ? I18N.t("nowWindowYes", { heb: hebDisp })
      : I18N.t("nowWindowNo", { heb: hebDisp });

    // Main guidance text
    const guideEl = $("nowGuide");
    if (st.alt <= 0) {
      let extra = "";
      if (st.riseMs) extra = " " + I18N.t("nowRisesAt", { t: Astro.formatTime(st.riseMs, st.tz) }) + ".";
      guideEl.innerHTML = `<span style="color:#fca5a5">${I18N.t("nowBelowHorizon", { alt: st.alt.toFixed(1) })}</span>${extra}`;
    } else {
      let extra = st.setMs ? ` (${I18N.t("nowSetsAt", { t: Astro.formatTime(st.setMs, st.tz) })})` : "";
      guideEl.textContent = I18N.t("nowLookGuide", {
        comp: compLoc,
        az: st.az.toFixed(0),
        alt: st.alt.toFixed(0),
        fists: fistsGuide(st.alt),
      }) + extra;
    }

    // Live steering cue when phone compass is active
    const cueEl = $("nowCue");
    if (compassActive && liveHeading !== null && st.alt > 0) {
      const diff = angleDiff(st.az, liveHeading);
      const absD = Math.abs(Math.round(diff));
      let hTxt = absD <= 10
        ? `<span class="cue-ok">&#10003; ${I18N.t("nowFacingMoon")}</span>`
        : (diff > 0 ? I18N.t("nowTurnRight", { deg: absD }) : I18N.t("nowTurnLeft", { deg: absD }));
      let pTxt = "";
      if (livePitch !== null && absD <= 15) {
        const pd = st.alt - livePitch;
        if (Math.abs(pd) <= 8) pTxt = ` &bull; <span class="cue-ok">${I18N.t("nowAimedAtMoon")}</span>`;
        else pTxt = ` &bull; ${pd > 0 ? I18N.t("nowTiltUp", { deg: Math.round(pd) }) : I18N.t("nowTiltDown", { deg: Math.round(-pd) })}`;
      }
      cueEl.style.display = "block";
      cueEl.innerHTML = hTxt + pTxt;
    } else {
      cueEl.style.display = "none";
    }

    // Altitude bar visual
    const barFill = $("nowAltFill");
    if (barFill) barFill.style.width = `${Math.max(0, Math.min(100, (st.alt / 90) * 100))}%`;

    // Building check section (if MODEL is already loaded for this spot)
    const bBox = $("nowBuildings");
    const samePlace = MODEL && PLACE && Math.hypot(loc.lat - PLACE.lat, loc.lon - PLACE.lon) < 0.004;
    if (samePlace && st.alt > 0.5 && typeof traceRay === "function") {
      const hereTr = traceRay(SHUL.x, SHUL.y, SHUL.g, st.az, st.alt);
      const liveBest = typeof findClosestSpotAt === "function" ? findClosestSpotAt(st.az, st.alt) : null;
      const hereBadge = hereTr.isClear
        ? `<span style="color:#86efac;font-weight:700">${I18N.t("clearWord")} (+${hereTr.clearance.toFixed(1)}°)</span>`
        : `<span style="color:#fca5a5;font-weight:700">${I18N.t("blockedWord")} (${hereTr.clearance >= 0 ? "+" : ""}${hereTr.clearance.toFixed(1)}°)</span>`;
      let bestLine = "";
      if (liveBest && !hereTr.isClear) {
        const w = typeof walkStr === "function" ? walkStr(liveBest.spot.walk_ft) : `${liveBest.spot.walk_ft} ft`;
        bestLine = `<div style="margin-top:4px">${I18N.t("nowClosestNow")} <strong style="color:#86efac">${liveBest.spot.short_name}</strong> (${w}, +${liveBest.trace.clearance.toFixed(1)}°)</div>`;
      } else if (!liveBest && !hereTr.isClear) {
        bestLine = `<div style="margin-top:4px;color:#fca5a5">${I18N.t("nowNoneNearby", { n: MODEL.walkMax.toLocaleString() })}</div>`;
      }
      bBox.innerHTML = `<div class="now-bldg-res"><div>${I18N.t("nowRightHere")} ${hereBadge}</div>${bestLine}</div>`;
    } else if (st.alt > 0.5) {
      bBox.innerHTML = `<button type="button" class="btn secondary now-bldg-btn" id="btnNowCheckBldg">&#127961;&#65039; ${I18N.t("nowCheckBuildings")}</button>`;
      $("btnNowCheckBldg").onclick = () => {
        const target = { lat: loc.lat, lon: loc.lon, name: loc.label || "My location", label: loc.label || `${loc.lat.toFixed(5)}, ${loc.lon.toFixed(5)}` };
        closeModal();
        choosePlace(target);
      };
    } else {
      bBox.innerHTML = "";
    }

    drawCompass();
  }

  function onOrientation(e) {
    let heading = null;
    if (typeof e.webkitCompassHeading === "number" && !Number.isNaN(e.webkitCompassHeading)) {
      heading = e.webkitCompassHeading;
    } else if (typeof e.alpha === "number" && e.alpha !== null) {
      heading = normDeg(360 - e.alpha);
    }
    if (heading !== null) {
      liveHeading = heading;
      if (typeof e.beta === "number" && e.beta !== null) {
        // When holding phone upright facing sky, beta ≈ 90° is horizon, >90° tilts down, <90°? Actually beta=90 is vertical (0° elev), beta=0 is flat (90°? or looking straight up when beta=0 face up)
        // Standard upright aim: holding phone vertical facing forward has beta ≈ 90°; tilting top back to look up decreases beta? No, tilting screen toward user (looking up through back camera) makes beta > 90°.
        // Use a simple estimate when phone is held upright in portrait: elevation ≈ Math.max(-20, Math.min(90, e.beta - 90)) when tilted back, or 90 - e.beta when tilted forward.
        livePitch = null; // keep heading rock-solid without confusing inverted-axis pitch quirks across devices
      }
      if (open) render();
    }
  }

  async function enableCompass() {
    const btn = $("btnNowCompass");
    if (typeof DeviceOrientationEvent === "undefined") {
      $("nowCompassMsg").textContent = I18N.t("nowCompassUnavailable");
      return;
    }
    try {
      if (typeof DeviceOrientationEvent.requestPermission === "function") {
        const res = await DeviceOrientationEvent.requestPermission();
        if (res !== "granted") {
          $("nowCompassMsg").textContent = I18N.t("nowCompassDenied");
          return;
        }
      }
      window.addEventListener("deviceorientationabsolute", onOrientation, true);
      window.addEventListener("deviceorientation", onOrientation, true);
      compassActive = true;
      btn.textContent = "🧭 " + I18N.t("nowCompassActive");
      btn.classList.add("active");
      $("nowCompassMsg").textContent = "";
      render();
    } catch {
      $("nowCompassMsg").textContent = I18N.t("nowCompassDenied");
    }
  }

  function requestGps() {
    if (!navigator.geolocation) {
      $("nowLocInfo").textContent = "Geolocation unavailable";
      return;
    }
    $("nowLocInfo").textContent = I18N.t("nowLocating");
    navigator.geolocation.getCurrentPosition(
      async pos => {
        const { latitude: lat, longitude: lon } = pos.coords;
        loc = { lat, lon, label: `${lat.toFixed(4)}, ${lon.toFixed(4)}`, fromGps: true };
        $("nowLocInfo").textContent = `GPS: ${loc.label}`;
        render();
        const rv = await Geo.reverseGeocode(lat, lon);
        if (loc && loc.fromGps) {
          loc.label = rv.name || rv.label;
          $("nowLocInfo").textContent = `GPS: ${loc.label}`;
        }
      },
      err => {
        if (!loc && PLACE) {
          loc = { lat: PLACE.lat, lon: PLACE.lon, label: PLACE.name, fromGps: false };
          $("nowLocInfo").textContent = I18N.t("nowUsingPlace", { name: PLACE.name });
          render();
        } else if (!loc) {
          $("nowLocInfo").textContent = `GPS error: ${err.message}`;
        }
      },
      { enableHighAccuracy: true, timeout: 12000 }
    );
  }

  function openModal() {
    open = true;
    $("nowOverlay").classList.add("open");
    if (typeof trackEvent === "function") trackEvent("event/find-now", "Find the Moon Now opened");

    if (PLACE) {
      loc = { lat: PLACE.lat, lon: PLACE.lon, label: PLACE.name, fromGps: false };
      $("nowLocInfo").textContent = I18N.t("nowUsingPlace", { name: PLACE.name });
      render();
    } else {
      requestGps();
    }
    clearInterval(refreshTimer);
    refreshTimer = setInterval(render, 15000);
    requestAnimationFrame(drawCompass);
  }

  function closeModal() {
    open = false;
    $("nowOverlay").classList.remove("open");
    clearInterval(refreshTimer);
    refreshTimer = null;
  }

  window.addEventListener("DOMContentLoaded", () => {
    const btnOpen = $("btnFindNow");
    if (btnOpen) btnOpen.onclick = openModal;
    const btnClose = $("btnNowClose");
    if (btnClose) btnClose.onclick = closeModal;
    const btnGps = $("btnNowGps");
    if (btnGps) btnGps.onclick = requestGps;
    const btnComp = $("btnNowCompass");
    if (btnComp) btnComp.onclick = enableCompass;
    $("nowOverlay").addEventListener("click", e => { if (e.target === $("nowOverlay")) closeModal(); });
    window.addEventListener("keydown", e => { if (e.key === "Escape" && open) closeModal(); });
    window.addEventListener("resize", () => { if (open) drawCompass(); });
    if (typeof I18N !== "undefined") I18N.onChange(() => { if (open) render(); });
  });

  return { open: openModal, close: closeModal, render };
})();
