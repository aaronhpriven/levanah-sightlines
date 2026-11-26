// 3D viewer: building model, first-person view, elevation cross-section and time slider.
// Generated from src/build_interactive_calendar.py (YIWS viewer) with location-specific values made generic.

// ---------------- 3D VIEWER STATE ----------------
let nightIdx = 0;
let frameIdx = 0;
let activeView = "spot";
let spotMode = "stable"; // "stable" (30-min spot) or "live" (closest right now)
let playTimer = null;
let curNight = null;
let curActiveSpot = null;
let curShulTrace = null;
let curSpotTrace = null;
let localBuildings = [];
let fpCenterAz = 100;

const overlay = document.getElementById("viewerOverlay");
const c3d = document.getElementById("c3d");
const cFp = document.getElementById("cFp");
const cProf = document.getElementById("cProf");
const slider = document.getElementById("timeSlider");
const btnPlay = document.getElementById("btnPlay");

let cam = { targetX: 0, targetY: 0, targetZ: 120, yaw: -145 * DEG, pitch: 34 * DEG, dist: 1050, fov: 52 * DEG };

function stopPlay() {
  if (playTimer) {
    clearInterval(playTimer);
    playTimer = null;
    btnPlay.innerHTML = "&#9654; Play";
    btnPlay.classList.remove("active");
  }
}

function openViewer(id) {
  stopPlay();
  nightIdx = id;
  curNight = NIGHTS[id];
  frameIdx = 0;
  slider.value = 0;
  activeView = curNight.spot ? "spot" : "shul";

  // Pre-filter nearby buildings around shul & spot for ultra-fast 60fps 3D orbit
  const sx = curNight.spot ? curNight.spot.x : SHUL.x;
  const sy = curNight.spot ? curNight.spot.y : SHUL.y;
  localBuildings = BUILDINGS.filter(b =>
    Math.hypot(b.cx - sx, b.cy - sy) < 1100 || Math.hypot(b.cx - SHUL.x, b.cy - SHUL.y) < 1100
  );
  fpCenterAz = curNight.frames[15][0];

  document.getElementById("tickStart").textContent = curNight.wait_min
    ? `+${curNight.wait_min}m (${curNight.frames[0][2]})`
    : `Tzeis (${curNight.frames[0][2]})`;
  document.getElementById("tickEnd").textContent = `+30m (${curNight.frames[30][2]})`;

  document.getElementById("legEst").style.display = BUILDINGS.some(b => b.est === "default") ? "flex" : "none";
  document.getElementById("btnFpShul").textContent = PLACE.atLabel;
  overlay.classList.add("open");
  setPreset("iso", false);
  recomputeAndRender();
  requestAnimationFrame(() => recomputeAndRender());
}

function closeViewer() {
  stopPlay();
  overlay.classList.remove("open");
}

document.getElementById("btnBack").onclick = closeViewer;
document.getElementById("btnPrev").onclick = () => {
  const list = getFilteredNights();
  const pos = list.findIndex(n => n.id === nightIdx);
  const prev = list[(pos - 1 + list.length) % list.length];
  if (prev) openViewer(prev.id);
};
document.getElementById("btnNext").onclick = () => {
  const list = getFilteredNights();
  const pos = list.findIndex(n => n.id === nightIdx);
  const next = list[(pos + 1) % list.length];
  if (next) openViewer(next.id);
};
window.addEventListener("keydown", e => { if (e.key === "Escape" && overlay.classList.contains("open")) closeViewer(); });

function recomputeAndRender() {
  if (!curNight) return;
  const fr = curNight.frames[frameIdx];
  const [az, alt, timeStr, compass] = fr;
  curShulTrace = traceRay(SHUL.x, SHUL.y, SHUL.g, az, alt);

  if (spotMode === "live") {
    const liveRes = findClosestSpotAt(az, alt);
    if (liveRes) {
      curActiveSpot = liveRes.spot;
      curSpotTrace = liveRes.trace;
    } else {
      curActiveSpot = null;
      curSpotTrace = null;
    }
  } else {
    curActiveSpot = curNight.spot;
    curSpotTrace = curActiveSpot
      ? traceRay(curActiveSpot.x, curActiveSpot.y, curActiveSpot.g, az, alt)
      : null;
  }

  // Ensure localBuildings covers the active spot as well as the shul
  const sx = curActiveSpot ? curActiveSpot.x : SHUL.x;
  const sy = curActiveSpot ? curActiveSpot.y : SHUL.y;
  localBuildings = BUILDINGS.filter(b =>
    Math.hypot(b.cx - sx, b.cy - sy) < 1100 || Math.hypot(b.cx - SHUL.x, b.cy - SHUL.y) < 1100
  );

  // Update header & pills
  const tagPart = curNight.special_tag ? ` — ${curNight.special_tag}` : "";
  document.getElementById("vTitle").textContent = `${curNight.date_disp} (${curNight.heb_date} ${curNight.hebrew_year})${tagPart}`;
  const waitTxt = curNight.wait_min ? ` • Showing +${curNight.wait_min}m clear window` : "";
  document.getElementById("vSub").textContent = `${PLACE.label} • Tzeis ${curNight.tzeis_str} • ${curNight.illum_pct}% lit${waitTxt}`;

  document.getElementById("lblTime").textContent = `${timeStr} (+${frameIdx} min)`;
  document.getElementById("lblMoon").innerHTML = `Moon: <strong>${compass} (${az.toFixed(1)}&deg;)</strong> &bull; Alt <strong>${alt.toFixed(1)}&deg;</strong>`;

  const modeLbl = spotMode === "live" ? "Closest Now" : `${SETTINGS.clearMin}-Min Spot`;
  const pillSpot = document.getElementById("pillSpot");
  const btnFpSpot = document.getElementById("btnFpSpot");
  const btnProfSpot = document.getElementById("btnProfSpot");
  if (curSpotTrace && curActiveSpot) {
    const sc = curSpotTrace.clearance;
    const walkTag = curActiveSpot.walk_ft <= 20 ? "0 ft" : `${curActiveSpot.walk_ft.toLocaleString()} ft`;
    pillSpot.style.display = "flex";
    btnFpSpot.style.display = "inline-block";
    btnProfSpot.style.display = "inline-block";
    pillSpot.className = "pill " + (curSpotTrace.isClear ? "clear" : "blocked");
    pillSpot.innerHTML = `<span>${modeLbl}:</span> <strong>${curActiveSpot.short_name}</strong> (${walkTag}, <strong>${sc >= 0 ? "+" : ""}${sc.toFixed(1)}&deg;</strong>)`;
    document.getElementById("legSpot").textContent = `${modeLbl}: ${curActiveSpot.short_name} (${sc >= 0 ? "+" : ""}${sc.toFixed(1)}°)`;
    btnFpSpot.textContent = modeLbl;
    btnProfSpot.textContent = `${modeLbl} (${sc >= 0 ? "+" : ""}${sc.toFixed(1)}°)`;
    btnFpSpot.className = "ctrl " + (activeView === "spot" ? (curSpotTrace.isClear ? "active-green" : "active-red") : "");
    btnProfSpot.className = "ctrl " + (activeView === "spot" ? (curSpotTrace.isClear ? "active-green" : "active-red") : "");
  } else {
    pillSpot.style.display = "flex";
    pillSpot.className = "pill blocked";
    pillSpot.innerHTML = `<span>${modeLbl}:</span> <strong>No clear spot within ${MODEL.walkMax.toLocaleString()} ft</strong>`;
    btnFpSpot.style.display = "none";
    btnProfSpot.style.display = "none";
    document.getElementById("legSpot").textContent = `No Clear Spot Within ${MODEL.walkMax.toLocaleString()} ft`;
  }

  const shc = curShulTrace.clearance;
  const pillShul = document.getElementById("pillShul");
  pillShul.className = "pill " + (curShulTrace.isClear ? "clear" : "blocked");
  pillShul.innerHTML = `<span>${PLACE.atLabel}:</span> <strong>${curShulTrace.isClear ? "Clear" : "Blocked"} (${shc >= 0 ? "+" : ""}${shc.toFixed(1)}&deg;)</strong>`;
  document.getElementById("legShul").textContent = `${PLACE.atLabel} (${shc >= 0 ? "+" : ""}${shc.toFixed(1)}°)`;
  document.getElementById("btnProfShul").textContent = `${PLACE.atLabel} (${shc >= 0 ? "+" : ""}${shc.toFixed(1)}°)`;
  document.getElementById("btnFpShul").className = "ctrl " + (activeView === "shul" ? (curShulTrace.isClear ? "active-green" : "active-red") : "");
  document.getElementById("btnProfShul").className = "ctrl " + (activeView === "shul" ? (curShulTrace.isClear ? "active-green" : "active-red") : "");
  document.getElementById("profTitle").innerHTML = `2D Elevation Cross-Section Along Azimuth ${az.toFixed(1)}&deg; (${compass}) <span class="hint">&bull; Dashed cap = +4 ft parapet</span>`;

  draw3D();
  drawFirstPerson();
  drawProfile();
}

// ---------------- CANVAS HELPERS ----------------
function resizeCanvas(canvas) {
  const rect = canvas.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { w: rect.width, h: rect.height, ctx };
}

function project3D(x, y, z, w, h, camPos, basis, f) {
  const rx = x - camPos.x, ry = y - camPos.y, rz = z - camPos.z;
  const cx = rx * basis.rx + ry * basis.ry + rz * basis.rz;
  const cy = rx * basis.ux + ry * basis.uy + rz * basis.uz;
  const cz = rx * basis.fx + ry * basis.fy + rz * basis.fz;
  if (cz <= 5) return null;
  return { sx: w * 0.5 + (cx / cz) * f, sy: h * 0.5 - (cy / cz) * f, cz };
}

function makeCameraBasis(camPos, tx, ty, tz) {
  let fx = tx - camPos.x, fy = ty - camPos.y, fz = tz - camPos.z;
  const fl = Math.hypot(fx, fy, fz) || 1;
  fx /= fl; fy /= fl; fz /= fl;
  let rx = fy, ry = -fx, rz = 0;
  let rl = Math.hypot(rx, ry, rz);
  if (rl < 1e-4) { rx = 1; ry = 0; rz = 0; rl = 1; }
  rx /= rl; ry /= rl; rz /= rl;
  return { fx, fy, fz, rx, ry, rz, ux: ry * fz - rz * fy, uy: rz * fx - rx * fz, uz: rx * fy - ry * fx };
}

function draw3D() {
  if (!curNight || !curShulTrace) return;
  const { w, h, ctx } = resizeCanvas(c3d);
  const [az, alt] = curNight.frames[frameIdx];
  const rayDx = Math.sin(az * DEG), rayDy = Math.cos(az * DEG);
  const tanAlt = Math.tan(Math.max(0.5, alt) * DEG);

  ctx.fillStyle = "#0b1120";
  ctx.fillRect(0, 0, w, h);

  const camPos = {
    x: cam.targetX - Math.cos(cam.pitch) * Math.sin(cam.yaw) * cam.dist,
    y: cam.targetY - Math.cos(cam.pitch) * Math.cos(cam.yaw) * cam.dist,
    z: cam.targetZ + Math.sin(cam.pitch) * cam.dist,
  };
  const basis = makeCameraBasis(camPos, cam.targetX, cam.targetY, cam.targetZ);
  const f = (h * 0.5) / Math.tan(cam.fov * 0.5);

  ctx.strokeStyle = "rgba(148, 163, 184, 0.24)";
  ctx.lineWidth = 1.3;
  for (const pts of MODEL.streetsDraw) {
    ctx.beginPath();
    let started = false;
    for (const pt of pts) {
      const p = project3D(pt[0], pt[1], SHUL.g + 1, w, h, camPos, basis, f);
      if (!p) { started = false; continue; }
      if (!started) { ctx.moveTo(p.sx, p.sy); started = true; }
      else ctx.lineTo(p.sx, p.sy);
    }
    ctx.stroke();
  }

  const blockId = !curShulTrace.isClear ? curShulTrace.blockingId : null;
  const limitId = curSpotTrace ? curSpotTrace.limitingId : null;

  const sortedB = localBuildings.map(b => ({
    b,
    d2: (b.cx - camPos.x) ** 2 + (b.cy - camPos.y) ** 2 + ((b.g + b.h * 0.5) - camPos.z) ** 2,
  })).sort((a, b) => b.d2 - a.d2);

  for (const { b } of sortedB) {
    const pts = b.pts;
    const isBlock = (b.id === blockId);
    const isLimit = (b.id === limitId && !isBlock);
    const botP = [], topP = [];
    let anyVis = false;
    for (let i = 0; i < pts.length; i++) {
      const pb = project3D(pts[i][0], pts[i][1], b.g, w, h, camPos, basis, f);
      const pt = project3D(pts[i][0], pts[i][1], b.top, w, h, camPos, basis, f);
      botP.push(pb); topP.push(pt);
      if (pb || pt) anyVis = true;
    }
    if (!anyVis) continue;

    const hNorm = Math.min(1, b.h / 260);
    let wallFill, roofFill, strokeCol;
    if (isBlock) {
      wallFill = "rgba(220,38,38,0.85)"; roofFill = "rgba(248,113,113,0.92)"; strokeCol = "#fecaca";
    } else if (isLimit) {
      wallFill = "rgba(217,119,6,0.82)"; roofFill = "rgba(251,191,36,0.9)"; strokeCol = "#fef08a";
    } else {
      if (b.est === "default") {
        wallFill = "rgba(76,64,120,0.80)"; roofFill = "rgba(110,95,165,0.88)"; strokeCol = "rgba(167,139,250,0.35)";
      } else {
        const r = Math.round(35 + hNorm * 35), g = Math.round(48 + hNorm * 45), bl = Math.round(72 + hNorm * 65);
        wallFill = `rgba(${r},${g},${bl},0.82)`;
        roofFill = `rgba(${r+25},${g+28},${bl+35},0.90)`;
        strokeCol = "rgba(148,163,184,0.22)";
      }
    }

    const walls = [];
    for (let i = 0; i < pts.length - 1; i++) {
      const b0 = botP[i], b1 = botP[i+1], t0 = topP[i], t1 = topP[i+1];
      if (!b0 || !b1 || !t0 || !t1) continue;
      walls.push({ b0, b1, t0, t1, avgZ: (b0.cz + b1.cz + t0.cz + t1.cz) * 0.25 });
    }
    walls.sort((a, b) => b.avgZ - a.avgZ);

    ctx.lineWidth = isBlock || isLimit ? 1.2 : 0.6;
    ctx.strokeStyle = strokeCol;
    ctx.fillStyle = wallFill;
    for (const wl of walls) {
      ctx.beginPath();
      ctx.moveTo(wl.b0.sx, wl.b0.sy); ctx.lineTo(wl.b1.sx, wl.b1.sy);
      ctx.lineTo(wl.t1.sx, wl.t1.sy); ctx.lineTo(wl.t0.sx, wl.t0.sy);
      ctx.closePath(); ctx.fill(); ctx.stroke();
    }
    if (topP.every(p => p !== null)) {
      ctx.fillStyle = roofFill;
      ctx.beginPath();
      ctx.moveTo(topP[0].sx, topP[0].sy);
      for (let i = 1; i < topP.length; i++) ctx.lineTo(topP[i].sx, topP[i].sy);
      ctx.closePath(); ctx.fill(); ctx.stroke();
    }
  }

  function drawRay3D(ox, oy, oz, len, color, width, dashed=false) {
    ctx.save();
    ctx.strokeStyle = color; ctx.lineWidth = width;
    if (dashed) ctx.setLineDash([6, 4]);
    ctx.beginPath();
    let started = false;
    for (let i = 0; i <= 28; i++) {
      const t = len * i / 28;
      const p = project3D(ox + rayDx * t, oy + rayDy * t, oz + t * tanAlt, w, h, camPos, basis, f);
      if (!p) { started = false; continue; }
      if (!started) { ctx.moveTo(p.sx, p.sy); started = true; }
      else ctx.lineTo(p.sx, p.sy);
    }
    ctx.stroke();
    ctx.restore();
  }

  const fb = curShulTrace.firstBlock;
  if (fb) {
    drawRay3D(SHUL.x, SHUL.y, curShulTrace.oz, fb.tEnter, "#ef4444", 3.2, false);
    drawRay3D(SHUL.x + rayDx * fb.tEnter, SHUL.y + rayDy * fb.tEnter, curShulTrace.oz + fb.tEnter * tanAlt, 900 - fb.tEnter, "rgba(239,68,68,0.4)", 2, true);
    const hp = project3D(SHUL.x + rayDx * fb.tEnter, SHUL.y + rayDy * fb.tEnter, curShulTrace.oz + fb.tEnter * tanAlt, w, h, camPos, basis, f);
    if (hp) {
      ctx.fillStyle = "#fef08a"; ctx.strokeStyle = "#dc2626"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(hp.sx, hp.sy, 5.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    }
  } else {
    drawRay3D(SHUL.x, SHUL.y, curShulTrace.oz, 900, curShulTrace.isClear ? "#38bdf8" : "#f59e0b", 3.2, false);
  }

  if (curSpotTrace && curActiveSpot) {
    const sp = curActiveSpot;
    drawRay3D(sp.x, sp.y, curSpotTrace.oz, 950, curSpotTrace.isClear ? "#22c55e" : "#ef4444", 3.8, false);
    const mp = project3D(sp.x + rayDx * 950, sp.y + rayDy * 950, curSpotTrace.oz + 950 * tanAlt, w, h, camPos, basis, f);
    if (mp) {
      ctx.fillStyle = "#fef08a"; ctx.shadowColor = "#fde047"; ctx.shadowBlur = 14;
      ctx.beginPath(); ctx.arc(mp.sx, mp.sy, 8, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
    }
  }

  const pinBoxes = [];
  function drawPin(x, y, z, label, col, labelDy) {
    const p = project3D(x, y, z, w, h, camPos, basis, f);
    if (!p) return;
    ctx.fillStyle = col; ctx.strokeStyle = "#fff"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(p.sx, p.sy, 6, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    ctx.font = "700 11px -apple-system, sans-serif";
    const tw = ctx.measureText(label).width;
    const rx = p.sx + 9, ry = p.sy + labelDy;
    ctx.fillStyle = "rgba(15,23,42,0.88)";
    ctx.fillRect(rx, ry, tw + 10, 18);
    ctx.fillStyle = "#f8fafc";
    ctx.fillText(label, rx + 5, ry + 13);
    pinBoxes.push({ x0: p.sx - 12, y0: Math.min(p.sy - 12, ry - 4), x1: rx + tw + 16, y1: Math.max(p.sy + 12, ry + 22) });
  }
  drawPin(SHUL.x, SHUL.y, curShulTrace.oz, PLACE.pinLabel, "#3b82f6", 10);
  if (curActiveSpot && curActiveSpot.walk_ft > 10) {
    drawPin(curActiveSpot.x, curActiveSpot.y, curSpotTrace.oz, curActiveSpot.short_name, "#22c55e", -22);
  }

  // Draw 3D street name labels (at most 1 per unique street, closest to viewport center, no pin overlap)
  ctx.font = "600 10px -apple-system, sans-serif";
  const bestPerStreet = new Map();
  for (const sl of MODEL.streetLabels) {
    const p = project3D(sl[1], sl[2], SHUL.g + 8, w, h, camPos, basis, f);
    if (!p || p.cz > 1850 || p.sx < 45 || p.sx > w - 85 || p.sy < 22 || p.sy > h - 25) continue;
    if (p.sx < 215 && p.sy > h - 108) continue;
    if (p.sx > w - 105 && p.sy < 105) continue;
    if (pinBoxes.some(b => p.sx + 36 > b.x0 && p.sx - 36 < b.x1 && p.sy + 10 > b.y0 && p.sy - 10 < b.y1)) continue;
    const centerDist = Math.hypot(p.sx - w * 0.5, p.sy - h * 0.5);
    const prev = bestPerStreet.get(sl[0]);
    if (!prev || centerDist < prev.centerDist) {
      bestPerStreet.set(sl[0], { name: sl[0], sx: p.sx, sy: p.sy, centerDist });
    }
  }
  const placedLabels = [];
  for (const item of [...bestPerStreet.values()].sort((a, b) => a.centerDist - b.centerDist)) {
    if (placedLabels.some(q => Math.abs(q.x - item.sx) < 68 && Math.abs(q.y - item.sy) < 20)) continue;
    placedLabels.push({ x: item.sx, y: item.sy });
    const tw = ctx.measureText(item.name).width;
    ctx.fillStyle = "rgba(15, 23, 42, 0.78)";
    ctx.fillRect(item.sx - tw * 0.5 - 4, item.sy - 7, tw + 8, 14);
    ctx.fillStyle = "#cbd5e1";
    ctx.fillText(item.name, item.sx - tw * 0.5, item.sy + 3.5);
  }

  // Draw live rotating compass rose (top-right)
  const cx = w - 46, cy = 46, r = 32;
  ctx.save();
  ctx.fillStyle = "rgba(15, 23, 42, 0.88)";
  ctx.strokeStyle = "#334155";
  ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill(); ctx.stroke();

  // Helper: map world azimuth (0=N, 90=E) to compass canvas (x, y) given current cam.yaw
  const compPt = (azRad, rad) => {
    const rel = azRad - cam.yaw;
    return [cx + Math.sin(rel) * rad, cy - Math.cos(rel) * rad];
  };

  // Subtle crosshairs
  ctx.strokeStyle = "rgba(148, 163, 184, 0.22)";
  ctx.lineWidth = 1;
  const [nx0, ny0] = compPt(0, r - 11), [sx0, sy0] = compPt(Math.PI, r - 11);
  const [ex0, ey0] = compPt(Math.PI * 0.5, r - 11), [wx0, wy0] = compPt(Math.PI * 1.5, r - 11);
  ctx.beginPath(); ctx.moveTo(nx0, ny0); ctx.lineTo(sx0, sy0); ctx.moveTo(ex0, ey0); ctx.lineTo(wx0, wy0); ctx.stroke();

  // North red needle
  const [ntx, nty] = compPt(0, r - 10);
  const [nlx, nly] = compPt(Math.PI * 0.5, 4);
  const [nrx, nry] = compPt(Math.PI * 1.5, 4);
  ctx.fillStyle = "#ef4444";
  ctx.beginPath(); ctx.moveTo(ntx, nty); ctx.lineTo(nlx, nly); ctx.lineTo(nrx, nry); ctx.closePath(); ctx.fill();

  // South gray needle
  const [stx, sty] = compPt(Math.PI, r - 12);
  ctx.fillStyle = "#64748b";
  ctx.beginPath(); ctx.moveTo(stx, sty); ctx.lineTo(nlx, nly); ctx.lineTo(nrx, nry); ctx.closePath(); ctx.fill();

  // Moon azimuth marker on compass rim
  const [mmx, mmy] = compPt(az * DEG, r - 2);
  ctx.fillStyle = "#fde047";
  ctx.strokeStyle = "#0f172a";
  ctx.lineWidth = 1.2;
  ctx.beginPath(); ctx.arc(mmx, mmy, 4.2, 0, Math.PI * 2); ctx.fill(); ctx.stroke();

  // Cardinal labels
  ctx.font = "700 9.5px -apple-system, sans-serif";
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  const cardinals = [["N", 0, "#f87171"], ["E", Math.PI * 0.5, "#94a3b8"], ["S", Math.PI, "#94a3b8"], ["W", Math.PI * 1.5, "#94a3b8"]];
  for (const [lbl, radA, col] of cardinals) {
    const [lx, ly] = compPt(radA, r - 7);
    ctx.fillStyle = col;
    ctx.fillText(lbl, lx, ly);
  }
  ctx.restore();
}

function drawFirstPerson() {
  const { w, h, ctx } = resizeCanvas(cFp);
  const tr = (activeView === "spot" && curSpotTrace) ? curSpotTrace : curShulTrace;
  const [az, alt] = curNight.frames[frameIdx];
  const ox = tr.ox, oy = tr.oy, oz = tr.oz;

  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, "#020617"); grad.addColorStop(0.55, "#0f172a"); grad.addColorStop(1, "#1e293b");
  ctx.fillStyle = grad; ctx.fillRect(0, 0, w, h);

  const maxAlt = Math.max(52, Math.ceil((Math.max(...curNight.frames.map(f => f[1])) + 12) / 10) * 10);
  const altMin = -4, azSpan = 90;
  const toX = a => { let d = a - fpCenterAz; while (d > 180) d -= 360; while (d < -180) d += 360; return w * 0.5 + (d / azSpan) * w; };
  const toY = e => h - ((e - altMin) / (maxAlt - altMin)) * h;

  ctx.strokeStyle = "rgba(148,163,184,0.16)"; ctx.fillStyle = "#64748b";
  ctx.font = "10px -apple-system, sans-serif"; ctx.lineWidth = 1;
  for (let a = 0; a <= maxAlt; a += 10) {
    const y = toY(a);
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    ctx.fillText(a + "°", 6, y - 3);
  }
  for (let da = -40; da <= 40; da += 10) {
    const x = toX(fpCenterAz + da);
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    if (da === 0) { ctx.fillStyle = "#94a3b8"; ctx.fillText(`${fpCenterAz.toFixed(1)}°`, x + 4, 14); ctx.fillStyle = "#64748b"; }
  }

  // 30-min trajectory arc
  ctx.save();
  ctx.strokeStyle = "rgba(253,224,71,0.45)"; ctx.lineWidth = 1.5; ctx.setLineDash([3, 3]);
  ctx.beginPath();
  curNight.frames.forEach((f, i) => { const px = toX(f[0]), py = toY(f[1]); if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py); });
  ctx.stroke(); ctx.restore();

  // Moon disc behind buildings
  const mx = toX(az), my = toY(alt);
  ctx.save();
  ctx.fillStyle = "#fef9c3"; ctx.shadowColor = "#fde047"; ctx.shadowBlur = 18;
  ctx.beginPath(); ctx.arc(mx, my, 10, 0, Math.PI * 2); ctx.fill();
  ctx.restore();

  const sortedB = localBuildings.map(b => ({ b, d2: (b.cx - ox) ** 2 + (b.cy - oy) ** 2 }))
    .filter(x => x.d2 < 1600 * 1600)
    .sort((a, b) => b.d2 - a.d2);

  for (const { b, d2 } of sortedB) {
    const isBlock = !tr.isClear && b.id === tr.blockingId;
    const isLimit = tr.isClear && b.id === tr.limitingId;
    const shade = Math.max(0.25, 1 - Math.sqrt(d2) / 1600);
    const pts = b.pts;
    for (let i = 0; i < pts.length - 1; i++) {
      const x1 = pts[i][0] - ox, y1 = pts[i][1] - oy;
      const x2 = pts[i+1][0] - ox, y2 = pts[i+1][1] - oy;
      const d1 = Math.hypot(x1, y1), d2e = Math.hypot(x2, y2);
      if (d1 < 5 || d2e < 5) continue;
      let az1 = Math.atan2(x1, y1) * RAD; if (az1 < 0) az1 += 360;
      let az2 = Math.atan2(x2, y2) * RAD; if (az2 < 0) az2 += 360;
      let da1 = az1 - fpCenterAz; while (da1 > 180) da1 -= 360; while (da1 < -180) da1 += 360;
      let da2 = az2 - fpCenterAz; while (da2 > 180) da2 -= 360; while (da2 < -180) da2 += 360;
      if (Math.abs(da1) > 65 && Math.abs(da2) > 65) continue;
      if (Math.abs(da1 - da2) > 120) continue;

      ctx.beginPath();
      ctx.moveTo(toX(az1), toY(Math.atan2(b.g - oz, d1) * RAD));
      ctx.lineTo(toX(az2), toY(Math.atan2(b.g - oz, d2e) * RAD));
      ctx.lineTo(toX(az2), toY(Math.atan2(b.top - oz, d2e) * RAD));
      ctx.lineTo(toX(az1), toY(Math.atan2(b.top - oz, d1) * RAD));
      ctx.closePath();

      if (isBlock) { ctx.fillStyle = "rgba(220,38,38,0.9)"; ctx.strokeStyle = "#fca5a5"; }
      else if (isLimit) { ctx.fillStyle = "rgba(217,119,6,0.88)"; ctx.strokeStyle = "#fde047"; }
      else { const c = Math.round(28 + shade * 42); ctx.fillStyle = `rgba(${c},${c+10},${c+26},0.94)`; ctx.strokeStyle = "rgba(148,163,184,0.22)"; }
      ctx.lineWidth = isBlock || isLimit ? 1.2 : 0.7;
      ctx.fill(); ctx.stroke();
    }
  }

  ctx.strokeStyle = tr.isClear ? "#22c55e" : "#ef4444";
  ctx.lineWidth = 1.5; ctx.setLineDash([4, 3]);
  ctx.beginPath(); ctx.arc(mx, my, 15, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);

  ctx.font = "600 10px -apple-system, sans-serif"; ctx.fillStyle = "#fde047";
  const fs = curNight.frames[0], fe = curNight.frames[30];
  ctx.fillText(fs[2], toX(fs[0]) - 46, toY(fs[1]) + 13);
  ctx.fillText(fe[2], toX(fe[0]) + 10, toY(fe[1]) - 6);

  const badge = tr.isClear
    ? `CLEAR: Moon +${tr.clearance.toFixed(1)}° above skyline`
    : (tr.clearance >= 0 ? `TIGHT: +${tr.clearance.toFixed(1)}° (< 1.5° margin)` : `BLOCKED: Building rises ${Math.abs(tr.clearance).toFixed(1)}° above Moon`);
  ctx.font = "700 12px -apple-system, sans-serif";
  const bw = ctx.measureText(badge).width + 18;
  ctx.fillStyle = tr.isClear ? "rgba(21,128,61,0.92)" : "rgba(185,28,28,0.92)";
  ctx.fillRect(w - bw - 10, 10, bw, 24);
  ctx.fillStyle = "#fff"; ctx.fillText(badge, w - bw - 1, 26);
}

function drawProfile() {
  const { w, h, ctx } = resizeCanvas(cProf);
  const tr = (activeView === "spot" && curSpotTrace) ? curSpotTrace : curShulTrace;
  const alt = curNight.frames[frameIdx][1];
  const tanAlt = Math.tan(Math.max(0.5, alt) * DEG);

  ctx.fillStyle = "#0b1120"; ctx.fillRect(0, 0, w, h);
  const padL = 52, padR = 24, padT = 18, padB = 28;
  const pw = w - padL - padR, ph = h - padT - padB;
  const maxDist = 1100;
  const near = tr.slices.filter(s => s.tEnter <= maxDist);
  const minElev = Math.floor((Math.min(tr.g, ...near.map(s => s.g)) - 40) / 10) * 10;
  const maxElev = Math.max(minElev + 420, ...near.map(s => s.top + 40), tr.oz + maxDist * Math.min(tanAlt, 1.0) * 0.6);
  const zStep = maxElev - minElev > 900 ? 200 : 100;
  const xOf = d => padL + (d / maxDist) * pw;
  const yOf = z => padT + ph - ((z - minElev) / (maxElev - minElev)) * ph;

  ctx.strokeStyle = "rgba(148,163,184,0.14)"; ctx.fillStyle = "#94a3b8";
  ctx.font = "10px -apple-system, sans-serif"; ctx.lineWidth = 1;
  for (let d = 0; d <= maxDist; d += 100) {
    const x = xOf(d);
    ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + ph); ctx.stroke();
    ctx.fillText(d + " ft", x - 12, h - 8);
  }
  for (let z = Math.ceil(minElev / zStep) * zStep; z <= maxElev; z += zStep) {
    const y = yOf(z);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    ctx.fillText(z + " ft", 8, y + 3);
  }

  ctx.strokeStyle = "#475569"; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(xOf(0), yOf(tr.g)); ctx.lineTo(xOf(maxDist), yOf(tr.g)); ctx.stroke();

  for (const s of tr.slices) {
    if (s.tEnter > maxDist) continue;
    const x1 = xOf(s.tEnter), x2 = xOf(Math.min(maxDist, s.tExit));
    const bw = Math.max(4, x2 - x1);
    const yG = yOf(s.g), yR = yOf(s.roof), yT = yOf(s.top);
    const isBlock = s.blocks, isLimit = s.id === tr.limitingId;
    ctx.fillStyle = isBlock ? "rgba(220,38,38,0.78)" : (isLimit ? "rgba(217,119,6,0.75)" : "rgba(71,85,105,0.75)");
    ctx.fillRect(x1, yR, bw, yG - yR);
    ctx.strokeStyle = isBlock ? "#fca5a5" : (isLimit ? "#fde047" : "#94a3b8");
    ctx.lineWidth = 1; ctx.strokeRect(x1, yR, bw, yG - yR);
    ctx.strokeStyle = "#e2e8f0"; ctx.setLineDash([3, 2]);
    ctx.beginPath(); ctx.moveTo(x1, yT); ctx.lineTo(x1 + bw, yT); ctx.stroke(); ctx.setLineDash([]);
    if (isBlock || isLimit || s.h >= 120) {
      ctx.fillStyle = isBlock ? "#fca5a5" : (isLimit ? "#fde047" : "#cbd5e1");
      ctx.font = "600 10px -apple-system, sans-serif";
      ctx.fillText(`${s.est === "default" ? "~" : ""}${s.h} ft (${s.obsAngle.toFixed(1)}°)`, x1, yT - 4);
    }
  }

  const rayEndD = Math.min(maxDist, (maxElev - tr.oz) / tanAlt);
  ctx.strokeStyle = tr.isClear ? "#22c55e" : "#ef4444"; ctx.lineWidth = 3;
  ctx.beginPath(); ctx.moveTo(xOf(0), yOf(tr.oz)); ctx.lineTo(xOf(rayEndD), yOf(tr.oz + rayEndD * tanAlt)); ctx.stroke();

  ctx.fillStyle = "#38bdf8";
  ctx.beginPath(); ctx.arc(xOf(0), yOf(tr.oz), 5, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#e2e8f0"; ctx.font = "700 11px -apple-system, sans-serif";
  ctx.fillText(`Observer (eye ${tr.oz.toFixed(0)} ft) → Ray ${alt.toFixed(1)}°`, xOf(0) + 10, yOf(tr.oz) - 8);
}

// ---------------- CONTROLS ----------------
let dragging = false, lastX = 0, lastY = 0;
c3d.addEventListener("mousedown", e => { dragging = true; lastX = e.clientX; lastY = e.clientY; });
window.addEventListener("mouseup", () => { dragging = false; });
window.addEventListener("mousemove", e => {
  if (!dragging) return;
  cam.yaw += (e.clientX - lastX) * 0.008;
  cam.pitch = Math.max(5 * DEG, Math.min(86 * DEG, cam.pitch + (e.clientY - lastY) * 0.008));
  lastX = e.clientX; lastY = e.clientY;
  draw3D();
});
c3d.addEventListener("wheel", e => {
  e.preventDefault();
  cam.dist = Math.max(250, Math.min(2600, cam.dist * (1 + e.deltaY * 0.001)));
  draw3D();
}, { passive: false });

// Touch controls: 1-finger drag to orbit, 2-finger pinch to zoom
let touchMode = null, lastPinchDist = 0;
function touchDist(t) {
  return Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
}
c3d.addEventListener("touchstart", e => {
  if (e.touches.length === 1) {
    touchMode = "orbit";
    lastX = e.touches[0].clientX;
    lastY = e.touches[0].clientY;
  } else if (e.touches.length >= 2) {
    touchMode = "pinch";
    lastPinchDist = touchDist(e.touches);
  }
}, { passive: true });
c3d.addEventListener("touchmove", e => {
  if (touchMode === "orbit" && e.touches.length === 1) {
    e.preventDefault();
    const t = e.touches[0];
    cam.yaw += (t.clientX - lastX) * 0.009;
    cam.pitch = Math.max(5 * DEG, Math.min(86 * DEG, cam.pitch + (t.clientY - lastY) * 0.009));
    lastX = t.clientX;
    lastY = t.clientY;
    draw3D();
  } else if (e.touches.length >= 2) {
    e.preventDefault();
    const d = touchDist(e.touches);
    if (touchMode === "pinch" && lastPinchDist > 0 && d > 0) {
      cam.dist = Math.max(250, Math.min(2600, cam.dist * (lastPinchDist / d)));
      draw3D();
    }
    touchMode = "pinch";
    lastPinchDist = d;
  }
}, { passive: false });
c3d.addEventListener("touchend", e => {
  if (e.touches.length === 1) {
    touchMode = "orbit";
    lastX = e.touches[0].clientX;
    lastY = e.touches[0].clientY;
  } else if (e.touches.length === 0) {
    touchMode = null;
  }
}, { passive: true });

function setPreset(name, shouldDraw=true) {
  const [az] = curNight.frames[frameIdx];
  const rdx = Math.sin(az * DEG), rdy = Math.cos(az * DEG);
  const sp = curActiveSpot || curNight.spot || SHUL;
  for (const id of ["btnCamIso", "btnCamTop"]) document.getElementById(id).classList.remove("active");
  if (name === "iso") {
    document.getElementById("btnCamIso").classList.add("active");
    cam.targetX = (SHUL.x + sp.x) * 0.5 + rdx * 140;
    cam.targetY = (SHUL.y + sp.y) * 0.5 + rdy * 140;
    cam.targetZ = SHUL.g + 35; cam.yaw = (az - 230) * DEG; cam.pitch = 34 * DEG;
    cam.dist = Math.max(950, Math.hypot(sp.x - SHUL.x, sp.y - SHUL.y) * 1.1 + 500);
  } else if (name === "top") {
    document.getElementById("btnCamTop").classList.add("active");
    cam.targetX = (SHUL.x + sp.x) * 0.5 + rdx * 140;
    cam.targetY = (SHUL.y + sp.y) * 0.5 + rdy * 140;
    cam.targetZ = SHUL.g + 15; cam.yaw = 0; cam.pitch = 85 * DEG;
    cam.dist = Math.max(1150, Math.hypot(sp.x - SHUL.x, sp.y - SHUL.y) * 1.2 + 650);
  }
  if (shouldDraw && curNight && curShulTrace) draw3D();
}

document.getElementById("btnCamIso").onclick = () => setPreset("iso");
document.getElementById("btnCamTop").onclick = () => setPreset("top");
document.getElementById("btnFpSpot").onclick = () => { activeView = "spot"; recomputeAndRender(); };
document.getElementById("btnFpShul").onclick = () => { activeView = "shul"; recomputeAndRender(); };
document.getElementById("btnProfSpot").onclick = () => { activeView = "spot"; recomputeAndRender(); };
document.getElementById("btnProfShul").onclick = () => { activeView = "shul"; recomputeAndRender(); };

function setSpotMode(mode) {
  spotMode = mode;
  document.getElementById("btnModeStable").classList.toggle("active", mode === "stable");
  document.getElementById("btnModeLive").classList.toggle("active", mode === "live");
  if (mode === "live" && !curActiveSpot) activeView = "spot";
  recomputeAndRender();
}
document.getElementById("btnModeStable").onclick = () => setSpotMode("stable");
document.getElementById("btnModeLive").onclick = () => setSpotMode("live");

slider.addEventListener("input", e => { frameIdx = parseInt(e.target.value, 10); recomputeAndRender(); });
btnPlay.onclick = () => {
  if (playTimer) { stopPlay(); return; }
  if (frameIdx >= 30) frameIdx = 0;
  btnPlay.innerHTML = "&#9646;&#9646; Pause";
  btnPlay.classList.add("active");
  playTimer = setInterval(() => {
    frameIdx = (frameIdx + 1) % 31;
    slider.value = frameIdx;
    recomputeAndRender();
  }, 240);
};

window.addEventListener("resize", () => { if (overlay.classList.contains("open")) recomputeAndRender(); });
