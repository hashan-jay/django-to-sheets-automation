import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { DateField, today } from "./Dashboard";

const EMPTY = {
  sheets: [],
  counts: {},
  rows: [],
};

export default function SheetAnalytics() {
  const [date, setDate] = useState(today);
  const [data, setData] = useState(EMPTY);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [type, setType] = useState("All");
  const [status, setStatus] = useState("All");
  const [brand, setBrand] = useState("All");
  const [sheet, setSheet] = useState("All");

  useEffect(() => {
    let cancel = false;
    setLoading(true);
    setError("");
    api(`/api/sheet-analytics/?date=${encodeURIComponent(date)}`)
      .then((body) => {
        if (!cancel) setData(body || EMPTY);
      })
      .catch((err) => {
        if (!cancel) setError(err.message);
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, [date]);

  const activeSheets = (data.sheets || []).filter((item) => item.saved);
  const brands = useMemo(() => [...new Set((data.rows || []).map((row) => row.brand).filter(Boolean))].sort(), [data]);
  const statuses = useMemo(
    () => [...new Set(["COMPLETED", "PENDING", "PROCESSING", "REJECTED", "OTHER", ...(data.rows || []).map((row) => row.status).filter(Boolean)])],
    [data],
  );
  const rows = useMemo(() => (data.rows || []).filter((row) => matchesFilters(row, { type, status, brand, sheet })), [data, type, status, brand, sheet]);
  const sent = useMemo(() => rows.filter((row) => sentToSheet(row, sheet)), [rows, sheet]);
  const missing = useMemo(() => rows.filter((row) => missingFromSheet(row, sheet)), [rows, sheet]);

  return (
    <section className="analytics">
      <div className="analytics-head">
        <div>
          <h2>Sheet Analytics</h2>
          <p>Deposits and withdrawals compared with the Google Sheets this system has written, matched by transaction ID.</p>
        </div>
        <DateField value={date} onChange={setDate} />
      </div>
      <div className="analytics-filters">
        <label>
          Type
          <select value={type} onChange={(event) => setType(event.target.value)}>
            <option value="All">All</option>
            <option value="DEPOSIT">DEPOSIT</option>
            <option value="WITHDRAW">WITHDRAW</option>
            <option value="REJECT">REJECT</option>
          </select>
        </label>
        <label>
          Status
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="All">All</option>
            {statuses.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          Brand
          <select value={brand} onChange={(event) => setBrand(event.target.value)}>
            <option value="All">All</option>
            {brands.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          Sheet
          <select value={sheet} onChange={(event) => setSheet(event.target.value)}>
            <option value="All">All active sheets</option>
            {activeSheets.map((item) => (
              <option key={item.slot} value={item.name}>{item.name}</option>
            ))}
          </select>
        </label>
      </div>
      {error && <p className="sheet-url-note is-error">{error}</p>}
      {loading && <p className="analytics-wait">Reading saved transactions…</p>}
      <AnalyticsBlock
        title="All brand deposits and withdrawals"
        note={countNote(rows)}
        rows={rows}
        mode="all"
        sheet={sheet}
      />
      <AnalyticsBlock
        title="Sent to the Google Sheet"
        note={countNote(sent)}
        rows={sent}
        mode="sent"
        sheet={sheet}
      />
      <AnalyticsBlock
        title="Not sent to the Google Sheet"
        note={`${countNote(missing)} still missing`}
        rows={missing}
        mode="missing"
        sheet={sheet}
      />
    </section>
  );
}

function matchesFilters(row, filters) {
  if (filters.brand !== "All" && row.brand !== filters.brand) return false;
  if (filters.status !== "All" && row.status !== filters.status) return false;
  if (filters.type === "DEPOSIT" || filters.type === "WITHDRAW") return row.type === filters.type;
  if (filters.type === "REJECT") return row.status === "REJECTED";
  return true;
}

function sentToSheet(row, sheet) {
  if (sheet === "All") return (row.sent_sheets || []).length > 0;
  return (row.sent_sheets || []).includes(sheet);
}

function missingFromSheet(row, sheet) {
  const missing = row.missing || [];
  if (sheet === "All") return missing.length > 0;
  return missing.some((item) => item.sheet === sheet);
}

function countNote(rows) {
  const deposits = rows.filter((row) => row.type === "DEPOSIT").length;
  const withdrawals = rows.filter((row) => row.type === "WITHDRAW").length;
  return `${deposits.toLocaleString()} deposits · ${withdrawals.toLocaleString()} withdrawals`;
}

function AnalyticsBlock({ title, note, rows, mode, sheet }) {
  return (
    <article className="analytics-card">
      <header>
        <h3>{title}</h3>
        <p>{note}</p>
      </header>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time (Sydney)</th>
              <th>ID</th>
              <th>Brand</th>
              <th>Username</th>
              <th>Name</th>
              <th>Amount</th>
              <th>Type</th>
              <th>Status</th>
              <th>{mode === "missing" ? "Why it was not written" : "Google Sheet"}</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td className="empty" colSpan={9}>No transactions in this section for this date.</td>
              </tr>
            )}
            {rows.map((row) => (
              <tr key={`${mode}-${row.brand}-${row.id}`}>
                <td>{row.time}</td>
                <td>{row.id}</td>
                <td>{row.brand}</td>
                <td>{row.username}</td>
                <td>{row.name}</td>
                <td>{row.amount}</td>
                <td>{row.type}</td>
                <td>{row.status}</td>
                <td>{sheetCell(row, mode, sheet)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function sheetCell(row, mode, sheet) {
  const sent = sheet === "All" ? (row.sent_sheets || []) : (row.sent_sheets || []).filter((name) => name === sheet);
  const missing = sheet === "All" ? (row.missing || []) : (row.missing || []).filter((item) => item.sheet === sheet);
  if (mode === "sent") return sent.join(", ");
  if (mode === "missing") return missing.map((item) => `${item.sheet}: ${item.reason}`).join(" ");
  return sent.join(", ") || "Not written yet";
}
