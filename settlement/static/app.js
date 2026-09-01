// Inline editing for the run review table. Numeric edits update in place via
// JSON; structural fee changes (add/remove/reset) reload the page.

function dollars(cents) {
  return (cents / 100).toFixed(2);
}

async function post(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    alert("Save failed: " + (await resp.text()));
    throw new Error("save failed");
  }
  return resp.json();
}

function applyLine(data) {
  const row = document.querySelector(`tr[data-line-id="${data.id}"]`);
  if (!row) return;
  row.dataset.net = data.net_cents;
  row.dataset.share = data.consignor_share_cents;
  row.dataset.mine = data.my_share_cents;
  row.dataset.gross = data.gross_cents;
  row.dataset.fee = data.fee_total;
  row.dataset.excluded = data.excluded ? "1" : "0";
  const set = (role, val, cents) => {
    const el = row.querySelector(`[data-role="${role}"]`);
    if (el) {
      el.textContent = val;
      el.classList.toggle("neg", cents < 0);
    }
  };
  set("fee-total", data.fmt.fee_total, data.fee_total);
  set("net", data.fmt.net, data.net_cents);
  set("share", data.fmt.share, data.consignor_share_cents);
  set("mine", data.fmt.mine, data.my_share_cents);
  row.classList.toggle("excluded", !!data.excluded);
  row.classList.toggle("edited-row", !!data.edited);
  const grossInput = row.querySelector('input[data-api-field="gross"]');
  if (grossInput && document.activeElement !== grossInput) {
    grossInput.value = dollars(data.gross_cents);
  }
  data.fees.forEach((f) => {
    const inp = document.querySelector(`input[data-fee-id="${f.id}"]`);
    if (inp && document.activeElement !== inp) inp.value = dollars(f.amount_cents);
    if (inp) inp.classList.toggle("dirty", !!f.edited);
  });
  recomputeTotals();
}

function recomputeTotals() {
  const totals = { gross: 0, fee: 0, net: 0, share: 0, mine: 0 };
  const perConsignor = {};
  document.querySelectorAll("tr[data-line-id]").forEach((row) => {
    if (row.dataset.excluded === "1") return;
    const c = row.dataset.consignor;
    perConsignor[c] = perConsignor[c] || { gross: 0, fee: 0, net: 0, share: 0, mine: 0 };
    for (const k of Object.keys(totals)) {
      const v = parseInt(row.dataset[k] || "0", 10);
      totals[k] += v;
      perConsignor[c][k] += v;
    }
  });
  const write = (el, obj) => {
    for (const k of Object.keys(totals)) {
      const cell = el.querySelector(`[data-total="${k}"]`);
      if (cell) {
        cell.textContent = "$" + dollars(obj[k]).replace("-", "");
        if (obj[k] < 0) cell.textContent = "-" + cell.textContent;
        cell.classList.toggle("neg", obj[k] < 0);
      }
    }
  };
  const grand = document.querySelector("tr[data-grand-total]");
  if (grand) write(grand, totals);
  document.querySelectorAll("tr[data-consignor-total]").forEach((row) => {
    write(row, perConsignor[row.dataset.consignorTotal] ||
               { gross: 0, fee: 0, net: 0, share: 0, mine: 0 });
  });
}

document.addEventListener("change", async (ev) => {
  const el = ev.target;
  if (el.matches("input[data-api-field], select[data-api-field]")) {
    const line = el.dataset.line;
    let value = el.type === "checkbox" ? (el.checked ? 1 : 0) : el.value;
    const data = await post(`/api/run-line/${line}`, {
      field: el.dataset.apiField, value: value,
    });
    applyLine(data);
  } else if (el.matches("input[data-fee-id]")) {
    const data = await post(`/api/fee/${el.dataset.feeId}`, { amount: el.value });
    applyLine(data);
  }
});

document.addEventListener("click", async (ev) => {
  const el = ev.target;
  if (el.matches("button[data-fee-toggle]")) {
    ev.preventDefault();
    await post(`/api/fee/${el.dataset.feeToggle}`,
               { removed: el.dataset.removed !== "1" });
    location.reload();
  } else if (el.matches("button[data-add-fee]")) {
    ev.preventDefault();
    const line = el.dataset.addFee;
    const name = prompt("Fee name (e.g. 'Etsy Offsite Ads 15%'):");
    if (name === null) return;
    const amount = prompt("Fee amount in dollars (e.g. 4.13):");
    if (amount === null) return;
    await post(`/api/run-line/${line}/fee/add`, { name: name, amount: amount });
    location.reload();
  } else if (el.matches("button[data-reset-fees]")) {
    ev.preventDefault();
    if (!confirm("Recompute this line's fees from the fee schedule? Manual fee edits on this line will be discarded (the change is audited).")) return;
    await post(`/api/run-line/${el.dataset.resetFees}/reset-fees`, {});
    location.reload();
  }
});

document.addEventListener("DOMContentLoaded", recomputeTotals);
