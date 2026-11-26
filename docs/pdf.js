// Client-side PDF export: Motzaei table, map of recommended spots, and all valid nights.
// jsPDF + AutoTable are loaded on demand from a CDN the first time the button is pressed.

const PdfExport = (() => {
  const LIBS = [
    ["https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js",
     "https://cdn.jsdelivr.net/npm/jspdf@2.5.1/dist/jspdf.umd.min.js"],
    ["https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.5.31/jspdf.plugin.autotable.min.js",
     "https://cdn.jsdelivr.net/npm/jspdf-autotable@3.5.31/dist/jspdf.plugin.autotable.min.js"],
  ];
  let libsP = null;

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => { s.remove(); reject(new Error(`Could not load ${new URL(src).host}`)); };
      document.head.appendChild(s);
    });
  }

  async function ensureLibs() {
    if (!libsP) {
      libsP = (async () => {
        for (const alts of LIBS) {
          let err = null, ok = false;
          for (const u of alts) {
            try { await loadScript(u); ok = true; break; } catch (e) { err = e; }
          }
          if (!ok) throw err;
        }
      })();
    }
    try { await libsP; } catch (e) { libsP = null; throw e; }
  }

  // Standard PDF fonts only cover Latin-1; map common symbols and drop anything else.
  function pdfText(s) {
    return String(s ?? "")
      .replace(/[–—]/g, "-").replace(/•/g, "|").replace(/≈/g, "~").replace(/≥/g, ">=").replace(/≤/g, "<=")
      .replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/…/g, "...").replace(/[✓✕]/g, "")
      .replace(/[^\x20-\xff]/g, "").replace(/\s{2,}/g, " ").trim();
  }

  const letterFor = i => (i < 26 ? String.fromCharCode(65 + i) : String.fromCharCode(65 + Math.floor(i / 26) - 1) + String.fromCharCode(65 + (i % 26)));

  function assignLetters() {
    const map = new Map();
    const list = [];
    for (const n of NIGHTS.filter(x => x.is_motzaei)) {
      if (!n.spot) continue;
      const k = `${n.spot.x},${n.spot.y}`;
      if (!map.has(k)) {
        const letter = letterFor(list.length);
        map.set(k, letter);
        list.push({ letter, ...n.spot, motzaei: n.is_motzaei });
      }
    }
    return { key: s => map.get(`${s.x},${s.y}`), list };
  }

  // Top-down map of buildings, streets, the location and lettered spots
  function drawMap(spots) {
    const W = 1600, H = 1100;
    const cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    const ctx = cv.getContext("2d");
    const xs = [SHUL.x, 0, ...spots.map(s => s.x)], ys = [SHUL.y, 0, ...spots.map(s => s.y)];
    let x0 = Math.min(...xs) - 180, x1 = Math.max(...xs) + 180, y0 = Math.min(...ys) - 180, y1 = Math.max(...ys) + 180;
    const minSpan = 900;
    if (x1 - x0 < minSpan) { const c = (x0 + x1) / 2; x0 = c - minSpan / 2; x1 = c + minSpan / 2; }
    if (y1 - y0 < minSpan * H / W) { const c = (y0 + y1) / 2; y0 = c - minSpan * H / W / 2; y1 = c + minSpan * H / W / 2; }
    const s = Math.min(W / (x1 - x0), H / (y1 - y0));
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const P = (x, y) => [W / 2 + (x - cx) * s, H / 2 - (y - cy) * s];
    const inView = (x, y, m = 0) => { const [px, py] = P(x, y); return px > -m && px < W + m && py > -m && py < H + m; };

    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, W, H);

    // streets
    ctx.strokeStyle = "#e2e8f0";
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = Math.max(6, Math.min(26, 30 * s));
    for (const pts of MODEL.streetsDraw) {
      if (!pts.some(p => inView(p[0], p[1], 300))) continue;
      ctx.beginPath();
      pts.forEach((p, i) => { const [px, py] = P(p[0], p[1]); if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py); });
      ctx.stroke();
    }

    // buildings, shaded by height
    for (const b of BUILDINGS) {
      if (!inView(b.cx, b.cy, 200)) continue;
      const t = Math.min(1, b.h / 250);
      if (b.est === "default") ctx.fillStyle = "#ddd6f3";
      else { const v = Math.round(214 - t * 120); ctx.fillStyle = `rgb(${v},${v + 4},${v + 12})`; }
      ctx.strokeStyle = "#94a3b8";
      ctx.lineWidth = 1;
      ctx.beginPath();
      b.pts.forEach((p, i) => { const [px, py] = P(p[0], p[1]); if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py); });
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }

    // street labels
    ctx.font = "600 20px Helvetica, Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const placed = [];
    for (const [name, x, y] of MODEL.streetLabels) {
      if (!inView(x, y, -40)) continue;
      const [px, py] = P(x, y);
      if (placed.some(q => Math.abs(q[0] - px) < 140 && Math.abs(q[1] - py) < 28)) continue;
      placed.push([px, py]);
      const label = pdfText(name) || name;
      const tw = ctx.measureText(label).width;
      ctx.fillStyle = "rgba(255,255,255,0.85)";
      ctx.fillRect(px - tw / 2 - 5, py - 13, tw + 10, 26);
      ctx.fillStyle = "#334155";
      ctx.fillText(label, px, py);
    }

    // location
    const [lx, ly] = P(SHUL.x, SHUL.y);
    ctx.fillStyle = "#2563eb"; ctx.strokeStyle = "#fff"; ctx.lineWidth = 4;
    ctx.beginPath(); ctx.arc(lx, ly, 16, 0, Math.PI * 2); ctx.fill(); ctx.stroke();

    // spots
    ctx.textAlign = "center";
    for (const sp of spots) {
      const [px, py] = P(sp.x, sp.y);
      const isLoc = Math.hypot(sp.x - SHUL.x, sp.y - SHUL.y) < 6;
      const ox = isLoc ? 26 : 0, oy = isLoc ? 26 : 0;
      ctx.fillStyle = sp.motzaei ? "#16a34a" : "#65a30d";
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc(px + ox, py + oy, 17, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      ctx.fillStyle = "#fff";
      ctx.font = `800 ${sp.letter.length > 1 ? 15 : 19}px Helvetica, Arial, sans-serif`;
      ctx.fillText(sp.letter, px + ox, py + oy + 1);
    }

    // location label on top of everything
    ctx.font = "700 22px Helvetica, Arial, sans-serif";
    ctx.textAlign = "left";
    const locLabel = pdfText(PLACE.pinLabel) || PLACE.short;
    const lw = ctx.measureText(locLabel).width;
    const lxo = lx - 20 - lw - 12 > 10 ? -(lw + 32) : 20;
    ctx.fillStyle = "rgba(255,255,255,0.92)"; ctx.fillRect(lx + lxo, ly - 47, lw + 12, 30);
    ctx.fillStyle = "#1e3a8a"; ctx.fillText(locLabel, lx + lxo + 6, ly - 32);

    // north arrow (map is north-up)
    ctx.save();
    ctx.translate(W - 60, 70);
    ctx.fillStyle = "#0f172a";
    ctx.beginPath(); ctx.moveTo(0, -34); ctx.lineTo(14, 8); ctx.lineTo(0, 0); ctx.lineTo(-14, 8); ctx.closePath(); ctx.fill();
    ctx.font = "800 22px Helvetica, Arial, sans-serif"; ctx.fillText("N", 0, 30);
    ctx.restore();

    // scale bar
    const target = (x1 - x0) / 5;
    const nice = [50, 100, 200, 250, 500, 1000].reduce((a, b) => Math.abs(b - target) < Math.abs(a - target) ? b : a);
    const px = nice * s;
    ctx.fillStyle = "rgba(255,255,255,0.9)"; ctx.fillRect(20, H - 64, px + 40, 48);
    ctx.fillStyle = "#0f172a"; ctx.fillRect(40, H - 34, px, 8);
    ctx.font = "600 18px Helvetica, Arial, sans-serif"; ctx.textAlign = "left";
    ctx.fillText(`${nice} ft`, 40, H - 48);

    ctx.strokeStyle = "#cbd5e1"; ctx.lineWidth = 4; ctx.strokeRect(0, 0, W, H);
    return { url: cv.toDataURL("image/jpeg", 0.88), ratio: H / W };
  }

  function spotCell(n, letters) {
    if (n.spot) {
      const wait = n.wait_min ? ` (from ${n.wait_time_str})` : "";
      const L = letters.key(n.spot);
      return `${L ? `${L}  ` : ""}${pdfText(n.spot.short_name) || "Spot"}${wait}`;
    }
    if (n.moon_alt_deg <= 0.5) return `Moon not up at tzeis${n.moon_note ? ` - ${pdfText(n.moon_note)}` : ""}`;
    return `No clear spot within ${MODEL.walkMax.toLocaleString()} ft`;
  }
  const walkCell = n => (n.spot ? (n.spot.walk_ft <= 20 ? "0 ft" : `${n.spot.walk_ft.toLocaleString()} ft`) : "-");
  const moonCell = n => { const f = n.frames[0]; return `${f[3]} ${f[0].toFixed(0)}°, alt ${f[1].toFixed(0)}°, ${n.illum_pct}%`; };

  function build() {
    const { jsPDF } = window.jspdf;
    const doc = new jsPDF({ unit: "pt", format: "letter" });
    const PW = doc.internal.pageSize.getWidth(), PH = doc.internal.pageSize.getHeight();
    const M = 36;
    const letters = assignLetters();
    const israel = SETTINGS.israel === "auto" ? Astro.isLikelyIsrael(PLACE.lat, PLACE.lon) : SETTINGS.israel === "israel";

    // ---- header
    let y = M + 6;
    doc.setFont("helvetica", "bold"); doc.setFontSize(17); doc.setTextColor(15, 23, 42);
    doc.text(pdfText(`Kiddush Levanah ${SETTINGS.year} - ${PLACE.name}`) || `Kiddush Levanah ${SETTINGS.year}`, M, y);
    y += 16;
    doc.setFont("helvetica", "normal"); doc.setFontSize(9.5); doc.setTextColor(71, 85, 105);
    const addr = pdfText(PLACE.label !== PLACE.name ? PLACE.label : "") || `${PLACE.lat.toFixed(5)}, ${PLACE.lon.toFixed(5)}`;
    doc.text(addr, M, y);
    y += 13;
    const rules = pdfText(`Window: ${SETTINGS.minDays} days after molad until ${SOF_LABEL[SETTINGS.sofZman]} (after Yom Kippur / Tisha B'Av) • Tzeis = shkiah + ${SETTINGS.tzeis} min • Moon clear >= 1.5° above rooftops for ${SETTINGS.clearMin} min • ${israel ? "Israel" : "Diaspora"} Yom Tov • Times: ${MODEL.tz}`);
    doc.splitTextToSize(rules, PW - 2 * M).forEach(line => { doc.text(line, M, y); y += 11.5; });
    const hs = MODEL.heightStats;
    const dataLine = pdfText(`3D data: ${MODEL.source}.${hs.pctEst >= 5 ? ` ${hs.pctEst}% of building heights estimated (${SETTINGS.defaultHeightFt} ft default) - treat as approximate.` : ""}`);
    doc.setTextColor(100, 116, 139);
    doc.splitTextToSize(dataLine, PW - 2 * M).forEach(line => { doc.text(line, M, y); y += 11.5; });
    y += 4;

    const head = [["Night", "Hebrew date", "Tzeis", "Moon at tzeis", "Where to go (see map)", "Walk", "Window ends"]];
    const row = n => [
      `${n.date_disp}${n.special_tag && n.special_tag !== "Motzaei Shabbos" ? `\n${n.special_tag}` : ""}`,
      n.heb_date, n.tzeis_str, moonCell(n), spotCell(n, letters), walkCell(n), pdfText(n.win_latest),
    ];
    const tableStyle = {
      theme: "grid",
      styles: { font: "helvetica", fontSize: 8.5, cellPadding: 3.5, lineColor: [203, 213, 225], lineWidth: 0.5, textColor: [15, 23, 42], valign: "middle" },
      headStyles: { fillColor: [30, 41, 59], textColor: 255, fontStyle: "bold" },
      alternateRowStyles: { fillColor: [248, 250, 252] },
      columnStyles: { 0: { cellWidth: 92 }, 1: { cellWidth: 62 }, 2: { cellWidth: 46 }, 3: { cellWidth: 92 }, 5: { cellWidth: 44, halign: "right" }, 6: { cellWidth: 70 } },
      margin: { left: M, right: M, bottom: 40 },
      didParseCell: d => {
        if (d.section === "body" && d.column.index === 4) {
          const t = String(d.cell.raw);
          if (/^(No clear|Moon not up)/.test(t)) d.cell.styles.textColor = [185, 28, 28];
          else d.cell.styles.fontStyle = "bold";
        }
      },
    };

    // ---- Motzaei table
    doc.setFont("helvetica", "bold"); doc.setFontSize(12); doc.setTextColor(15, 23, 42);
    doc.text("Motzaei Shabbos, Motzaei Yom Kippur & Motzaei Tisha B'Av", M, y + 8);
    doc.autoTable({ ...tableStyle, startY: y + 14, head, body: NIGHTS.filter(n => n.is_motzaei).map(row) });

    // ---- map + legend
    doc.addPage();
    y = M + 6;
    doc.setFont("helvetica", "bold"); doc.setFontSize(12); doc.setTextColor(15, 23, 42);
    doc.text("Map of recommended spots", M, y);
    doc.setFont("helvetica", "normal"); doc.setFontSize(8.5); doc.setTextColor(100, 116, 139);
    doc.text(pdfText(`Blue = ${PLACE.pinLabel}. Green letters = spots for the Motzaei nights listed on page 1. North is up.`), M, y + 12);
    const map = drawMap(letters.list);
    const mw = PW - 2 * M, mh = mw * map.ratio;
    doc.addImage(map.url, "JPEG", M, y + 20, mw, mh);
    const legend = letters.list.map(s => [s.letter, pdfText(s.name) || "Spot", s.walk_ft <= 20 ? "0 ft" : `${s.walk_ft.toLocaleString()} ft`]);
    doc.autoTable({
      ...tableStyle,
      startY: y + 28 + mh,
      head: [["", "Spot", "Walk"]],
      body: legend,
      styles: { ...tableStyle.styles, fontSize: 8 },
      columnStyles: { 0: { cellWidth: 26, halign: "center", fontStyle: "bold" }, 2: { cellWidth: 60, halign: "right" } },
      didParseCell: undefined,
    });

    // ---- all nights
    doc.addPage();
    doc.setFont("helvetica", "bold"); doc.setFontSize(12); doc.setTextColor(15, 23, 42);
    doc.text(`All valid nights (${NIGHTS.length})`, M, M + 6);
    doc.setFont("helvetica", "normal"); doc.setFontSize(8.5); doc.setTextColor(100, 116, 139);
    doc.text("Lettered spots appear on the map; others are described by street and nearest intersection.", M + 150, M + 6);
    doc.autoTable({
      ...tableStyle,
      startY: M + 14,
      head,
      body: NIGHTS.map(row),
      styles: { ...tableStyle.styles, fontSize: 7.5, cellPadding: 2.6 },
    });

    // ---- footer on every page
    const pages = doc.getNumberOfPages();
    const stamp = new Date().toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
    for (let i = 1; i <= pages; i++) {
      doc.setPage(i);
      doc.setFont("helvetica", "normal"); doc.setFontSize(7.5); doc.setTextColor(148, 163, 184);
      let foot = pdfText(`Generated ${stamp} • Interactive 3D version: ${location.href.split("#")[0]}`);
      const maxW = PW - 2 * M - 70;
      if (doc.getTextWidth(foot) > maxW) {
        while (foot.length > 20 && doc.getTextWidth(foot + "...") > maxW) foot = foot.slice(0, -1);
        foot += "...";
      }
      doc.text(foot, M, PH - 20);
      doc.text(`Page ${i} of ${pages}`, PW - M, PH - 20, { align: "right" });
    }
    const slug = (PLACE.name || "location").replace(/[^A-Za-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40) || "location";
    doc.save(`Kiddush_Levanah_${SETTINGS.year}_${slug}.pdf`);
  }

  async function download() {
    const btn = document.getElementById("btnPdf");
    if (!NIGHTS.length || !MODEL) return;
    const orig = btn.innerHTML;
    btn.disabled = true;
    btn.textContent = "Preparing PDF…";
    try {
      await ensureLibs();
      await new Promise(r => setTimeout(r, 0));
      build();
      if (typeof trackEvent === "function") trackEvent("event/pdf-download", "PDF downloaded");
    } catch (e) {
      console.error(e);
      alert(`Could not create the PDF: ${e.message}`);
    } finally {
      btn.disabled = false;
      btn.innerHTML = orig;
    }
  }

  window.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btnPdf").onclick = download;
  });
  return { download };
})();
