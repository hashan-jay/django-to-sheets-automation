import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { DateField, formatDay, today } from "./Dashboard";

const REGISTERED_COLUMNS = [
  ["username", "Username"],
  ["name", "Name"],
  ["mobile", "Mobile"],
  ["email", "Email"],
  ["brand", "Brand"],
  ["status", "Status"],
  ["type", "Type"],
  ["cash", "Cash", "money"],
  ["lifetime_deposit", "Lifetime deposit", "money"],
  ["lifetime_deposit_count", "Deposit count"],
  ["lifetime_withdraw", "Lifetime withdraw", "money"],
  ["lifetime_withdraw_count", "Withdraw count"],
  ["bank_name", "Bank"],
  ["bank_account_name", "Account name"],
  ["bank_account_number", "Account no"],
  ["bsb", "BSB"],
  ["pay_id", "PayID"],
  ["bank_locked", "Bank lock"],
  ["referrer", "Referrer"],
  ["tags", "Tags"],
  ["registered", "Registered (Sydney)"],
  ["visited", "Last visit (Sydney)"],
  ["cash_site", "Cash site (Sydney)"],
];

const EMPTY = {
  registered: { count: 0, loaded: 0, complete: false, page: 1, pages: 1, rows: [] },
  played: { count: 0, rows: [] },
  joined: { count: 0, rows: [] },
  errors: [],
};

export default function Customers() {
  const [brands, setBrands] = useState([]);
  const [brand, setBrand] = useState("All");
  const [date, setDate] = useState(today);
  const [query, setQuery] = useState("");
  const [q, setQ] = useState("");
  const [playedQuery, setPlayedQuery] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState(EMPTY);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api("/api/brands/")
      .then(setBrands)
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => setQ(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    let stopped = false;
    let inflight = false;
    let timer = 0;

    async function load() {
      if (stopped || inflight) return;
      inflight = true;
      const params = new URLSearchParams({
        date,
        brand,
        q,
        page: String(page),
      });
      try {
        const next = await api(`/api/customers/?${params.toString()}`);
        if (stopped) return;
        setData(next);
        setError("");
        if (next?.registered?.page && next.registered.page !== page) {
          setPage(next.registered.page);
        }
      } catch (err) {
        if (!stopped) setError(err.message);
      } finally {
        inflight = false;
        if (!stopped) setLoading(false);
      }
    }

    setLoading(true);
    load();
    timer = window.setInterval(load, 8000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [date, brand, q, page]);

  const registered = data.registered || EMPTY.registered;
  const played = data.played || EMPTY.played;
  const joined = data.joined || EMPTY.joined;
  const playedNeedle = playedQuery.trim().toLowerCase();
  const playedRows = useMemo(() => {
    const rows = played.rows || [];
    if (!playedNeedle) return rows;
    return rows.filter((row) => {
      const id = String(row.username || "").toLowerCase();
      const name = String(row.name || "").toLowerCase();
      return id.includes(playedNeedle) || name.includes(playedNeedle);
    });
  }, [played.rows, playedNeedle]);
  const dayLabel = formatDay(date);
  const brandLabel = brand === "All" ? "all brands" : brand;

  return (
    <div className="users-page customers-page">
      <header className="users-head">
        <div>
          <h2>Customers</h2>
          <p>
            Players from each brand. The calendar picks the day for who played and who joined.
            The first list is everyone registered.
          </p>
        </div>
        <div className="customer-tools">
          <DateField value={date} onChange={setDate} label="Day" />
          <div className="users-summary">
            <span>
              <strong>{registered.loaded.toLocaleString()}</strong> registered
            </span>
            <span>
              <strong>{played.count.toLocaleString()}</strong> played
            </span>
            <span>
              <strong>{joined.count.toLocaleString()}</strong> joined
            </span>
          </div>
        </div>
      </header>

      {error && <div className="form-error">{error}</div>}
      {(data.errors || []).map((message) => (
        <div className="form-error" key={message}>{message}</div>
      ))}

      <section className="card customer-section">
        <div className="customer-head">
          <div>
            <p className="customer-kicker">Section 1</p>
            <h3>All registered customers</h3>
            <p>
              Every player account saved from the brands.
              {!registered.complete && " The rest of the register is still loading."}
            </p>
          </div>
          <div className="customer-tools">
            <label>
              Brand
              <select
                value={brand}
                onChange={(event) => {
                  setBrand(event.target.value);
                  setPage(1);
                }}
              >
                <option value="All">All brands</option>
                {brands.map((item) => (
                  <option key={item.id} value={item.name}>{item.name}</option>
                ))}
              </select>
            </label>
            <label>
              Search
              <input
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPage(1);
                }}
                placeholder="Username, name, mobile, bank, or PayID"
              />
            </label>
          </div>
        </div>
        <p className="transfers-count">
          {loading ? (
            <>Loading {brandLabel}…</>
          ) : (
            <>
              <strong>{registered.count.toLocaleString()}</strong>
              {registered.count === 1 ? " customer" : " customers"}
              {q ? " match this search" : ""}
            </>
          )}
        </p>
        <div className={`customer-frame${loading ? " is-loading" : ""}`}>
          {loading && <BrandLoading label={`Loading ${brandLabel}`} />}
          <div className="table-wrap customer-table">
          <table>
            <thead>
              <tr>
                {REGISTERED_COLUMNS.map(([key, label]) => (
                  <th key={key}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {!loading && registered.rows.length === 0 && (
                <tr>
                  <td className="empty" colSpan={REGISTERED_COLUMNS.length}>
                    {q ? "No customers match that search." : "No registered customers yet."}
                  </td>
                </tr>
              )}
              {registered.rows.map((row) => (
                <tr key={`${row.brand}-${row.id}`}>
                  {REGISTERED_COLUMNS.map(([key, , kind]) => (
                    <td key={key} className={cellClass(key, kind)}>{cellText(row, key, kind)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
        {!loading && <Pager page={registered.page} pages={registered.pages} onPage={setPage} />}
      </section>

      <section className="card customer-section">
        <div className="customer-head">
          <div>
            <p className="customer-kicker">Section 2</p>
            <h3>Played on {dayLabel}</h3>
            <p>
              Customers with a completed deposit or withdrawal on this day. Games is how many brands
              they were active on. Rejected and pending attempts are not counted.
            </p>
          </div>
          <div className="customer-tools">
            <label>
              Search
              <input
                value={playedQuery}
                onChange={(event) => setPlayedQuery(event.target.value)}
                placeholder="ID or name"
              />
            </label>
          </div>
        </div>
        <p className="transfers-count">
          {loading ? (
            <>Loading {brandLabel}…</>
          ) : playedNeedle ? (
            <>
              <strong>{playedRows.length.toLocaleString()}</strong>
              {playedRows.length === 1 ? " customer matches" : " customers match"} this search
            </>
          ) : (
            <>
              <strong>{played.count.toLocaleString()}</strong>
              {played.count === 1 ? " customer" : " customers"} played
            </>
          )}
        </p>
        <div className={`customer-frame${loading ? " is-loading" : ""}`}>
          {loading && <BrandLoading label={`Loading ${brandLabel}`} />}
          <div className="table-wrap customer-table">
          <table>
            <thead>
              <tr>
                <th>Username</th>
                <th>Name</th>
                <th>Mobile</th>
                <th>Games</th>
                <th>Brands</th>
                <th>Deposits</th>
                <th>Withdrawals</th>
              </tr>
            </thead>
            <tbody>
              {!loading && playedRows.length === 0 && (
                <tr>
                  <td className="empty" colSpan={7}>
                    {playedNeedle ? "No customers match that search." : `No customers played on ${dayLabel}.`}
                  </td>
                </tr>
              )}
              {playedRows.map((row, index) => (
                <tr key={`${row.username}-${row.name}-${row.mobile}-${index}`}>
                  <td>{row.username}</td>
                  <td>{row.name}</td>
                  <td>{row.mobile}</td>
                  <td className="customer-count">{row.games}</td>
                  <td>{(row.brands || []).join(", ")}</td>
                  <td className="customer-count">{row.deposits}</td>
                  <td className="customer-count">{row.withdrawals}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      </section>

      <section className="card customer-section">
        <div className="customer-head">
          <div>
            <p className="customer-kicker">Section 3</p>
            <h3>Joined on {dayLabel}</h3>
            <p>
              Customers who registered on a brand this day, with that brand and how many deposits
              and withdrawals they made the same day.
            </p>
          </div>
        </div>
        <p className="transfers-count">
          {loading ? (
            <>Loading {brandLabel}…</>
          ) : (
            <>
              <strong>{joined.count.toLocaleString()}</strong>
              {joined.count === 1 ? " new customer" : " new customers"}
            </>
          )}
        </p>
        <div className={`customer-frame${loading ? " is-loading" : ""}`}>
          {loading && <BrandLoading label={`Loading ${brandLabel}`} />}
          <div className="table-wrap customer-table">
          <table>
            <thead>
              <tr>
                <th>Username</th>
                <th>Name</th>
                <th>Mobile</th>
                <th>Email</th>
                <th>Brand</th>
                <th>Registered (Sydney)</th>
                <th>Deposits</th>
                <th>Withdrawals</th>
              </tr>
            </thead>
            <tbody>
              {!loading && joined.rows.length === 0 && (
                <tr>
                  <td className="empty" colSpan={8}>No new customers joined on {dayLabel}.</td>
                </tr>
              )}
              {joined.rows.map((row) => (
                <tr key={`${row.brand}-${row.id}`}>
                  <td>{row.username}</td>
                  <td>{row.name}</td>
                  <td>{row.mobile}</td>
                  <td>{row.email}</td>
                  <td className="bank-name">{row.brand}</td>
                  <td>{row.registered}</td>
                  <td className="customer-count">{row.deposits}</td>
                  <td className="customer-count">{row.withdrawals}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      </section>
    </div>
  );
}

function cellClass(key, kind) {
  if (key === "brand") return "bank-name";
  if (kind === "money" || key === "lifetime_deposit_count" || key === "lifetime_withdraw_count") return "customer-count";
  return undefined;
}

function cellText(row, key, kind) {
  const value = row[key];
  if (kind === "money") return money(value);
  if (value == null || value === "") return "";
  return value;
}

function money(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "";
  return amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function BrandLoading({ label }) {
  return (
    <div className="customer-load" role="status" aria-live="polite">
      <div className="customer-load-ring" aria-hidden="true">
        <span />
        <span />
      </div>
      <p>{label}</p>
    </div>
  );
}

function Pager({ page, pages, onPage }) {
  if (!pages || pages <= 1) return null;
  return (
    <div className="customer-pager">
      <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span>
        Page {page.toLocaleString()} of {pages.toLocaleString()}
      </span>
      <button type="button" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </div>
  );
}
