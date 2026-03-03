import { useState, useEffect, useCallback } from "react";

const GOLD_ACCENT = "#c9a96e";
const BG_DARK = "#0f0f0f";
const BG_CARD = "#1a1a1a";
const BORDER = "#2a2a2a";
const TEXT = "#e8e4df";
const TEXT_DIM = "#777";
const FONT = "'Instrument Sans', 'DM Sans', system-ui, sans-serif";
const MONO = "'DM Mono', monospace";

const CATALOG = [
  { cat: "Chain", name: "Cable Chain (per ft)", price: 1.50, unit: "ft" },
  { cat: "Chain", name: "Curb Chain (per ft)", price: 1.75, unit: "ft" },
  { cat: "Chain", name: "Box Chain (per ft)", price: 2.00, unit: "ft" },
  { cat: "Chain", name: "Figaro Chain (per ft)", price: 1.85, unit: "ft" },
  { cat: "Chain", name: "Rope Chain (per ft)", price: 2.25, unit: "ft" },
  { cat: "Chain", name: "Snake Chain (per ft)", price: 2.10, unit: "ft" },
  { cat: "Chain", name: "Stainless Steel Chain (per ft)", price: 1.25, unit: "ft" },
  { cat: "Chain", name: "Waterproof PVD Gold Chain (per ft)", price: 3.50, unit: "ft" },
  { cat: "Clasp", name: "Lobster Clasp (12mm)", price: 0.35, unit: "pc" },
  { cat: "Clasp", name: "Lobster Clasp (16mm)", price: 0.45, unit: "pc" },
  { cat: "Clasp", name: "Toggle Clasp Set", price: 0.85, unit: "pc" },
  { cat: "Clasp", name: "Magnetic Clasp", price: 1.25, unit: "pc" },
  { cat: "Clasp", name: "Box Clasp", price: 0.95, unit: "pc" },
  { cat: "Clasp", name: "S/S Lobster Clasp", price: 0.60, unit: "pc" },
  { cat: "Bead", name: "Pewter Charm Bead", price: 0.75, unit: "pc" },
  { cat: "Bead", name: "Stainless Steel Bead (6mm)", price: 0.40, unit: "pc" },
  { cat: "Bead", name: "Waterproof Gold Bead", price: 0.85, unit: "pc" },
  { cat: "Bead", name: "Crystal Bicone (4mm)", price: 0.15, unit: "pc" },
  { cat: "Bead", name: "Natural Stone Pendant", price: 2.50, unit: "pc" },
  { cat: "Bead", name: "Semi-Precious Gemstone Bead", price: 0.60, unit: "pc" },
  { cat: "Finding", name: "Jump Ring (6mm, 50pk)", price: 2.50, unit: "pk" },
  { cat: "Finding", name: "Head Pins (2in, 50pk)", price: 3.00, unit: "pk" },
  { cat: "Finding", name: "Eye Pins (2in, 50pk)", price: 3.00, unit: "pk" },
  { cat: "Finding", name: "Bead Cap with Loop", price: 0.30, unit: "pc" },
  { cat: "Finding", name: "Crimp Beads (100pk)", price: 2.25, unit: "pk" },
  { cat: "Finding", name: "Earwire Pair (French Hook)", price: 0.65, unit: "pr" },
  { cat: "Finding", name: "Connector Link", price: 0.40, unit: "pc" },
  { cat: "Finding", name: "Cord End Cap", price: 0.35, unit: "pc" },
  { cat: "Cord", name: "Cotton Cord (per yd)", price: 0.50, unit: "yd" },
  { cat: "Cord", name: "Leather Cord (per yd)", price: 1.25, unit: "yd" },
  { cat: "Cord", name: "Beading Wire (per ft)", price: 0.35, unit: "ft" },
];

const CATEGORIES = [...new Set(CATALOG.map(c => c.cat))];

const TIERS = [
  { label: "Beginner", markup: 2.5, wholesale: 1.5, desc: "Starting out, building a customer base" },
  { label: "Intermediate", markup: 3.5, wholesale: 2.0, desc: "Established brand, consistent quality" },
  { label: "Professional", markup: 5.0, wholesale: 2.5, desc: "Premium brand, high demand, unique designs" },
];

const fmt = (n) => n.toFixed(2);
const fmtUSD = (n) => `$${n.toFixed(2)}`;

let idCounter = 0;
const newId = () => ++idCounter;

const emptyRow = () => ({ id: newId(), source: "catalog", catalogIdx: "", name: "", qty: 1, unitPrice: 0, unit: "pc" });

export default function JewelryCostCalculator() {
  const [materials, setMaterials] = useState([emptyRow(), emptyRow(), emptyRow()]);
  const [laborHours, setLaborHours] = useState("");
  const [laborMinutes, setLaborMinutes] = useState("");
  const [hourlyRate, setHourlyRate] = useState("15");
  const [packaging, setPackaging] = useState("1.50");
  const [toolsCost, setToolsCost] = useState("");
  const [boothFees, setBoothFees] = useState("");
  const [otherOverhead, setOtherOverhead] = useState("");

  // Precious metals
  const [silverSpot, setSilverSpot] = useState("");
  const [goldSpot, setGoldSpot] = useState("");
  const [silverWeight, setSilverWeight] = useState("");
  const [goldWeight, setGoldWeight] = useState("");
  const [metalMarkup, setMetalMarkup] = useState("2.5");
  const [fetchingPrices, setFetchingPrices] = useState(false);
  const [priceDate, setPriceDate] = useState("");

  const [showCatalog, setShowCatalog] = useState(null); // row id
  const [catalogFilter, setCatalogFilter] = useState("All");

  const fetchMetalPrices = useCallback(async () => {
    setFetchingPrices(true);
    try {
      const resp = await fetch("https://api.metals.dev/v1/latest?api_key=demo&currency=USD&unit=toz");
      const data = await resp.json();
      if (data.metals) {
        if (data.metals.silver) setSilverSpot(fmt(data.metals.silver));
        if (data.metals.gold) setGoldSpot(fmt(data.metals.gold));
        setPriceDate(new Date().toLocaleString());
      }
    } catch {
      try {
        const resp2 = await fetch("https://metals-api.com/api/latest?access_key=demo&base=USD&symbols=XAG,XAU");
        const data2 = await resp2.json();
        if (data2.rates) {
          if (data2.rates.XAG) setSilverSpot(fmt(1 / data2.rates.XAG));
          if (data2.rates.XAU) setGoldSpot(fmt(1 / data2.rates.XAU));
          setPriceDate(new Date().toLocaleString());
        }
      } catch {
        setPriceDate("Could not fetch — enter manually");
      }
    }
    setFetchingPrices(false);
  }, []);

  const updateRow = (id, field, value) => {
    setMaterials(prev => prev.map(r => {
      if (r.id !== id) return r;
      const updated = { ...r, [field]: value };
      if (field === "catalogIdx" && value !== "") {
        const item = CATALOG[parseInt(value)];
        if (item) {
          updated.name = item.name;
          updated.unitPrice = item.price;
          updated.unit = item.unit;
        }
      }
      return updated;
    }));
  };

  const addRow = () => setMaterials(prev => [...prev, emptyRow()]);
  const removeRow = (id) => setMaterials(prev => prev.length > 1 ? prev.filter(r => r.id !== id) : prev);

  const selectCatalogItem = (rowId, catIdx) => {
    updateRow(rowId, "catalogIdx", String(catIdx));
    setShowCatalog(null);
  };

  // Calculations
  const materialTotal = materials.reduce((sum, r) => sum + (parseFloat(r.qty) || 0) * (parseFloat(r.unitPrice) || 0), 0);

  const silverVal = ((parseFloat(silverWeight) || 0) / 31.1035) * (parseFloat(silverSpot) || 0) * (parseFloat(metalMarkup) || 1);
  const goldVal = ((parseFloat(goldWeight) || 0) / 31.1035) * (parseFloat(goldSpot) || 0) * (parseFloat(metalMarkup) || 1);
  const metalTotal = silverVal + goldVal;

  const laborTotal = ((parseFloat(laborHours) || 0) + (parseFloat(laborMinutes) || 0) / 60) * (parseFloat(hourlyRate) || 0);

  const overheadTotal = (parseFloat(packaging) || 0) + (parseFloat(toolsCost) || 0) + (parseFloat(boothFees) || 0) + (parseFloat(otherOverhead) || 0);

  const totalCost = materialTotal + metalTotal + laborTotal + overheadTotal;

  const inputStyle = {
    width: "100%",
    padding: "8px 10px",
    fontSize: 13,
    fontFamily: FONT,
    background: "#111",
    border: `1px solid ${BORDER}`,
    borderRadius: 6,
    color: TEXT,
    outline: "none",
    transition: "border-color 0.15s",
    boxSizing: "border-box",
  };

  const labelStyle = {
    fontSize: 11,
    fontFamily: MONO,
    color: TEXT_DIM,
    textTransform: "uppercase",
    letterSpacing: "0.06em",
    marginBottom: 4,
    display: "block",
  };

  const sectionTitle = (icon, text) => (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
      <span style={{ fontSize: 18 }}>{icon}</span>
      <span style={{ fontSize: 15, fontWeight: 700, color: TEXT }}>{text}</span>
    </div>
  );

  const card = (children, style = {}) => (
    <div style={{
      background: BG_CARD,
      border: `1px solid ${BORDER}`,
      borderRadius: 10,
      padding: "20px 20px",
      marginBottom: 16,
      ...style,
    }}>
      {children}
    </div>
  );

  return (
    <div style={{
      minHeight: "100vh",
      background: `linear-gradient(145deg, ${BG_DARK} 0%, #1a1a2e 50%, ${BG_DARK} 100%)`,
      fontFamily: FONT,
      color: TEXT,
      padding: "24px 16px 60px",
    }}>
      <link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet" />

      {/* HEADER */}
      <div style={{ maxWidth: 800, margin: "0 auto", textAlign: "center", marginBottom: 32 }}>
        <div style={{ fontSize: 11, fontFamily: MONO, letterSpacing: "0.15em", textTransform: "uppercase", color: GOLD_ACCENT, marginBottom: 8 }}>
          Continental Beads · Free Tool
        </div>
        <h1 style={{ fontSize: 28, fontWeight: 700, margin: "0 0 6px", color: "#fff", lineHeight: 1.25 }}>
          Jewelry Design Cost Calculator
        </h1>
        <p style={{ fontSize: 14, color: TEXT_DIM, margin: 0, lineHeight: 1.5 }}>
          Price your handmade jewelry with confidence. Itemize materials, factor in precious metals at live spot prices, and compare pricing strategies side by side.
        </p>
      </div>

      <div style={{ maxWidth: 800, margin: "0 auto" }}>

        {/* ====== SECTION 1: MATERIALS ====== */}
        {card(
          <>
            {sectionTitle("📦", "Materials & Components")}
            <p style={{ fontSize: 12, color: TEXT_DIM, margin: "0 0 12px", lineHeight: 1.5 }}>
              Add each component. Pick from the Continental Beads catalog or enter custom items.
            </p>

            {materials.map((row, i) => (
              <div key={row.id} style={{
                display: "grid",
                gridTemplateColumns: "1fr 60px 80px 80px 32px",
                gap: 8,
                alignItems: "end",
                marginBottom: 8,
                paddingBottom: 8,
                borderBottom: i < materials.length - 1 ? `1px solid #222` : "none",
              }}>
                <div>
                  {i === 0 && <span style={labelStyle}>Item</span>}
                  <div style={{ position: "relative" }}>
                    <input
                      value={row.name}
                      onChange={e => updateRow(row.id, "name", e.target.value)}
                      placeholder="Type or pick from catalog →"
                      style={inputStyle}
                      onFocus={() => updateRow(row.id, "source", "custom")}
                    />
                    <button
                      onClick={() => setShowCatalog(showCatalog === row.id ? null : row.id)}
                      style={{
                        position: "absolute",
                        right: 4,
                        top: "50%",
                        transform: "translateY(-50%)",
                        background: showCatalog === row.id ? GOLD_ACCENT : "transparent",
                        color: showCatalog === row.id ? BG_DARK : GOLD_ACCENT,
                        border: `1px solid ${GOLD_ACCENT}40`,
                        borderRadius: 4,
                        fontSize: 10,
                        padding: "2px 6px",
                        cursor: "pointer",
                        fontFamily: MONO,
                        fontWeight: 600,
                      }}
                    >
                      CBS
                    </button>
                  </div>

                  {showCatalog === row.id && (
                    <div style={{
                      position: "absolute",
                      zIndex: 50,
                      background: "#1a1a1a",
                      border: `1px solid ${GOLD_ACCENT}40`,
                      borderRadius: 8,
                      padding: 12,
                      width: 340,
                      maxHeight: 280,
                      overflowY: "auto",
                      marginTop: 4,
                      boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
                    }}>
                      <div style={{ display: "flex", gap: 4, marginBottom: 8, flexWrap: "wrap" }}>
                        {["All", ...CATEGORIES].map(c => (
                          <button key={c} onClick={() => setCatalogFilter(c)} style={{
                            fontSize: 10, padding: "3px 8px", borderRadius: 4, border: "none",
                            background: catalogFilter === c ? `${GOLD_ACCENT}25` : "transparent",
                            color: catalogFilter === c ? GOLD_ACCENT : TEXT_DIM,
                            cursor: "pointer", fontFamily: MONO,
                          }}>{c}</button>
                        ))}
                      </div>
                      {CATALOG.filter(c => catalogFilter === "All" || c.cat === catalogFilter).map((item, ci) => {
                        const realIdx = CATALOG.indexOf(item);
                        return (
                          <div key={ci}
                            onClick={() => selectCatalogItem(row.id, realIdx)}
                            style={{
                              padding: "6px 8px",
                              borderRadius: 4,
                              cursor: "pointer",
                              fontSize: 12,
                              display: "flex",
                              justifyContent: "space-between",
                              alignItems: "center",
                              transition: "background 0.1s",
                            }}
                            onMouseEnter={e => e.currentTarget.style.background = "#252525"}
                            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                          >
                            <span>
                              <span style={{ color: GOLD_ACCENT, fontSize: 10, marginRight: 6 }}>{item.cat}</span>
                              {item.name}
                            </span>
                            <span style={{ fontFamily: MONO, color: GOLD_ACCENT, fontSize: 11 }}>
                              ${fmt(item.price)}/{item.unit}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                <div>
                  {i === 0 && <span style={labelStyle}>Qty</span>}
                  <input
                    type="number"
                    min="0"
                    step="0.5"
                    value={row.qty}
                    onChange={e => updateRow(row.id, "qty", e.target.value)}
                    style={{ ...inputStyle, textAlign: "center" }}
                  />
                </div>

                <div>
                  {i === 0 && <span style={labelStyle}>Unit $</span>}
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={row.unitPrice}
                    onChange={e => updateRow(row.id, "unitPrice", e.target.value)}
                    style={{ ...inputStyle, textAlign: "right" }}
                  />
                </div>

                <div>
                  {i === 0 && <span style={labelStyle}>Subtotal</span>}
                  <div style={{
                    ...inputStyle,
                    background: "transparent",
                    border: "1px solid transparent",
                    textAlign: "right",
                    fontFamily: MONO,
                    color: GOLD_ACCENT,
                    fontWeight: 600,
                  }}>
                    {fmtUSD((parseFloat(row.qty) || 0) * (parseFloat(row.unitPrice) || 0))}
                  </div>
                </div>

                <div>
                  {i === 0 && <span style={{ ...labelStyle, visibility: "hidden" }}>X</span>}
                  <button
                    onClick={() => removeRow(row.id)}
                    style={{
                      width: 28, height: 36, border: "none", borderRadius: 4,
                      background: "transparent", color: "#555", cursor: "pointer",
                      fontSize: 16, display: "flex", alignItems: "center", justifyContent: "center",
                    }}
                    onMouseEnter={e => e.currentTarget.style.color = "#dc2626"}
                    onMouseLeave={e => e.currentTarget.style.color = "#555"}
                  >×</button>
                </div>
              </div>
            ))}

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12 }}>
              <button onClick={addRow} style={{
                padding: "6px 14px", fontSize: 12, fontWeight: 600,
                border: `1px dashed ${BORDER}`, borderRadius: 6,
                background: "transparent", color: TEXT_DIM, cursor: "pointer",
                fontFamily: FONT,
              }}>+ Add Material</button>
              <div style={{ fontFamily: MONO, fontSize: 13, color: TEXT }}>
                Materials: <span style={{ color: GOLD_ACCENT, fontWeight: 700 }}>{fmtUSD(materialTotal)}</span>
              </div>
            </div>
          </>
        )}

        {/* ====== SECTION 2: PRECIOUS METALS ====== */}
        {card(
          <>
            {sectionTitle("✨", "Precious Metals (Sterling Silver & Gold)")}
            <p style={{ fontSize: 12, color: TEXT_DIM, margin: "0 0 12px", lineHeight: 1.5 }}>
              For components priced by weight. Enter weight in grams — the calculator uses troy ounce spot prices.
            </p>

            <div style={{ display: "flex", gap: 8, alignItems: "end", marginBottom: 12, flexWrap: "wrap" }}>
              <button onClick={fetchMetalPrices} disabled={fetchingPrices} style={{
                padding: "7px 14px", fontSize: 11, fontWeight: 600,
                border: "none", borderRadius: 6,
                background: GOLD_ACCENT, color: BG_DARK, cursor: fetchingPrices ? "wait" : "pointer",
                fontFamily: FONT, opacity: fetchingPrices ? 0.6 : 1,
              }}>
                {fetchingPrices ? "Fetching..." : "Fetch Live Spot Prices"}
              </button>
              {priceDate && <span style={{ fontSize: 10, color: TEXT_DIM, fontFamily: MONO }}>{priceDate}</span>}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              {/* Silver */}
              <div style={{ padding: 12, background: "#111", borderRadius: 8, border: `1px solid ${BORDER}` }}>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10, color: "#ccc" }}>Silver</div>
                <div style={{ marginBottom: 8 }}>
                  <span style={labelStyle}>Spot Price ($/troy oz)</span>
                  <input type="number" step="0.01" value={silverSpot} onChange={e => setSilverSpot(e.target.value)} placeholder="e.g. 32.50" style={inputStyle} />
                </div>
                <div>
                  <span style={labelStyle}>Weight (grams)</span>
                  <input type="number" step="0.1" value={silverWeight} onChange={e => setSilverWeight(e.target.value)} placeholder="0" style={inputStyle} />
                </div>
                {silverVal > 0 && <div style={{ marginTop: 8, fontFamily: MONO, fontSize: 12, color: GOLD_ACCENT }}>
                  Melt: {fmtUSD(((parseFloat(silverWeight) || 0) / 31.1035) * (parseFloat(silverSpot) || 0))} → With {metalMarkup}x markup: {fmtUSD(silverVal)}
                </div>}
              </div>

              {/* Gold */}
              <div style={{ padding: 12, background: "#111", borderRadius: 8, border: `1px solid ${BORDER}` }}>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10, color: "#ccc" }}>Gold</div>
                <div style={{ marginBottom: 8 }}>
                  <span style={labelStyle}>Spot Price ($/troy oz)</span>
                  <input type="number" step="0.01" value={goldSpot} onChange={e => setGoldSpot(e.target.value)} placeholder="e.g. 2950.00" style={inputStyle} />
                </div>
                <div>
                  <span style={labelStyle}>Weight (grams)</span>
                  <input type="number" step="0.1" value={goldWeight} onChange={e => setGoldWeight(e.target.value)} placeholder="0" style={inputStyle} />
                </div>
                {goldVal > 0 && <div style={{ marginTop: 8, fontFamily: MONO, fontSize: 12, color: GOLD_ACCENT }}>
                  Melt: {fmtUSD(((parseFloat(goldWeight) || 0) / 31.1035) * (parseFloat(goldSpot) || 0))} → With {metalMarkup}x markup: {fmtUSD(goldVal)}
                </div>}
              </div>
            </div>

            <div style={{ marginTop: 12 }}>
              <span style={labelStyle}>Artistry Markup on Melt Value</span>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <input
                  type="range" min="1" max="5" step="0.1"
                  value={metalMarkup}
                  onChange={e => setMetalMarkup(e.target.value)}
                  style={{ flex: 1, accentColor: GOLD_ACCENT }}
                />
                <span style={{ fontFamily: MONO, fontSize: 14, color: GOLD_ACCENT, fontWeight: 700, minWidth: 40 }}>{metalMarkup}x</span>
              </div>
              <div style={{ fontSize: 10, color: TEXT_DIM, marginTop: 2 }}>
                Industry standard: 2.5–3x melt value for sterling silver artisan work
              </div>
            </div>

            <div style={{ textAlign: "right", marginTop: 10, fontFamily: MONO, fontSize: 13 }}>
              Precious Metals: <span style={{ color: GOLD_ACCENT, fontWeight: 700 }}>{fmtUSD(metalTotal)}</span>
            </div>
          </>
        )}

        {/* ====== SECTION 3: LABOR ====== */}
        {card(
          <>
            {sectionTitle("⏱️", "Labor")}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
              <div>
                <span style={labelStyle}>Hours</span>
                <input type="number" min="0" value={laborHours} onChange={e => setLaborHours(e.target.value)} placeholder="0" style={inputStyle} />
              </div>
              <div>
                <span style={labelStyle}>Minutes</span>
                <input type="number" min="0" max="59" value={laborMinutes} onChange={e => setLaborMinutes(e.target.value)} placeholder="0" style={inputStyle} />
              </div>
              <div>
                <span style={labelStyle}>Hourly Rate ($)</span>
                <input type="number" min="0" step="0.5" value={hourlyRate} onChange={e => setHourlyRate(e.target.value)} placeholder="15" style={inputStyle} />
              </div>
            </div>
            <div style={{ textAlign: "right", marginTop: 10, fontFamily: MONO, fontSize: 13 }}>
              Labor: <span style={{ color: GOLD_ACCENT, fontWeight: 700 }}>{fmtUSD(laborTotal)}</span>
            </div>
          </>
        )}

        {/* ====== SECTION 4: OVERHEAD ====== */}
        {card(
          <>
            {sectionTitle("📋", "Overhead (per piece)")}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 12 }}>
              <div>
                <span style={labelStyle}>Packaging</span>
                <input type="number" min="0" step="0.25" value={packaging} onChange={e => setPackaging(e.target.value)} placeholder="1.50" style={inputStyle} />
              </div>
              <div>
                <span style={labelStyle}>Tools / Equipment</span>
                <input type="number" min="0" step="0.25" value={toolsCost} onChange={e => setToolsCost(e.target.value)} placeholder="0" style={inputStyle} />
              </div>
              <div>
                <span style={labelStyle}>Booth / Listing Fees</span>
                <input type="number" min="0" step="0.25" value={boothFees} onChange={e => setBoothFees(e.target.value)} placeholder="0" style={inputStyle} />
              </div>
              <div>
                <span style={labelStyle}>Other</span>
                <input type="number" min="0" step="0.25" value={otherOverhead} onChange={e => setOtherOverhead(e.target.value)} placeholder="0" style={inputStyle} />
              </div>
            </div>
            <div style={{ textAlign: "right", marginTop: 10, fontFamily: MONO, fontSize: 13 }}>
              Overhead: <span style={{ color: GOLD_ACCENT, fontWeight: 700 }}>{fmtUSD(overheadTotal)}</span>
            </div>
          </>
        )}

        {/* ====== COST SUMMARY ====== */}
        {card(
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
            <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
              {[
                { label: "Materials", val: materialTotal },
                { label: "Metals", val: metalTotal },
                { label: "Labor", val: laborTotal },
                { label: "Overhead", val: overheadTotal },
              ].map(s => (
                <div key={s.label} style={{ textAlign: "center" }}>
                  <div style={{ fontSize: 10, fontFamily: MONO, color: TEXT_DIM, textTransform: "uppercase" }}>{s.label}</div>
                  <div style={{ fontSize: 14, fontFamily: MONO, fontWeight: 600, color: TEXT }}>{fmtUSD(s.val)}</div>
                </div>
              ))}
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 10, fontFamily: MONO, color: TEXT_DIM, textTransform: "uppercase" }}>Total Cost</div>
              <div style={{ fontSize: 26, fontWeight: 700, fontFamily: MONO, color: GOLD_ACCENT }}>{fmtUSD(totalCost)}</div>
            </div>
          </div>,
          { background: `linear-gradient(135deg, ${BG_CARD}, #1f1f2e)`, border: `1px solid ${GOLD_ACCENT}30` }
        )}

        {/* ====== SECTION 5: PRICING TIERS ====== */}
        {sectionTitle("💰", "Pricing Strategy — Choose Your Tier")}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 24 }}>
          {TIERS.map((tier, ti) => {
            const retail = totalCost * tier.markup;
            const wholesale = totalCost * tier.wholesale;
            const profit = retail - totalCost;
            const margin = retail > 0 ? ((profit / retail) * 100) : 0;

            return (
              <div key={ti} style={{
                background: ti === 1 ? `linear-gradient(145deg, #1f1f2e, ${BG_CARD})` : BG_CARD,
                border: ti === 1 ? `2px solid ${GOLD_ACCENT}` : `1px solid ${BORDER}`,
                borderRadius: 10,
                padding: "20px 16px",
                position: "relative",
                overflow: "hidden",
              }}>
                {ti === 1 && (
                  <div style={{
                    position: "absolute",
                    top: 0,
                    right: 0,
                    background: GOLD_ACCENT,
                    color: BG_DARK,
                    fontSize: 9,
                    fontWeight: 700,
                    fontFamily: MONO,
                    padding: "3px 10px",
                    borderBottomLeftRadius: 6,
                    textTransform: "uppercase",
                    letterSpacing: "0.08em",
                  }}>
                    Recommended
                  </div>
                )}

                <div style={{ fontSize: 14, fontWeight: 700, color: ti === 1 ? GOLD_ACCENT : TEXT, marginBottom: 2 }}>
                  {tier.label}
                </div>
                <div style={{ fontSize: 10, color: TEXT_DIM, marginBottom: 16, lineHeight: 1.4 }}>
                  {tier.desc}
                </div>

                <div style={{ fontSize: 10, fontFamily: MONO, color: TEXT_DIM, textTransform: "uppercase", marginBottom: 4 }}>
                  Retail ({tier.markup}x markup)
                </div>
                <div style={{
                  fontSize: 28, fontWeight: 700, fontFamily: MONO,
                  color: ti === 1 ? GOLD_ACCENT : TEXT,
                  marginBottom: 12,
                }}>
                  {fmtUSD(retail)}
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                  <div style={{ background: "#111", borderRadius: 6, padding: "8px 10px", textAlign: "center" }}>
                    <div style={{ fontSize: 9, fontFamily: MONO, color: TEXT_DIM, textTransform: "uppercase" }}>Wholesale</div>
                    <div style={{ fontSize: 15, fontWeight: 700, fontFamily: MONO, color: TEXT }}>{fmtUSD(wholesale)}</div>
                    <div style={{ fontSize: 9, fontFamily: MONO, color: TEXT_DIM }}>{tier.wholesale}x cost</div>
                  </div>
                  <div style={{ background: "#111", borderRadius: 6, padding: "8px 10px", textAlign: "center" }}>
                    <div style={{ fontSize: 9, fontFamily: MONO, color: TEXT_DIM, textTransform: "uppercase" }}>Profit</div>
                    <div style={{ fontSize: 15, fontWeight: 700, fontFamily: MONO, color: "#22c55e" }}>{fmtUSD(profit)}</div>
                    <div style={{ fontSize: 9, fontFamily: MONO, color: TEXT_DIM }}>{fmt(margin)}% margin</div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* ====== CTA ====== */}
        {card(
          <div style={{ textAlign: "center", padding: "8px 0" }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: TEXT, marginBottom: 6 }}>
              Ready to stock up on supplies?
            </div>
            <div style={{ fontSize: 12, color: TEXT_DIM, marginBottom: 14, lineHeight: 1.5 }}>
              Continental Beads carries 1,000+ chains, findings, beads, and charms — all nickel-free and hypoallergenic.
              Wholesale accounts get 50% off retail pricing.
            </div>
            <a
              href="https://www.continentalbeadsuppliers.com/collections/all"
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: "inline-block",
                padding: "10px 28px",
                fontSize: 13,
                fontWeight: 700,
                background: GOLD_ACCENT,
                color: BG_DARK,
                borderRadius: 6,
                textDecoration: "none",
                fontFamily: FONT,
              }}
            >
              Shop Continental Beads →
            </a>
          </div>,
          { background: `linear-gradient(135deg, #1a1a2e, ${BG_CARD})`, border: `1px solid ${GOLD_ACCENT}20` }
        )}

        {/* Footer */}
        <div style={{ textAlign: "center", fontSize: 10, color: TEXT_DIM, fontFamily: MONO, marginTop: 12 }}>
          Tool provided by <a href="https://www.continentalbeadsuppliers.com" target="_blank" rel="noopener noreferrer" style={{ color: GOLD_ACCENT, textDecoration: "none" }}>Continental Bead Suppliers</a> · Las Vegas, NV
        </div>
      </div>
    </div>
  );
}
