const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");

// ---------- Palette (teal du projet) ----------
const INK = "0F2A30", TEAL = "0D9488", TEALD = "047857", TEALDD = "033A2B";
const TEALLT = "EAF7F4", TEALLT2 = "D1FAF2", MINT = "5EEAD4";
const WHITE = "FFFFFF", MUTED = "5B7178", BORDER = "D8E8E4";
const HFONT = "Georgia", BFONT = "Calibri";

const FIG = "/Users/zakariae/Desktop/MCP-Powered BI Ecosystem/rapport/figures/";
const ASSET = "/Users/zakariae/Desktop/MCP-Powered BI Ecosystem/rapport/assets/";
const DIMS = {
  accueil:[2560,1800], pipeline:[2560,2496], dashboard:[2560,1800], carte:[2000,880],
  serie_home:[1640,720], top_tournois:[1640,860], rapport_kpis:[1848,728],
  rapport_anomalies:[1848,448], rapport_segments:[1848,496], rapport_findings:[1848,392],
  logo:[175,189],
};

// ---------- Assets page de garde (identiques au rapport) ----------
const COVER = { fr: ASSET + "entete_fr.png", ar: ASSET + "entete_arabe.png", logo: ASSET + "logo_ensa.png" };
// Fond couverture : vagues teal en light mode (SVG -> PNG, paysage 16:9)
const waveSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="1333" height="750">
<rect width="1333" height="750" fill="#FFFFFF"/>
<path d="M0,712 C300,701 520,721 760,708 C1000,698 1180,717 1333,707 L1333,750 L0,750 Z" fill="#D1FAF2"/>
<path d="M0,725 C300,715 520,733 760,722 C1000,713 1180,729 1333,722 L1333,750 L0,750 Z" fill="#0D9488"/>
<path d="M0,736 C320,729 520,743 760,734 C1000,727 1200,741 1333,736 L1333,750 L0,750 Z" fill="#047857"/>
</svg>`;

// ---------- Icônes ----------
async function icon(IconComp, color, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(IconComp, { color, size: String(size) }));
  const png = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + png.toString("base64");
}
const shadow = () => ({ type: "outer", color: "0F2A30", blur: 7, offset: 3, angle: 90, opacity: 0.12 });

// ---------- Helpers ----------
const W = 13.33, H = 7.5;
function fit(key, maxW, maxH) {
  const [pw, ph] = DIMS[key]; let w = maxW, h = (maxW * ph) / pw;
  if (h > maxH) { h = maxH; w = (maxH * pw) / ph; }
  return { w, h };
}
function footer(slide, n) {
  slide.addText(String(n), { x: W - 1.1, y: 6.95, w: 0.6, h: 0.35, fontFace: BFONT, fontSize: 9, color: MUTED, align: "right", valign: "middle", margin: 0 });
}
// En-tête institutionnel : Français | Logo ENSA | Arabe (comme la page de garde du rapport)
function coverHeader(slide) {
  slide.addImage({ path: COVER.fr,   x: 0.85, y: 0.50, h: 0.95, w: 0.95 * 2.018 });
  slide.addImage({ path: COVER.logo, x: 6.02, y: 0.32, h: 1.40, w: 1.40 * 0.926 });
  slide.addImage({ path: COVER.ar,   x: 10.5, y: 0.50, h: 0.95, w: 0.95 * 2.060 });
}
function title(slide, text, kicker) {
  if (kicker) slide.addText(kicker.toUpperCase(), { x: 0.6, y: 0.42, w: 12, h: 0.3, fontFace: BFONT, fontSize: 12, bold: true, color: TEAL, charSpacing: 2, margin: 0 });
  slide.addText(text, { x: 0.6, y: kicker ? 0.74 : 0.5, w: 12.1, h: 0.7, fontFace: HFONT, fontSize: 28, bold: true, color: INK, margin: 0 });
}
function card(slide, x, y, w, h, fill = WHITE) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { color: BORDER, width: 1 }, shadow: shadow() });
}
function iconCircle(slide, x, y, d, iconData, bg = TEALLT2) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: bg }, line: { type: "none" } });
  slide.addImage({ data: iconData, x: x + d * 0.24, y: y + d * 0.24, w: d * 0.52, h: d * 0.52 });
}
function shot(slide, key, x, y, maxW, maxH, caption, center) {
  const { w, h } = fit(key, maxW, maxH);
  const px = center ? x + (maxW - w) / 2 : x;
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: px - 0.06, y: y - 0.06, w: w + 0.12, h: h + 0.12, rectRadius: 0.06, fill: { color: WHITE }, line: { color: BORDER, width: 1 }, shadow: shadow() });
  slide.addImage({ path: FIG + "fig_" + key + ".png", x: px, y, w, h });
  if (caption) slide.addText(caption, { x: px - 0.06, y: y + h + 0.08, w: w + 0.12, h: 0.3, fontFace: BFONT, fontSize: 10.5, italic: true, color: MUTED, align: "center", margin: 0 });
  return { w, h, x: px };
}

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.author = "Mohamed Rouane & Zakariae Trachni";
pres.title = "Soutenance PFA — MCP-Powered BI Ecosystem";

(async () => {
  const slides = [];
  // Pré-rendu des icônes
  const I = {
    robot: await icon(fa.FaRobot, "#0D9488"), users: await icon(fa.FaUsers, "#0D9488"),
    server: await icon(fa.FaServer, "#0D9488"), chart: await icon(fa.FaChartLine, "#0D9488"),
    db: await icon(fa.FaDatabase, "#0D9488"), shield: await icon(fa.FaShieldAlt, "#0D9488"),
    check: await icon(fa.FaCheckCircle, "#047857"), bolt: await icon(fa.FaBolt, "#0D9488"),
    map: await icon(fa.FaMapMarkedAlt, "#0D9488"), diagram: await icon(fa.FaProjectDiagram, "#0D9488"),
    search: await icon(fa.FaSearch, "#0D9488"), file: await icon(fa.FaFileAlt, "#0D9488"),
    layers: await icon(fa.FaLayerGroup, "#0D9488"), cogs: await icon(fa.FaCogs, "#0D9488"),
    scale: await icon(fa.FaBalanceScale, "#0D9488"), warn: await icon(fa.FaExclamationTriangle, "#B45309"),
    bulb: await icon(fa.FaLightbulb, "#0D9488"), target: await icon(fa.FaBullseye, "#0D9488"),
    checkW: await icon(fa.FaCheckCircle, "#5EEAD4"), plug: await icon(fa.FaPlug, "#0D9488"),
    flag: await icon(fa.FaFlagCheckered, "#0D9488"), rocket: await icon(fa.FaRocket, "#0D9488"),
  };

  // Fond couverture (vagues teal, light mode) : SVG -> PNG
  const coverBg = "image/png;base64," + (await sharp(Buffer.from(waveSvg), { density: 200 }).png().toBuffer()).toString("base64");

  // ============ SLIDE 1 — Couverture (light mode, style page de garde) ============
  let s = pres.addSlide(); slides.push(s); s.background = { data: coverBg };
  coverHeader(s);
  s.addText("École Nationale des Sciences Appliquées d'Oujda", { x: 0.6, y: 1.92, w: 12.13, h: 0.5, fontFace: HFONT, fontSize: 20, bold: true, color: INK, align: "center", charSpacing: 1, margin: 0 });
  s.addText("Projet de Fin d'Année (PFA)", { x: 0.6, y: 2.54, w: 12.13, h: 0.35, fontFace: BFONT, fontSize: 15, bold: true, color: TEALD, align: "center", charSpacing: 1, margin: 0 });
  s.addText("Filière : Ingénierie Data Science et Cloud Computing", { x: 0.6, y: 2.92, w: 12.13, h: 0.32, fontFace: BFONT, fontSize: 13, color: MUTED, align: "center", margin: 0 });
  // Bloc titre encadré de filets teal (comme la page de garde)
  s.addShape(pres.shapes.RECTANGLE, { x: 2.4, y: 3.56, w: 8.53, h: 0.028, fill: { color: TEALD }, line: { type: "none" } });
  s.addText("MCP-Powered BI Ecosystem", { x: 0.6, y: 3.70, w: 12.13, h: 0.78, fontFace: HFONT, fontSize: 34, bold: true, color: INK, align: "center", margin: 0 });
  s.addText("Une plateforme décisionnelle généraliste multi-agents orchestrée par le protocole MCP", { x: 1.6, y: 4.52, w: 10.13, h: 0.5, fontFace: BFONT, fontSize: 14, italic: true, color: TEAL, align: "center", margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 2.4, y: 5.10, w: 8.53, h: 0.028, fill: { color: TEALD }, line: { type: "none" } });
  // Réalisé par (gauche) / Encadré par + jury (droite)
  // Réalisé par (gauche) · Membres du jury (centre) · Encadré par (droite)
  s.addText([
    { text: "Réalisé par :", options: { bold: true, color: TEALD, fontSize: 13, breakLine: true } },
    { text: "Mohamed Rouane", options: { color: INK, fontSize: 14, breakLine: true } },
    { text: "Zakariae Trachni", options: { color: INK, fontSize: 14 } },
  ], { x: 0.8, y: 5.42, w: 3.9, h: 1.0, fontFace: BFONT, align: "left", valign: "top", margin: 0, lineSpacingMultiple: 1.18 });
  s.addText([
    { text: "Membres du jury :", options: { bold: true, color: TEALD, fontSize: 13, breakLine: true } },
    { text: "Pr. Asmae El Mezouari", options: { color: INK, fontSize: 14, breakLine: true } },
    { text: "Pr. Abdelmounaim Kerkri", options: { color: INK, fontSize: 14 } },
  ], { x: 4.71, y: 5.42, w: 3.9, h: 1.0, fontFace: BFONT, align: "center", valign: "top", margin: 0, lineSpacingMultiple: 1.18 });
  s.addText([
    { text: "Encadré par :", options: { bold: true, color: TEALD, fontSize: 13, breakLine: true } },
    { text: "Pr. Abdelmounaim Kerkri", options: { color: INK, fontSize: 14 } },
  ], { x: 8.63, y: 5.42, w: 3.9, h: 1.0, fontFace: BFONT, align: "right", valign: "top", margin: 0, lineSpacingMultiple: 1.18 });
  s.addText("Année universitaire 2025 – 2026", { x: 0.6, y: 6.62, w: 12.13, h: 0.3, fontFace: BFONT, fontSize: 12, bold: true, color: TEALD, align: "center", margin: 0 });

  // ============ SLIDE 2 — Plan ============
  s = pres.addSlide(); slides.push(s); s.background = { color: WHITE };
  title(s, "Plan de la présentation", "Sommaire");
  const plan = [
    ["1", "Contexte & problématique", "Pourquoi automatiser la Business Intelligence ?"],
    ["2", "Objectifs & état de l'art", "Cibles du projet ; LLM, agents et protocole MCP"],
    ["3", "Conception", "Architecture en couches, 7 agents, moteur adaptatif"],
    ["4", "Réalisation", "KPIs, carte géographique, anomalies, fiabilité"],
    ["5", "Démonstration & étude de cas", "Interface et 17 769 matchs de football"],
    ["6", "Conclusion & perspectives", "Bilan et pistes d'évolution"],
  ];
  plan.forEach((p, i) => {
    const y = 1.75 + i * 0.86;
    s.addShape(pres.shapes.OVAL, { x: 0.7, y, w: 0.6, h: 0.6, fill: { color: i % 2 ? TEALD : TEAL }, line: { type: "none" } });
    s.addText(p[0], { x: 0.7, y, w: 0.6, h: 0.6, fontFace: HFONT, fontSize: 22, bold: true, color: WHITE, align: "center", valign: "middle", margin: 0 });
    s.addText(p[1], { x: 1.55, y: y - 0.02, w: 7.5, h: 0.4, fontFace: HFONT, fontSize: 18, bold: true, color: INK, valign: "middle", margin: 0 });
    s.addText(p[2], { x: 1.55, y: y + 0.34, w: 11, h: 0.3, fontFace: BFONT, fontSize: 12.5, color: MUTED, valign: "middle", margin: 0 });
  });
  footer(s, slides.length);

  // ============ SLIDE 3 — Contexte & problématique ============
  s = pres.addSlide(); slides.push(s); s.background = { color: WHITE };
  title(s, "Contexte & problématique", "Introduction");
  // chaîne décisionnelle
  const chain = ["Données\nbrutes", "Ingestion\n& validation", "Préparation\n& nettoyage", "Analyse\n& KPIs", "Restitution\n& décision"];
  chain.forEach((c, i) => {
    const x = 0.6 + i * 2.5;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.7, w: 2.15, h: 1.0, rectRadius: 0.08, fill: { color: i === 4 ? TEAL : TEALLT2 }, line: { color: BORDER, width: 1 } });
    s.addText(c, { x, y: 1.7, w: 2.15, h: 1.0, fontFace: BFONT, fontSize: 12.5, bold: true, color: i === 4 ? WHITE : INK, align: "center", valign: "middle", margin: 0 });
    if (i < 4) s.addText("›", { x: x + 2.13, y: 1.7, w: 0.4, h: 1.0, fontFace: HFONT, fontSize: 26, bold: true, color: TEAL, align: "center", valign: "middle", margin: 0 });
  });
  s.addText("Une chaîne aujourd'hui largement manuelle", { x: 0.6, y: 2.78, w: 12, h: 0.3, fontFace: BFONT, fontSize: 12, italic: true, color: MUTED, align: "center", margin: 0 });
  // limites
  s.addText("Limites des outils BI classiques", { x: 0.6, y: 3.35, w: 7, h: 0.4, fontFace: HFONT, fontSize: 17, bold: true, color: TEALD, margin: 0 });
  s.addText([
    { text: "Forte dépendance à l'expertise (analyste = goulot d'étranglement)", options: { bullet: true, breakLine: true } },
    { text: "Travail répétitif et chronophage à chaque nouveau jeu de données", options: { bullet: true, breakLine: true } },
    { text: "Solutions spécialisées par cas d'usage (hypothèses figées)", options: { bullet: true, breakLine: true } },
    { text: "Rédaction du rapport entièrement humaine", options: { bullet: true } },
  ], { x: 0.7, y: 3.8, w: 6.6, h: 2.4, fontFace: BFONT, fontSize: 14.5, color: INK, paraSpaceAfter: 8, margin: 0 });
  // problématique callout
  card(s, 7.7, 3.5, 5.0, 2.7, TEALLT);
  iconCircle(s, 8.0, 3.8, 0.7, I.bulb);
  s.addText("Problématique", { x: 8.85, y: 3.85, w: 3.6, h: 0.4, fontFace: HFONT, fontSize: 16, bold: true, color: TEALD, valign: "middle", margin: 0 });
  s.addText("Comment analyser automatiquement et de manière fiable n'importe quel jeu de données tabulaire, en combinant la rigueur d'un moteur déterministe et le discernement d'agents IA ?", { x: 8.0, y: 4.55, w: 4.4, h: 1.5, fontFace: BFONT, fontSize: 14, italic: true, color: INK, valign: "top", margin: 0, lineSpacingMultiple: 1.08 });
  footer(s, slides.length);

  // ============ SLIDE 4 — Objectifs ============
  s = pres.addSlide(); slides.push(s); s.background = { color: WHITE };
  title(s, "Objectifs du projet", "Cibles");
  const objs = [
    [I.diagram, "Architecture multi-agents", "Sept agents orchestrés via un serveur MCP, à contrôle d'accès par rôle."],
    [I.cogs, "Moteur adaptatif généraliste", "Profilage automatique des colonnes, sans hypothèse sur le domaine métier."],
    [I.file, "Livrables automatiques", "Tableau de bord interactif + rapport décisionnel (web & PDF)."],
    [I.shield, "Fiabilité & véracité", "Filets de sécurité, vérification des chiffres, suivi des coûts."],
  ];
  objs.forEach((o, i) => {
    const x = 0.6 + (i % 2) * 6.25, y = 1.85 + Math.floor(i / 2) * 2.1;
    card(s, x, y, 5.9, 1.8);
    iconCircle(s, x + 0.3, y + 0.4, 1.0, o[0]);
    s.addText(o[1], { x: x + 1.5, y: y + 0.3, w: 4.2, h: 0.5, fontFace: HFONT, fontSize: 17, bold: true, color: INK, valign: "middle", margin: 0 });
    s.addText(o[2], { x: x + 1.5, y: y + 0.82, w: 4.25, h: 0.8, fontFace: BFONT, fontSize: 13, color: MUTED, margin: 0, lineSpacingMultiple: 1.05 });
  });
  // bandeau "0 hypothèse"
  s.addText([
    { text: "0", options: { fontFace: HFONT, fontSize: 30, bold: true, color: TEAL } },
    { text: "  hypothèse métier — fonctionne sur tout fichier CSV / Excel / JSON", options: { fontFace: BFONT, fontSize: 15, color: INK } },
  ], { x: 0.6, y: 6.25, w: 12, h: 0.5, align: "center", valign: "middle", margin: 0 });
  footer(s, slides.length);

  // ============ SLIDE 5 — État de l'art ============
  s = pres.addSlide(); slides.push(s); s.background = { color: WHITE };
  title(s, "Les briques technologiques", "État de l'art");
  const art = [
    [I.robot, "Grands modèles de langage", "Raisonnement, synthèse et appel d'outils — mais sujets aux hallucinations."],
    [I.users, "Agents d'IA", "Boucle observer → décider → agir ; rôles spécialisés qui coopèrent."],
    [I.server, "Protocole MCP", "Standard ouvert : registre d'outils + contrôle d'accès pour les LLM."],
    [I.chart, "Outils techniques", "Python, pandas, Plotly, FastAPI, fournisseurs LLM Groq / Ollama."],
  ];
  art.forEach((a, i) => {
    const x = 0.6 + (i % 2) * 6.25, y = 1.85 + Math.floor(i / 2) * 2.15;
    card(s, x, y, 5.9, 1.85);
    iconCircle(s, x + 0.32, y + 0.55, 0.95, a[0]);
    s.addText(a[1], { x: x + 1.5, y: y + 0.28, w: 4.2, h: 0.5, fontFace: HFONT, fontSize: 16.5, bold: true, color: TEALD, valign: "middle", margin: 0 });
    s.addText(a[2], { x: x + 1.5, y: y + 0.82, w: 4.25, h: 0.9, fontFace: BFONT, fontSize: 13, color: MUTED, margin: 0, lineSpacingMultiple: 1.05 });
  });
  footer(s, slides.length);

  // ============ SLIDE 6 — Architecture en couches ============
  s = pres.addSlide(); slides.push(s); s.background = { color: WHITE };
  title(s, "Architecture en couches", "Conception");
  const layers = [
    ["Couche présentation", "Interface web FastAPI — téléversement, suivi, dashboard, rapport", TEAL, WHITE],
    ["Couche orchestration", "Pipeline + filets de sécurité déterministes", TEALLT2, INK],
    ["Couche agents", "7 agents spécialisés (Orchestrateur, Ingestion, Data Prep, KPI, …)", TEALLT2, INK],
    ["Serveur MCP", "Registre de 14 outils + contrôle d'accès par rôle", TEALD, WHITE],
    ["Moteur déterministe", "Profilage · KPIs · Graphiques · Insights · Validation", TEALLT2, INK],
    ["Magasin d'artefacts", "dashboard.html · report.html · state.json", TEALLT2, INK],
  ];
  layers.forEach((l, i) => {
    const y = 1.7 + i * 0.86;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 2.2, y, w: 8.9, h: 0.68, rectRadius: 0.06, fill: { color: l[2] }, line: { color: BORDER, width: 1 } });
    s.addText(l[0], { x: 2.45, y, w: 3.1, h: 0.68, fontFace: HFONT, fontSize: 14.5, bold: true, color: l[3], valign: "middle", margin: 0 });
    s.addText(l[1], { x: 5.5, y, w: 5.4, h: 0.68, fontFace: BFONT, fontSize: 11.5, color: l[3] === WHITE ? "E6F5F1" : MUTED, valign: "middle", margin: 0 });
    if (i < layers.length - 1) s.addText("▼", { x: 6.35, y: y + 0.62, w: 0.6, h: 0.22, fontFace: BFONT, fontSize: 11, color: TEAL, align: "center", valign: "middle", margin: 0 });
  });
  s.addText("Séparation des préoccupations : chaque couche évolue indépendamment ; le serveur MCP médie tous les accès.", { x: 0.6, y: 6.95, w: 12, h: 0.3, fontFace: BFONT, fontSize: 11.5, italic: true, color: MUTED, align: "center", margin: 0 });
  footer(s, slides.length);

  // ============ SLIDE 7 — 7 agents + MCP ============
  s = pres.addSlide(); slides.push(s); s.background = { color: WHITE };
  title(s, "Sept agents, un serveur MCP", "Conception");
  const agents = ["Orchestrateur", "Ingestion", "Data Prep", "KPI", "Dashboard", "Publication", "Reporter"];
  agents.forEach((a, i) => {
    const x = 0.6 + i * 1.78;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.75, w: 1.62, h: 0.95, rectRadius: 0.08, fill: { color: TEALLT2 }, line: { color: TEAL, width: 1 } });
    s.addText((i + 1) + "", { x, y: 1.82, w: 1.62, h: 0.3, fontFace: HFONT, fontSize: 12, bold: true, color: TEAL, align: "center", margin: 0 });
    s.addText(a, { x: x + 0.05, y: 2.05, w: 1.52, h: 0.55, fontFace: BFONT, fontSize: 11.5, bold: true, color: INK, align: "center", valign: "middle", margin: 0 });
    s.addText("▼", { x, y: 2.74, w: 1.62, h: 0.25, fontFace: BFONT, fontSize: 10, color: TEAL, align: "center", margin: 0 });
  });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 2.0, y: 3.15, w: 9.3, h: 0.85, rectRadius: 0.08, fill: { color: TEALD }, line: { type: "none" }, shadow: shadow() });
  s.addText("Serveur MCP — 14 outils, contrôle d'accès par rôle (refus par défaut)", { x: 2.0, y: 3.15, w: 9.3, h: 0.85, fontFace: HFONT, fontSize: 16, bold: true, color: WHITE, align: "center", valign: "middle", margin: 0 });
  // moindre privilège
  card(s, 0.6, 4.35, 6.0, 2.05, TEALLT);
  iconCircle(s, 0.9, 4.62, 0.7, I.shield);
  s.addText("Principe du moindre privilège", { x: 1.75, y: 4.66, w: 4.7, h: 0.4, fontFace: HFONT, fontSize: 15, bold: true, color: TEALD, valign: "middle", margin: 0 });
  s.addText("Chaque agent ne peut appeler que les outils strictement nécessaires à son rôle. Toute tentative hors périmètre est refusée par le serveur.", { x: 0.9, y: 5.25, w: 5.4, h: 1.0, fontFace: BFONT, fontSize: 13, color: INK, margin: 0, lineSpacingMultiple: 1.05 });
  // exemple agent KPI
  card(s, 6.9, 4.35, 5.8, 2.05);
  s.addText("Exemple — agent KPI", { x: 7.2, y: 4.55, w: 5.2, h: 0.35, fontFace: HFONT, fontSize: 14, bold: true, color: INK, margin: 0 });
  s.addText([
    { text: "profile_dataset", options: { bullet: true, breakLine: true } },
    { text: "suggest_kpis  ·  compute_kpis", options: { bullet: true, breakLine: true } },
    { text: "detect_anomalies  ·  compare_segments", options: { bullet: true } },
  ], { x: 7.3, y: 4.95, w: 5.2, h: 1.3, fontFace: "Consolas", fontSize: 12.5, color: TEALD, paraSpaceAfter: 5, margin: 0 });
  footer(s, slides.length);

  // ============ SLIDE 8 — Moteur déterministe ============
  s = pres.addSlide(); slides.push(s); s.background = { color: WHITE };
  title(s, "Le moteur déterministe adaptatif", "Conception");
  const flow = [[I.search, "Profilage", "Rôle de chaque colonne : mesure, dimension, date, géo, identifiant"],
    [I.chart, "KPIs adaptatifs", "Totaux, moyennes, tendances, parts — déduits des rôles"],
    [I.map, "Graphiques", "Tendances, barres, distributions, carte, corrélations"],
    [I.bulb, "Insights", "Anomalies, comparaisons de segments, corrélations"]];
  flow.forEach((f, i) => {
    const x = 0.6 + i * 3.18;
    card(s, x, 1.85, 2.85, 2.5);
    iconCircle(s, x + 1.0, 2.1, 0.85, f[0]);
    s.addText(f[1], { x, y: 3.05, w: 2.85, h: 0.4, fontFace: HFONT, fontSize: 16, bold: true, color: TEALD, align: "center", margin: 0 });
    s.addText(f[2], { x: x + 0.2, y: 3.5, w: 2.45, h: 0.85, fontFace: BFONT, fontSize: 11.5, color: MUTED, align: "center", margin: 0, lineSpacingMultiple: 1.05 });
    if (i < 3) s.addText("›", { x: x + 2.82, y: 1.85, w: 0.4, h: 2.5, fontFace: HFONT, fontSize: 28, bold: true, color: TEAL, align: "center", valign: "middle", margin: 0 });
  });
  card(s, 0.6, 4.7, 12.1, 1.55, TEALLT);
  s.addText([
    { text: "La bonne division du travail.   ", options: { bold: true, color: TEALD, fontFace: HFONT, fontSize: 16 } },
    { text: "Le moteur déterministe garantit l'exactitude et la généralité ; les agents (LLM) apportent le jugement, la curation et la narration. Aucun chiffre n'est inventé par le modèle.", options: { color: INK, fontFace: BFONT, fontSize: 14 } },
  ], { x: 0.95, y: 4.9, w: 11.4, h: 1.15, valign: "middle", margin: 0, lineSpacingMultiple: 1.1 });
  footer(s, slides.length);

  // ============ SLIDE 9 — Fiabilité ============
  s = pres.addSlide(); slides.push(s); s.background = { color: WHITE };
  title(s, "Fiabilité : la confiance avant tout", "Réalisation");
  const rel = [[I.shield, "Filets de sécurité", "Si un agent omet un appel d'outil, le pipeline le réalise lui-même : les livrables sont toujours complets."],
    [I.check, "Vérification des chiffres", "Chaque nombre du rapport est confronté aux KPIs calculés — garde-fou anti-hallucination."],
    [I.bolt, "Suivi des coûts", "Jetons, latence et coût estimé mesurés par agent et par exécution (observabilité)."]];
  rel.forEach((r, i) => {
    const x = 0.6 + i * 4.12;
    card(s, x, 1.95, 3.85, 3.7);
    iconCircle(s, x + 1.35, 2.35, 1.15, r[0]);
    s.addText(r[1], { x, y: 3.75, w: 3.85, h: 0.5, fontFace: HFONT, fontSize: 17, bold: true, color: TEALD, align: "center", margin: 0 });
    s.addText(r[2], { x: x + 0.3, y: 4.3, w: 3.25, h: 1.25, fontFace: BFONT, fontSize: 13, color: MUTED, align: "center", margin: 0, lineSpacingMultiple: 1.1 });
  });
  s.addText("Les filets de sécurité font du moteur déterministe le « filet de dernier recours » — une exécution réussit toujours.", { x: 0.6, y: 6.0, w: 12.1, h: 0.4, fontFace: BFONT, fontSize: 12.5, italic: true, color: MUTED, align: "center", margin: 0 });
  footer(s, slides.length);

  // ============ SLIDE 10 — Démonstration en direct ============
  s = pres.addSlide(); slides.push(s); s.background = { color: WHITE };
  title(s, "Démonstration en direct", "Démonstration");
  card(s, 0.6, 1.8, 4.75, 4.55, TEALLT);
  s.addText("Au programme", { x: 0.95, y: 2.05, w: 4.1, h: 0.45, fontFace: HFONT, fontSize: 18, bold: true, color: TEALD, margin: 0 });
  const demo = [
    "Téléverser un jeu de données (CSV / Excel / JSON)",
    "Suivre en direct le pipeline des 7 agents",
    "Explorer le tableau de bord & la carte mondiale",
    "Ouvrir le rapport décisionnel (chiffres vérifiés)",
  ];
  demo.forEach((t, i) => {
    const y = 2.72 + i * 0.86;
    s.addShape(pres.shapes.OVAL, { x: 0.95, y, w: 0.5, h: 0.5, fill: { color: i % 2 ? TEALD : TEAL }, line: { type: "none" } });
    s.addText(String(i + 1), { x: 0.95, y, w: 0.5, h: 0.5, fontFace: HFONT, fontSize: 15, bold: true, color: WHITE, align: "center", valign: "middle", margin: 0 });
    s.addText(t, { x: 1.6, y: y - 0.08, w: 3.55, h: 0.66, fontFace: BFONT, fontSize: 12.5, color: INK, valign: "middle", margin: 0 });
  });
  // Aperçus (repli si la démo en direct échoue)
  shot(s, "accueil", 5.65, 1.85, 3.35, 2.0, null, true);
  shot(s, "pipeline", 9.15, 1.85, 3.35, 2.0, null, true);
  shot(s, "dashboard", 5.65, 4.2, 3.35, 2.0, null, true);
  shot(s, "carte", 9.15, 4.55, 3.35, 1.6, null, true);
  s.addText("Aperçus de l'application", { x: 5.65, y: 6.35, w: 6.85, h: 0.3, fontFace: BFONT, fontSize: 10.5, italic: true, color: MUTED, align: "center", margin: 0 });
  footer(s, slides.length);

  // ============ SLIDE 12 — Étude de cas ============
  s = pres.addSlide(); slides.push(s); s.background = { color: WHITE };
  title(s, "Étude de cas : matchs internationaux", "Validation");
  const stats = [["17 769", "matchs"], ["1872–2024", "période"], ["90", "tournois"], ["214 / 218", "équipes"]];
  stats.forEach((st, i) => {
    const x = 0.6 + i * 3.12;
    card(s, x, 1.8, 2.85, 1.5, TEALLT);
    s.addText(st[0], { x, y: 1.92, w: 2.85, h: 0.7, fontFace: HFONT, fontSize: 27, bold: true, color: TEALD, align: "center", valign: "middle", margin: 0 });
    s.addText(st[1], { x, y: 2.68, w: 2.85, h: 0.4, fontFace: BFONT, fontSize: 13, color: MUTED, align: "center", margin: 0 });
  });
  card(s, 0.6, 3.65, 12.1, 2.6);
  iconCircle(s, 0.95, 3.95, 0.8, I.target);
  s.addText("Aucune configuration — le système découvre seul la structure", { x: 1.9, y: 4.0, w: 10.5, h: 0.5, fontFace: HFONT, fontSize: 17, bold: true, color: INK, valign: "middle", margin: 0 });
  s.addText([
    { text: "2 mesures détectées : buts à domicile et à l'extérieur", options: { bullet: true, breakLine: true } },
    { text: "2 colonnes géographiques : équipes reconnues comme des pays → carte mondiale", options: { bullet: true, breakLine: true } },
    { text: "1 colonne date (séries temporelles) + plusieurs dimensions (tournoi, stade…)", options: { bullet: true } },
  ], { x: 1.9, y: 4.75, w: 10.6, h: 1.4, fontFace: BFONT, fontSize: 14, color: INK, paraSpaceAfter: 7, margin: 0 });
  footer(s, slides.length);

  // ============ SLIDE 13 — Résultats / insights ============
  s = pres.addSlide(); slides.push(s); s.background = { color: WHITE };
  title(s, "Des insights pertinents, automatiquement", "Résultats");
  // anomalie callout
  card(s, 0.6, 1.75, 6.0, 1.6, TEALLT);
  iconCircle(s, 0.85, 2.05, 0.7, I.warn, "FEF3C7");
  s.addText("Anomalie détectée", { x: 1.7, y: 2.05, w: 4.6, h: 0.35, fontFace: HFONT, fontSize: 15, bold: true, color: "B45309", margin: 0 });
  s.addText("Australie 31 – 0 Samoa américaines (2001), record du monde, isolé sans aucune connaissance métier.", { x: 1.7, y: 2.42, w: 4.7, h: 0.85, fontFace: BFONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.05 });
  // segment callout
  card(s, 6.7, 1.75, 6.0, 1.6, TEALLT);
  iconCircle(s, 6.95, 2.05, 0.7, I.scale);
  s.addText("Avantage du terrain", { x: 7.8, y: 2.05, w: 4.6, h: 0.35, fontFace: HFONT, fontSize: 15, bold: true, color: TEALD, margin: 0 });
  s.addText("Comparaison de segments : 1,78 but à domicile contre 1,48 ailleurs — l'effet mesuré quantitativement.", { x: 7.8, y: 2.42, w: 4.7, h: 0.85, fontFace: BFONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.05 });
  // tables images
  shot(s, "rapport_anomalies", 0.6, 3.75, 7.4, 1.55, null);
  shot(s, "rapport_findings", 8.3, 3.75, 4.4, 1.4, "Chiffres vérifiés", true);
  shot(s, "rapport_segments", 0.6, 5.55, 7.4, 1.3, null);
  footer(s, slides.length);

  // ============ SLIDE 14 — Tests ============
  s = pres.addSlide(); slides.push(s); s.background = { color: WHITE };
  title(s, "Validation : 22 tests automatisés", "Qualité");
  card(s, 0.6, 1.95, 3.6, 3.9, INK);
  s.addImage({ data: I.checkW, x: 1.75, y: 2.35, w: 1.3, h: 1.3 });
  s.addText("22 / 22", { x: 0.6, y: 3.75, w: 3.6, h: 0.8, fontFace: HFONT, fontSize: 40, bold: true, color: MINT, align: "center", margin: 0 });
  s.addText("tests au vert", { x: 0.6, y: 4.6, w: 3.6, h: 0.4, fontFace: BFONT, fontSize: 15, color: WHITE, align: "center", margin: 0 });
  // breakdown
  const tests = ["Profilage des rôles de colonnes", "Permissions du serveur MCP (refus hors périmètre)", "Vérification des chiffres (7 tests)", "Relance des agents (retry-with-nudge)", "Détection géographique & carte", "Anomalies & comparaison de segments"];
  tests.forEach((t, i) => {
    const y = 2.05 + i * 0.62;
    s.addImage({ data: I.check, x: 4.6, y: y + 0.03, w: 0.34, h: 0.34 });
    s.addText(t, { x: 5.1, y, w: 7.6, h: 0.42, fontFace: BFONT, fontSize: 14, color: INK, valign: "middle", margin: 0 });
  });
  s.addText("Tests sans LLM → rapides, reproductibles ; un client « fictif » simule les défaillances d'agents.", { x: 4.6, y: 5.95, w: 8.1, h: 0.4, fontFace: BFONT, fontSize: 12, italic: true, color: MUTED, margin: 0 });
  footer(s, slides.length);

  // ============ SLIDE 15 — Conclusion ============
  s = pres.addSlide(); slides.push(s); s.background = { color: WHITE };
  title(s, "Conclusion & perspectives", "Bilan");
  card(s, 0.6, 1.85, 5.9, 4.5);
  iconCircle(s, 0.9, 2.15, 0.7, I.flag);
  s.addText("Bilan", { x: 1.75, y: 2.18, w: 4, h: 0.45, fontFace: HFONT, fontSize: 18, bold: true, color: TEALD, valign: "middle", margin: 0 });
  s.addText([
    { text: "Plateforme BI généraliste et automatisée, fonctionnelle de bout en bout", options: { bullet: true, breakLine: true } },
    { text: "Moteur déterministe + 7 agents orchestrés par MCP", options: { bullet: true, breakLine: true } },
    { text: "Dashboard + rapport (web & PDF) reproductibles", options: { bullet: true, breakLine: true } },
    { text: "Fiabilité : filets, vérification des chiffres, suivi des coûts", options: { bullet: true, breakLine: true } },
    { text: "Validée sur 17 769 matchs réels", options: { bullet: true } },
  ], { x: 0.95, y: 2.95, w: 5.3, h: 3.2, fontFace: BFONT, fontSize: 13.5, color: INK, paraSpaceAfter: 9, margin: 0, lineSpacingMultiple: 1.05 });
  card(s, 6.8, 1.85, 5.9, 4.5, TEALLT);
  iconCircle(s, 7.1, 2.15, 0.7, I.rocket);
  s.addText("Perspectives", { x: 7.95, y: 2.18, w: 4, h: 0.45, fontFace: HFONT, fontSize: 18, bold: true, color: TEALD, valign: "middle", margin: 0 });
  s.addText([
    { text: "Interrogation en langage naturel (analyste conversationnel)", options: { bullet: true, breakLine: true } },
    { text: "Connecteurs de données : bases SQL, jointures multi-sources", options: { bullet: true, breakLine: true } },
    { text: "Analyses prédictives (prévision de séries temporelles)", options: { bullet: true, breakLine: true } },
    { text: "Industrialisation : conteneurisation, multi-utilisateurs", options: { bullet: true } },
  ], { x: 7.15, y: 2.95, w: 5.3, h: 3.2, fontFace: BFONT, fontSize: 13.5, color: INK, paraSpaceAfter: 9, margin: 0, lineSpacingMultiple: 1.05 });
  footer(s, slides.length);

  // ============ SLIDE 16 — Merci (light mode, style couverture) ============
  s = pres.addSlide(); slides.push(s); s.background = { data: coverBg };
  coverHeader(s);  // En-tête institutionnel (nom de l'école en français | logo | arabe), comme la couverture
  s.addText("Merci de votre attention", { x: 0.6, y: 2.95, w: 12.13, h: 0.9, fontFace: HFONT, fontSize: 42, bold: true, color: INK, align: "center", margin: 0 });
  s.addText("Questions & discussion", { x: 0.6, y: 3.95, w: 12.13, h: 0.5, fontFace: BFONT, fontSize: 19, italic: true, color: TEAL, align: "center", margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 4.9, y: 4.7, w: 3.53, h: 0.028, fill: { color: TEALD }, line: { type: "none" } });
  s.addText([
    { text: "Réalisé par : ", options: { bold: true, color: TEALD } },
    { text: "Mohamed Rouane  •  Zakariae Trachni", options: { color: INK } },
  ], { x: 0.6, y: 5.05, w: 12.13, h: 0.35, fontFace: BFONT, fontSize: 14, align: "center", margin: 0 });
  s.addText([
    { text: "Encadré par : ", options: { bold: true, color: TEALD } },
    { text: "Pr. Abdelmounaim Kerkri", options: { color: INK } },
    { text: "        Membre du jury : ", options: { bold: true, color: TEALD } },
    { text: "Pr. Asmae El Mezouari", options: { color: INK } },
  ], { x: 0.6, y: 5.5, w: 12.13, h: 0.35, fontFace: BFONT, fontSize: 14, align: "center", margin: 0 });

  // ---------- Notes du présentateur (minutage ~20 min) ----------
  // Minutage cible : 15 min (dont ~3 min 30 de démonstration en direct)
  const notes = [
    "~0:30 — Slide titre. Se présenter, annoncer le sujet : une plateforme BI généraliste multi-agents orchestrée par MCP. Encadrant : Pr. Kerkri.",
    "~0:20 — Annoncer le plan en 6 temps (contexte, objectifs, conception, réalisation, démo/étude de cas, conclusion).",
    "~1:10 — Chaîne décisionnelle (de la donnée à la décision) et ses limites : manuelle, dépendante d'experts, répétitive, spécialisée. Poser la problématique.",
    "~0:40 — Présenter les objectifs ; insister sur le « 0 hypothèse métier » (généralité, tout CSV/Excel/JSON).",
    "~1:00 — État de l'art : LLM (puissants mais hallucinent), agents IA (rôles spécialisés), protocole MCP (registre d'outils + permissions), outils (Python, Plotly, FastAPI).",
    "~1:00 — Architecture en couches : séparation des préoccupations ; le serveur MCP médie tous les accès aux capacités.",
    "~1:00 — Les 7 agents et le moindre privilège ; exemple de l'agent KPI et de ses outils autorisés.",
    "~1:00 — Le moteur déterministe adaptatif : profilage → KPIs → graphiques → insights. Division du travail (moteur = exactitude, agents = jugement) et anti-hallucination.",
    "~0:45 — Fiabilité : filets de sécurité (livrables toujours complets), vérification des chiffres, suivi des coûts.",
    "~3:30 — DÉMONSTRATION EN DIRECT : (1) téléverser un CSV, (2) suivre le pipeline des 7 agents, (3) explorer le tableau de bord + la carte mondiale, (4) ouvrir le rapport. Les aperçus de la slide servent de repli si besoin.",
    "~0:45 — Étude de cas football : 17 769 matchs, aucune configuration, rôles détectés automatiquement (mesures, géo, date).",
    "~1:00 — Résultats : anomalie 31-0 (record du monde), avantage du terrain (1,78 vs 1,48 but), et tous les chiffres du rapport vérifiés.",
    "~0:30 — Qualité : 22 tests automatisés au vert, sans LLM (rapides et reproductibles).",
    "~0:45 — Conclusion : objectifs atteints + perspectives (langage naturel, connecteurs de données, prédictif, industrialisation).",
    "~0:15 — Remercier et ouvrir les questions. Total ≈ 14–15 min.",
  ];
  slides.forEach((sl, i) => { if (notes[i]) sl.addNotes(notes[i]); });

  await pres.writeFile({ fileName: "Soutenance_PFA_MCP_BI.pptx" });
  console.log("OK — Soutenance_PFA_MCP_BI.pptx généré (" + slides.length + " slides, notes incluses)");
})();
