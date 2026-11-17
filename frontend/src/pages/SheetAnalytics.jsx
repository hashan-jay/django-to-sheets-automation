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

  const rows = data.rows || [];
  const sent = useMemo(() => rows.filter((row) => (row.sent_sheets || []).length > 0), [rows]);
  const missing = useMemo(() => rows.filter((row) => (row.missing || []).length > 0), [rows]);
  const counts = data.counts || {};

  return (
    <section className="analytics">
      <div className="analytics-head">
        <div>
          <h2>Sheet Analytics</h2>
          <p>Deposits and withdrawals compared with the Google Sheets this system has written, matched by transaction ID.</p>
        </div>
        <DateField value={date} onChange={setDate} />
      </div>
      {error && <p className="sheet-url-note is-error">{error}</p>}
      {loading && <p className="analytics-wait">Reading saved transactions…</p>}
      <AnalyticsBlock
        title="All brand deposits and withdrawals"
        note={`${Number(counts.all_deposit || 0).toLocaleString()} deposits · ${Number(counts.all_withdraw || 0).toLocaleString()} withdrawals`}
        rows={rows}
        mode="all"
      />
      <AnalyticsBlock
        title="Sent to the Google Sheet"
        note={`${Number(counts.sent_deposit || 0).toLocaleString()} deposits · ${Number(counts.sent_withdraw || 0).toLocaleString()} withdrawals`}
        rows={sent}
        mode="sent"
      />
      <AnalyticsBlock
        title="Not sent to the Google Sheet"
        note={`${Number(counts.missing_deposit || 0).toLocaleString()} deposits · ${Number(counts.missing_withdraw || 0).toLocaleString()} withdrawals still missing`}
        rows={missing}
        mode="missing"
      />
    </section>
  );
}

function AnalyticsBlock({ title, note, rows, mode }) {
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
                <td>{mode === "sent" ? (row.sent_sheets || []).join(", ") : mode === "missing" ? (row.missing || []).map((item) => `${item.sheet}: ${item.reason}`).join(" ") : (row.sent_sheets || []).join(", ") || "Not written yet"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}
