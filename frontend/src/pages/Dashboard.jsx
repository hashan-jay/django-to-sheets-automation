import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";

const COLUMNS = [
  ["time", "Time (Sydney)"],
  ["id", "ID"],
  ["username", "Username"],
  ["name", "Name"],
  ["mobile", "Mobile"],
  ["amount", "Amount"],
  ["type", "Type"],
  ["bank_name", "Bank Name"],
  ["bank_account_name", "Bank Account Name"],
  ["bank", "Bank"],
  ["acc_name", "Acc Name"],
  ["acc_no", "Acc No"],
  ["bsb", "BSB"],
  ["pay_id", "PayID"],
  ["brand", "Brand"],
  ["created", "Created (Sydney)"],
  ["processed", "Processed (Sydney)"],
  ["status", "Status"],
  ["detail", "Detail"],
];

const ROW_HEIGHT = 36;
const EMPTY_BUCKET = { count: 0, amount: "0.00" };

const EMPTY_STATS = {
  pending_deposit: EMPTY_BUCKET,
  pending_withdraw: EMPTY_BUCKET,
  completed_deposit: EMPTY_BUCKET,
  completed_withdraw: EMPTY_BUCKET,
  bonus: EMPTY_BUCKET,
  forfeited: EMPTY_BUCKET,
  processing: EMPTY_BUCKET,
  rejected: EMPTY_BUCKET,
  other: EMPTY_BUCKET,
  net_completed: EMPTY_BUCKET,
  row_count: EMPTY_BUCKET,
};

const SORTS = [
  "Sort by Time",
  "Sort by Received Time",
  "Sort by Alphabetical Order",
  "Sort by Amount",
];

const WIDGETS = [
  ["pending_deposit", "Pending deposits", "pending-in", "PENDING", "DEPOSIT"],
  ["pending_withdraw", "Pending withdrawals", "pending-out", "PENDING", "WITHDRAW"],
  ["completed_deposit", "Completed deposits", "done-in", "COMPLETED", "DEPOSIT"],
  ["completed_withdraw", "Completed withdrawals", "done-out", "COMPLETED", "WITHDRAW"],
  ["bonus", "Bonus", "bonus", "All statuses", "BONUS"],
  ["forfeited", "Forfeited", "forfeited", "All statuses", "FORFEITED"],
  ["processing", "Processing", "processing", "PROCESSING", "All types"],
  ["rejected", "Rejected", "rejected", "REJECTED", "All types"],
];

export function today() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Australia/Sydney",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

export default function Dashboard() {
  const [brands, setBrands] = useState([]);
  const [group] = useState("All");
  const [sheetUrl, setSheetUrl] = useState("");
  const [depositStart, setDepositStart] = useState("105");
  const [withdrawStart, setWithdrawStart] = useState("1024");
  const [sheetNote, setSheetNote] = useState("");
  const [sheetBusy, setSheetBusy] = useState(false);
  const [rowsBusy, setRowsBusy] = useState(false);
  const [brand, setBrand] = useState("All");
  const [date, setDate] = useState(today);
  const [type, setType] = useState("All types");
  const [status, setStatus] = useState("All statuses");
  const [sortBy, setSortBy] = useState("Sort by Time");
  const [focus, setFocus] = useState("");
  const [live, setLive] = useState(true);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [opened, setOpened] = useState(null);
  const revision = useRef("");
  const tableRef = useRef(null);
  const tableScroll = useRef(null);
  const openRow = useCallback((row) => openTransaction(row, setOpened), []);

  useEffect(() => {
    api("/api/brands/")
      .then(setBrands)
      .catch((err) => setError(err.message));
    api("/api/google-sheet/")
      .then((sheet) => {
        setSheetUrl(sheet.sheet_url || "");
        setDepositStart(String(sheet.deposit_start_row || 105));
        setWithdrawStart(String(sheet.withdraw_start_row || 1024));
        setSheetNote(sheet.last_error || "");
      })
      .catch(() => {});
  }, []);

  async function saveStartRows(event) {
    event.preventDefault();
    setRowsBusy(true);
    setSheetNote("");
    try {
      const saved = await api("/api/google-sheet/", {
        method: "POST",
        body: { deposit_start_row: depositStart.trim(), withdraw_start_row: withdrawStart.trim() },
      });
      setDepositStart(String(saved.deposit_start_row));
      setWithdrawStart(String(saved.withdraw_start_row));
      setSheetNote(`Saved. Deposits start at row ${saved.deposit_start_row}. Withdrawals start at row ${saved.withdraw_start_row}.`);
    } catch (err) {
      setSheetNote(err.message);
    } finally {
      setRowsBusy(false);
    }
  }

  async function saveSheet(event) {
    event.preventDefault();
    setSheetBusy(true);
    setSheetNote("");
    try {
      const saved = await api("/api/google-sheet/", { method: "POST", body: { sheet_url: sheetUrl.trim() } });
      setSheetUrl(saved.sheet_url || "");
      if (saved.last_error) setSheetNote(saved.last_error);
      else if (saved.written_now) setSheetNote(`Wrote ${saved.written_now} rows.`);
      else setSheetNote("Saved. Completed deposits and withdrawals for each date go on that day's numbered tab.");
    } catch (err) {
      setSheetNote(err.message);
    } finally {
      setSheetBusy(false);
    }
  }

  useEffect(() => {
    let stopped = false;
    let timer = 0;
    let loading = false;
    revision.current = "";

    async function load() {
      if (loading) return;
      loading = true;
      const params = new URLSearchParams({ date, group, brand, type: "All types", status: "All statuses" });
      if (revision.current) params.set("rev", revision.current);
      try {
        const next = await api(`/api/dashboard/?${params.toString()}`);
        if (stopped) return;
        if (next?.unchanged) {
          if (next.revision) revision.current = String(next.revision);
          setError("");
          return;
        }
        if (next?.revision) revision.current = String(next.revision);
        setData(next);
        setError("");
      } catch (err) {
        if (!stopped) setError(err.message);
      } finally {
        loading = false;
      }
    }

    load();
    if (live) timer = window.setInterval(load, 1000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [group, brand, date, live]);

  function selectWidget(key, nextStatus, nextType) {
    if (focus === key) {
      setFocus("");
      setStatus("All statuses");
      setType("All types");
    } else {
      setFocus(key);
      setStatus(nextStatus);
      setType(nextType);
    }
    const panel = tableRef.current;
    const scroller = panel?.querySelector(".table-wrap");
    if (scroller) scroller.scrollTop = 0;
    panel?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function clearFocus() {
    setFocus("");
    setStatus("All statuses");
    setType("All types");
  }

  async function refreshNow() {
    setRefreshing(true);
    setError("");
    try {
      await api("/api/sync/", { method: "POST", body: { date } });
      const params = new URLSearchParams({ date, group, brand, type: "All types", status: "All statuses" });
      const next = await api(`/api/dashboard/?${params.toString()}`);
      if (next?.revision) revision.current = String(next.revision);
      if (!next?.unchanged) setData(next);
    } catch (err) {
      setError(err.message);
    } finally {
      setRefreshing(false);
    }
  }

  const stats = data?.stats || EMPTY_STATS;
  const pulse = useStatPulse(stats);
  const previewKey = focus;
  const previewRows = useMemo(() => {
    if (!previewKey) return [];
    return (data?.rows || [])
      .filter((row) => matchesWidget(row, previewKey))
      .slice()
      .sort((left, right) => compareText(right.time, left.time))
      .slice(0, 5);
  }, [data, previewKey]);
  const rows = useMemo(() => {
    const source = (data?.rows || []).filter((row) => (focus ? matchesWidget(row, focus) : passesDropdown(row, status, type)));
    return sortRows(source, sortBy);
  }, [data, sortBy, focus, status, type]);
  if (data?.stats && data.stats.row_count == null) revision.current = "";
  const widgets = stats.other?.count ? [...WIDGETS, ["other", "Other", "other", "OTHER", "All types"]] : WIDGETS;
  const focusTitle = widgetTitle(focus, widgets);
  const brandSummary = data?.brand_summary || [];
  const visibleBrands = useMemo(
    () => brands.filter((item) => group === "All" || item.group === group),
    [brands, group],
  );
  const windowRange = useVisibleRows(tableScroll, rows.length, ROW_HEIGHT);
  const visibleRows = rows.slice(windowRange.start, windowRange.end);

  const viewStatus = friendlyStatus(live, refreshing, data);
  const dayCount = Number(bucket(stats, "row_count").count) || 0;
  const completedIn = bucket(stats, "completed_deposit");
  const completedOut = bucket(stats, "completed_withdraw");
  const netParts = netSplit(completedIn.amount, completedOut.amount);

  return (
    <>
    <section className="command" aria-label="Filters">
    <div className="command-head">
      <div>
        <h2>KABOOM77</h2>
        <p>Date and live updates apply to bank balances and transactions together. Completed deposits and withdrawals are written to the day tab in this Google Sheet.</p>
      </div>
      <p className="command-scope">{formatDay(date)}</p>
    </div>
    <form className="sheet-url" onSubmit={saveSheet}>
      <label htmlFor="sheet-url">Writing Google Sheet</label>
      <div className="sheet-url-row">
        <input
          id="sheet-url"
          type="url"
          inputMode="url"
          spellCheck={false}
          autoComplete="off"
          value={sheetUrl}
          placeholder="Paste the Google Sheet link"
          onChange={(event) => setSheetUrl(event.target.value)}
        />
        <button type="submit" disabled={sheetBusy}>{sheetBusy ? "Saving…" : "Save"}</button>
      </div>
      <p className={sheetNote ? (sheetNote.startsWith("Saved") || sheetNote.startsWith("Wrote") ? "sheet-url-note" : "sheet-url-note is-error") : "sheet-url-note"}>
        {sheetNote || "Each date is written on the tab with that day’s number. Staff cells are left as you typed them."}
      </p>
    </form>
    <form className="sheet-starts" onSubmit={saveStartRows}>
      <label>
        Deposit start row
        <input
          inputMode="numeric"
          value={depositStart}
          onChange={(event) => setDepositStart(event.target.value)}
        />
      </label>
      <label>
        Withdraw start row
        <input
          inputMode="numeric"
          value={withdrawStart}
          onChange={(event) => setWithdrawStart(event.target.value)}
        />
      </label>
      <button type="submit" disabled={rowsBusy}>{rowsBusy ? "Saving…" : "Save rows"}</button>
    </form>
    <div className="page-controls">
      <label>
        Brand
        <select value={brand} onChange={(event) => setBrand(event.target.value)}>
          <option value="All">{group === "All" ? "All brands" : "All brands in this group"}</option>
          {visibleBrands.map((item) => (
            <option key={item.id}>{item.name}</option>
          ))}
        </select>
      </label>
      <DateField value={date} onChange={setDate} />
      <button type="button" className={live ? "live on" : "live off"} aria-pressed={live} onClick={() => setLive((value) => !value)}>
        <span className="live-copy">
          <strong>{live ? "Live on" : "Live off"}</strong>
          <small>{live ? "Updates every second" : "Updates are paused"}</small>
        </span>
      </button>
      <button type="button" className="primary" onClick={refreshNow} disabled={refreshing}>
        {refreshing ? "Refreshing…" : "Refresh now"}
      </button>
      <p className="status control-status">
        <strong>{viewStatus.title}</strong>
        <span>{viewStatus.detail}</span>
      </p>
      {error && <p className="form-error">{error}</p>}
    </div>
    </section>
    <BankLedger date={date} group={group} brand={brand} revision={data?.revision || ""} />
    <div className="workspace">
      <aside className="side">
        <BankAccounts date={date} brands={visibleBrands} revision={data?.revision || ""} />
      </aside>

      <section className="main" ref={tableRef}>
        <div className="toolbar">
          <h2>{focusTitle ? focusTitle : "Transactions"}</h2>
          <div className="filters">
            <label>
              Sort by
              <select value={sortBy} onChange={(event) => setSortBy(event.target.value)}>
                {SORTS.map((option) => (
                  <option key={option}>{option}</option>
                ))}
              </select>
            </label>
            <label>
              Status
              <select
                value={status}
                onChange={(event) => {
                  setFocus("");
                  setStatus(event.target.value);
                }}
              >
                <option>All statuses</option>
                <option>PENDING</option>
                <option>PROCESSING</option>
                <option>COMPLETED</option>
                <option>REJECTED</option>
                <option>OTHER</option>
              </select>
            </label>
            <label>
              Type
              <select
                value={type}
                onChange={(event) => {
                  setFocus("");
                  setType(event.target.value);
                }}
              >
                <option>All types</option>
                <option>DEPOSIT</option>
                <option>WITHDRAW</option>
                <option>BONUS</option>
                <option>FORFEITED</option>
              </select>
            </label>
          </div>
        </div>

        <div className="table-wrap txn-window" ref={tableScroll}>
          <table>
            <thead>
              <tr>
                {COLUMNS.map(([key, label]) => (
                  <th key={key}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td className="empty" colSpan={COLUMNS.length}>
                    {focusTitle ? `No ${focusTitle.toLowerCase()} for this date.` : "No transactions for this date yet."}
                  </td>
                </tr>
              )}
              <RowSpacer height={windowRange.start * ROW_HEIGHT} />
              {visibleRows.map((row) => (
                <TransactionRow key={`${row.brand}-${row.id}`} row={row} onOpen={openRow} />
              ))}
              <RowSpacer height={(rows.length - windowRange.end) * ROW_HEIGHT} />
            </tbody>
          </table>
        </div>

        <div className="stats">
          <div className="stats-head">
            <div>
              <h3>Statistics</h3>
              <p>
                {scopeLabel(group, brand)} · {date} · {Number(bucket(stats, "row_count").count).toLocaleString()} transactions
              </p>
            </div>
            <button
              type="button"
              className={`stats-net${focus === "net_completed" ? " selected" : ""}${pulse.net_completed ? " is-live" : ""}`}
              aria-pressed={focus === "net_completed"}
              onClick={() => selectWidget("net_completed", "COMPLETED", "All types")}
            >
              <span>Net completed</span>
              <strong className={amountTone(bucket(stats, "net_completed").amount)}>
                {money(bucket(stats, "net_completed").amount)}
              </strong>
              <span>{Number(bucket(stats, "net_completed").count).toLocaleString()} deposits and withdrawals</span>
              <span className="net-split" aria-hidden="true">
                <span className="net-in" style={{ width: `${netParts.inPct}%` }} />
                <span className="net-out" style={{ width: `${netParts.outPct}%` }} />
              </span>
              <span className="net-legend">
                <span className="up">In {money(completedIn.amount)}</span>
                <span className="down">Out {money(completedOut.amount)}</span>
              </span>
            </button>
          </div>
          <p className="stats-hint">
            {focusTitle ? (
              <>
                Showing {focusTitle.toLowerCase()}.{" "}
                <button type="button" className="text-button" onClick={clearFocus}>
                  Show all
                </button>
              </>
            ) : (
              "Click a card to list those transactions."
            )}
          </p>
          <div
            className={`widgets${focus ? " filtering" : ""}`}
            role="group"
            aria-label="Statistic cards"
            onKeyDown={(event) => {
              moveWidgetFocus(event);
            }}
          >
            {widgets.map(([key, title, tone, nextStatus, nextType]) => {
              const item = bucket(stats, key);
              const selected = focus === key;
              const share = shareOf(item.count, dayCount);
              return (
                <button
                  key={key}
                  type="button"
                  className={`widget ${tone}${selected ? " selected" : ""}${pulse[key] ? " is-live" : ""}`}
                  data-stat={key}
                  aria-pressed={selected}
                  onClick={() => selectWidget(key, nextStatus, nextType)}
                >
                  <span className="widget-label">{title}</span>
                  <strong className={`widget-amount ${amountTone(item.amount)}`}>{money(item.amount)}</strong>
                  <span className="widget-count">{Number(item.count).toLocaleString()} transactions</span>
                  <span
                    className="widget-meter"
                    role="meter"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.round(share)}
                    aria-label={`${title} share of the day's transactions`}
                  >
                    <span style={{ width: `${share}%` }} />
                  </span>
                  <span className="widget-share">{selected ? "Showing · " : ""}{shareLabel(item.count, dayCount)}</span>
                </button>
              );
            })}
          </div>
          {previewKey && (
            <div className="stats-preview">
              <div className="stats-preview-head">
                <strong>{widgetTitle(previewKey, widgets)}</strong>
                <span>
                  {Number(bucket(stats, previewKey).count).toLocaleString()} transactions
                  {" · "}
                  {money(bucket(stats, previewKey).amount)}
                </span>
              </div>
              {previewRows.length === 0 ? (
                <p className="stats-preview-empty">No {widgetTitle(previewKey, widgets).toLowerCase()} for this date.</p>
              ) : (
                <ul>
                  {previewRows.map((row) => (
                    <li key={`${row.brand}-${row.id}`}>
                      <button type="button" onClick={() => openTransaction(row, setOpened)}>
                        <span>{row.time}</span>
                        <span>{row.username || row.name || "Unknown"}</span>
                        <span className={amountTone(row.amount)}>{money(row.amount)}</span>
                        <span>{row.type}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {Number(bucket(stats, previewKey).count) > previewRows.length && (
                <button
                  type="button"
                  className="text-button stats-preview-more"
                  onClick={() => {
                    if (focus === previewKey) {
                      tableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
                      return;
                    }
                    const match = widgets.find((item) => item[0] === previewKey);
                    if (previewKey === "net_completed") selectWidget("net_completed", "COMPLETED", "All types");
                    else if (match) selectWidget(match[0], match[3], match[4]);
                  }}
                >
                  List all {Number(bucket(stats, previewKey).count).toLocaleString()} in the table
                </button>
              )}
            </div>
          )}
          {brandSummary.length > 1 && (
            <div className="brand-chips">
              {brandSummary.map((item) => (
                <button
                  key={item.name}
                  type="button"
                  className={`brand-chip${brand === item.name ? " selected" : ""}`}
                  aria-pressed={brand === item.name}
                  onClick={() => setBrand(brand === item.name ? "All" : item.name)}
                >
                  <strong>{item.name}</strong>
                  <span>{Number(item.rows).toLocaleString()} rows</span>
                  <span className={item.pending ? "chip-pending" : ""}>{Number(item.pending).toLocaleString()} pending</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
    {opened && <TransactionDialog request={opened} onClose={() => setOpened(null)} />}
    </>
  );
}

function RowSpacer({ height }) {
  if (height <= 0) return null;
  return (
    <tr className="txn-spacer" aria-hidden="true">
      <td colSpan={COLUMNS.length}>
        <div style={{ height }} />
      </td>
    </tr>
  );
}

const TransactionRow = memo(function TransactionRow({ row, onOpen }) {
  return (
    <tr
      className={`${rowClass(row)} txn-row`.trim()}
      tabIndex={0}
      title="Show this transaction"
      onClick={() => onOpen(row)}
      onKeyDown={(event) => {
        if (event.key === "Enter") onOpen(row);
      }}
    >
      {COLUMNS.map(([key]) => (
        <td
          key={key}
          className={
            key === "bank_name" && row[key]
              ? "bank-name"
              : key === "bank_account_name" && row[key]
                ? "bank-account"
                : undefined
          }
        >
          {row[key]}
        </td>
      ))}
    </tr>
  );
});

function useVisibleRows(ref, count, rowHeight) {
  const [range, setRange] = useState({ start: 0, end: 60 });
  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    let frame = 0;
    const update = () => {
      frame = 0;
      const overscan = 16;
      const start = Math.max(0, Math.floor(node.scrollTop / rowHeight) - overscan);
      const end = Math.min(count, Math.ceil((node.scrollTop + node.clientHeight) / rowHeight) + overscan);
      setRange((prev) => (prev.start === start && prev.end === end ? prev : { start, end }));
    };
    const onScroll = () => {
      if (!frame) frame = window.requestAnimationFrame(update);
    };
    update();
    node.addEventListener("scroll", onScroll, { passive: true });
    const observer = new ResizeObserver(onScroll);
    observer.observe(node);
    return () => {
      node.removeEventListener("scroll", onScroll);
      observer.disconnect();
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [ref, count, rowHeight]);
  return range;
}

function openTransaction(row, setOpened) {
  const id = String(row?.id || "").trim();
  const brandName = String(row?.brand || "").trim();
  if (!id || !brandName) return;
  setOpened({ brand: brandName, id, token: Date.now() });
}

let openModals = 0;
let releasePageScroll = null;

function popupCanScroll(event) {
  const deltaY = event.deltaY || 0;
  const deltaX = event.deltaX || 0;
  let node = event.target instanceof Element ? event.target : event.target?.parentElement;
  const modal = node?.closest?.(".modal");
  if (!modal) return false;
  while (node) {
    const style = window.getComputedStyle(node);
    const canY = /(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 1;
    const canX = /(auto|scroll)/.test(style.overflowX) && node.scrollWidth > node.clientWidth + 1;
    if (canY && deltaY) {
      const atTop = node.scrollTop <= 0;
      const atBottom = node.scrollTop + node.clientHeight >= node.scrollHeight - 1;
      if ((deltaY < 0 && !atTop) || (deltaY > 0 && !atBottom)) return true;
    }
    if (canX && deltaX && Math.abs(deltaX) > Math.abs(deltaY)) {
      const atLeft = node.scrollLeft <= 0;
      const atRight = node.scrollLeft + node.clientWidth >= node.scrollWidth - 1;
      if ((deltaX < 0 && !atLeft) || (deltaX > 0 && !atRight)) return true;
    }
    if (node === modal) break;
    node = node.parentElement;
  }
  return false;
}

export function lockPageScroll() {
  openModals += 1;
  const body = document.body;
  const root = document.documentElement;
  if (!body.classList.contains("modal-open")) {
    const scrollY = window.scrollY;
    body.dataset.modalOverflow = body.style.overflow;
    body.dataset.modalPadding = body.style.paddingRight;
    root.dataset.modalOverflow = root.style.overflow;
    root.dataset.modalScroll = String(scrollY);
    const scrollbar = window.innerWidth - root.clientWidth;
    body.style.overflow = "hidden";
    root.style.overflow = "hidden";
    if (scrollbar > 0) body.style.paddingRight = `${scrollbar}px`;
    body.classList.add("modal-open");
    window.scrollTo(0, scrollY);

    const keepPosition = () => {
      const y = Number(root.dataset.modalScroll || 0);
      if (window.scrollY !== y) window.scrollTo(0, y);
    };
    const stopPageWheel = (event) => {
      if (!popupCanScroll(event)) event.preventDefault();
    };
    const stopBackdropTouch = (event) => {
      const target = event.target instanceof Element ? event.target : null;
      if (!target?.closest(".modal")) event.preventDefault();
    };
    window.addEventListener("scroll", keepPosition);
    window.addEventListener("wheel", stopPageWheel, { passive: false });
    window.addEventListener("touchmove", stopBackdropTouch, { passive: false });
    releasePageScroll = () => {
      window.removeEventListener("scroll", keepPosition);
      window.removeEventListener("wheel", stopPageWheel);
      window.removeEventListener("touchmove", stopBackdropTouch);
      releasePageScroll = null;
    };
  }
  return () => {
    openModals = Math.max(0, openModals - 1);
    if (openModals > 0) return;
    const y = Number(root.dataset.modalScroll || window.scrollY);
    releasePageScroll?.();
    body.style.overflow = body.dataset.modalOverflow || "";
    body.style.paddingRight = body.dataset.modalPadding || "";
    root.style.overflow = root.dataset.modalOverflow || "";
    delete body.dataset.modalOverflow;
    delete body.dataset.modalPadding;
    delete root.dataset.modalOverflow;
    delete root.dataset.modalScroll;
    body.classList.remove("modal-open");
    window.scrollTo(0, y);
  };
}

function TransactionDialog({ request, onClose }) {
  const [state, setState] = useState({ status: "loading", body: null, error: "" });
  const requestId = useRef(0);

  useEffect(() => {
    return lockPageScroll();
  }, []);

  useEffect(() => {
    function onKey(event) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    const id = ++requestId.current;
    let stopped = false;
    setState({ status: "loading", body: null, error: "" });
    const params = new URLSearchParams({ brand: request.brand, id: request.id });
    api(`/api/transactions/detail/?${params.toString()}`)
      .then((body) => {
        if (stopped || id !== requestId.current) return;
        if (body?.id !== request.id || body?.brand !== request.brand) {
          setState({ status: "error", body: null, error: "The brand API returned a different transaction." });
          return;
        }
        setState({ status: "ready", body, error: "" });
      })
      .catch((err) => {
        if (!stopped && id === requestId.current) {
          setState({ status: "error", body: null, error: err.message });
        }
      });
    return () => {
      stopped = true;
    };
  }, [request]);

  const body = state.body;
  const title = body?.type ? `${body.type} ${body.id}` : request.id;

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="txn-title">
        <div className="modal-head">
          <div>
            <h2 id="txn-title">{title}</h2>
            <p>
              {request.brand}
              {body?.status ? ` · ${body.status}` : ""}
            </p>
          </div>
          <button type="button" className="modal-close" onClick={onClose}>
            Close
          </button>
        </div>
        {state.status === "loading" && <p className="bank-hint">Loading this transaction from the brand API…</p>}
        {state.status === "error" && <p className="form-error">{state.error}</p>}
        {state.status === "ready" &&
          (body.sections || []).map((section) => (
            <section key={section.title} className="detail-section">
              <h3>{section.title}</h3>
              <dl className="detail-grid">
                {(section.fields || []).map((field) => (
                  <div key={`${section.title}-${field.label}`} className="detail-row">
                    <dt>{field.label}</dt>
                    <dd>
                      {field.href ? (
                        <a href={field.href} target="_blank" rel="noreferrer">
                          {field.value}
                        </a>
                      ) : (
                        field.value
                      )}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
      </div>
    </div>
  );
}

const BANK_STATUS_FILTERS = [
  ["All", "All"],
  ["Deposit only", "Deposit Only"],
  ["Withdraw only", "Withdraw Only"],
  ["Both", "Both"],
];

const LEDGER_CARDS = [
  ["status", "Status", "text"],
  ["bank_name", "Bank name", "text"],
  ["account_name", "Bank account name", "text"],
  ["opening", "Opening balance", "money"],
  ["closing", "Closing balance", "money"],
  ["limit", "Limit", "limit"],
  ["deposit", "Deposit", "money"],
  ["withdraw", "Withdraw", "money"],
  ["transfer_in", "Transfer in", "money"],
  ["pending", "Pending", "money"],
  ["complete", "Complete", "money"],
  ["transfer_out", "Transfer out", "money"],
  ["cash_in", "Cash in", "money"],
  ["cash_out", "Cash out", "money"],
];

const BankLedger = memo(function BankLedger({ date, group, brand, revision }) {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [opened, setOpened] = useState(null);
  const request = useRef(0);
  const skipSave = useRef(false);
  const tableHead = useRef(null);
  const tableScroll = useRef(null);
  const totalScroll = useRef(null);
  const [columnWidths, setColumnWidths] = useState([]);
  const [statusFilter, setStatusFilter] = useState("All");
  const [bankQuery, setBankQuery] = useState("");
  const [activeOnly, setActiveOnly] = useState(false);
  const visibleRows = useMemo(() => {
    const query = bankQuery.trim().toLowerCase();
    return rows.filter((row) => {
      if (statusFilter !== "All" && row.status !== statusFilter) return false;
      if (!query) return true;
      const bank = String(row.bank_name || "").toLowerCase();
      const account = String(row.account_name || "").toLowerCase();
      return bank.includes(query) || account.includes(query);
    });
  }, [rows, statusFilter, bankQuery]);
  const orderedRows = useMemo(() => {
    const active = [];
    const inactive = [];
    for (const row of visibleRows) {
      if (bankIsActive(row)) active.push(row);
      else inactive.push(row);
    }
    return activeOnly ? active : [...active, ...inactive];
  }, [visibleRows, activeOnly]);
  const totals = useMemo(() => ledgerTotals(orderedRows), [orderedRows]);

  useLayoutEffect(() => {
    const head = tableHead.current;
    if (!head) return;
    const measure = () => {
      setColumnWidths([...head.children].map((cell) => cell.getBoundingClientRect().width));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(head);
    return () => observer.disconnect();
  }, [rows]);

  function syncTotalScroll() {
    if (tableScroll.current && totalScroll.current) {
      totalScroll.current.scrollLeft = tableScroll.current.scrollLeft;
    }
  }

  useEffect(() => {
    const id = ++request.current;
    let stopped = false;
    setLoading(true);
    const params = new URLSearchParams({ date, group, brand });
    api(`/api/bank-ledger/?${params.toString()}`)
      .then((next) => {
        if (stopped || id !== request.current) return;
        setRows(next?.rows || []);
        setError("");
      })
      .catch((err) => {
        if (!stopped && id === request.current) setError(err.message);
      })
      .finally(() => {
        if (!stopped && id === request.current) setLoading(false);
      });
    return () => {
      stopped = true;
    };
  }, [date, group, brand, revision]);

  function replaceRow(row) {
    setRows((current) =>
      current.map((item) =>
        item.bank_name === row.bank_name && item.account_name === row.account_name ? row : item,
      ),
    );
  }

  async function save(row, body) {
    const next = await api("/api/bank-ledger/", {
      method: "POST",
      body: { date, group, brand, bank_name: row.bank_name, account_name: row.account_name, ...body },
    });
    if (next?.row) replaceRow(next.row);
  }

  function startLimit(row) {
    setEditing({ bank_name: row.bank_name, account_name: row.account_name, value: row.limit ?? "" });
  }

  async function finishLimit(row, input) {
    if (skipSave.current) {
      skipSave.current = false;
      setEditing(null);
      return;
    }
    const value = input.value;
    setEditing(null);
    const current = row.limit ?? "";
    if (value.trim() === current) return;
    try {
      await save(row, { limit: value.trim() });
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <section className="ledger">
      <div className="ledger-intro">
        <div>
          <h2>Bank balances</h2>
          <p>
            {scopeLabel(group, brand)} · {formatDay(date)}. Opening balance is the previous day at 11:59 PM.
            Closing balance is that opening balance plus this day’s deposits, withdrawals, and bank transfers.
          </p>
        </div>
        <div className="ledger-tools">
          <div className={`ledger-view-switch ${activeOnly ? "is-active" : "is-all"}`} role="group" aria-label="Banks shown">
            <span className="ledger-view-switch-thumb" aria-hidden="true" />
            <button
              type="button"
              className={activeOnly ? "is-selected" : ""}
              aria-pressed={activeOnly}
              onClick={() => setActiveOnly(true)}
            >
              Active Banks
            </button>
            <button
              type="button"
              className={activeOnly ? "" : "is-selected"}
              aria-pressed={!activeOnly}
              onClick={() => setActiveOnly(false)}
            >
              All Banks
            </button>
          </div>
          <label className="ledger-filter ledger-search">
            Bank
            <input
              type="search"
              value={bankQuery}
              onChange={(event) => setBankQuery(event.target.value)}
              placeholder="Search bank or account"
            />
          </label>
          <label className="ledger-filter">
            Status
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              {BANK_STATUS_FILTERS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      {error && <p className="form-error">{error}</p>}
      <div className="ledger-wrap" ref={tableScroll} onScroll={syncTotalScroll}>
        <table className="ledger-table">
          <thead>
            <tr ref={tableHead}>
              <th className="ledger-activity-head">Bank Active/Inactive</th>
              <th>BANK NAME</th>
              <th>BANK ACCOUNT NAME</th>
              <th>OPENING BALANCE</th>
              <th>CLOSING BALANCE</th>
              <th>LIMIT</th>
              <th>DEPOSIT</th>
              <th>WITHDRAW</th>
              <th>TRANSFER IN</th>
              <th>PENDING</th>
              <th>COMPLETE</th>
              <th>TRANSFER OUT</th>
              <th>CASH IN</th>
              <th>CASH OUT</th>
            </tr>
          </thead>
          <tbody>
            {loading && rows.length === 0 && (
              <tr>
                <td className="ledger-empty" colSpan={14}>
                  Loading bank balances…
                </td>
              </tr>
            )}
            {!loading && rows.length === 0 && (
              <tr>
                <td className="ledger-empty" colSpan={14}>
                  No bank accounts for this date.
                </td>
              </tr>
            )}
            {!loading && rows.length > 0 && orderedRows.length === 0 && (
              <tr>
                <td className="ledger-empty" colSpan={14}>
                  {bankQuery.trim()
                    ? "No bank accounts match this search."
                    : activeOnly && statusFilter !== "All"
                      ? "No active banks for this status."
                      : activeOnly
                        ? "No active banks for this date."
                        : "No bank accounts for this status."}
                </td>
              </tr>
            )}
            {orderedRows.map((row) => {
              const editingLimit =
                editing && editing.bank_name === row.bank_name && editing.account_name === row.account_name;
              const active = bankIsActive(row);
              return (
                <tr
                  key={`${row.bank_name}\u0000${row.account_name}`}
                  className={`ledger-row ${active ? "is-bank-active" : "is-bank-inactive"}`}
                  onClick={() => setOpened({ bank_name: row.bank_name, account_name: row.account_name })}
                >
                  <td className={`ledger-activity ${active ? "is-active" : "is-inactive"}`}>{active ? "Active" : "Inactive"}</td>
                  <td className="ledger-bank">{row.bank_name}</td>
                  <td className="ledger-account">{row.account_name}</td>
                  <td className="ledger-open">{money(row.opening)}</td>
                  <td className="ledger-close">{money(row.closing)}</td>
                  <td className="ledger-limit" onClick={(event) => event.stopPropagation()}>
                    {editingLimit ? (
                      <input
                        aria-label={`Limit for ${row.account_name}`}
                        value={editing.value}
                        autoFocus
                        inputMode="decimal"
                        placeholder="N/A"
                        onChange={(event) => setEditing({ ...editing, value: event.target.value })}
                        onBlur={(event) => finishLimit(row, event.currentTarget)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") event.currentTarget.blur();
                          if (event.key === "Escape") {
                            skipSave.current = true;
                            event.currentTarget.blur();
                          }
                        }}
                      />
                    ) : (
                      <button type="button" onClick={() => startLimit(row)}>
                        {row.limit == null ? "N/A" : money(row.limit)}
                      </button>
                    )}
                  </td>
                  <td className="ledger-deposit">{money(row.deposit)}</td>
                  <td className="ledger-withdraw">{money(row.withdraw)}</td>
                  <td className="ledger-later">{money(row.transfer_in)}</td>
                  <td className="ledger-later">{money(row.pending)}</td>
                  <td className="ledger-later">{money(row.complete)}</td>
                  <td className="ledger-later">{money(row.transfer_out)}</td>
                  <td className="ledger-later">{money(row.cash_in)}</td>
                  <td className="ledger-later">{money(row.cash_out)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {orderedRows.length > 0 && (
        <div className="ledger-total-wrap" ref={totalScroll}>
          <table
            className="ledger-table ledger-total-table"
            style={{ width: columnWidths.reduce((sum, width) => sum + width, 0) || undefined }}
          >
            <colgroup>
              {columnWidths.map((width, index) => (
                <col key={index} style={{ width }} />
              ))}
            </colgroup>
            <tbody>
              <tr className="ledger-total">
                <td
                  className="ledger-total-label"
                  title={`${totals.activeCount.toLocaleString()} active, ${totals.inactiveCount.toLocaleString()} inactive`}
                >
                  Total
                </td>
                <td className="ledger-total-count" title={`${totals.bankCount.toLocaleString()} bank names`}>
                  {totals.bankCount.toLocaleString()}
                </td>
                <td className="ledger-total-count" title={`${totals.accountCount.toLocaleString()} bank accounts`}>
                  {totals.accountCount.toLocaleString()}
                </td>
                <td className="ledger-open">{money(totals.opening)}</td>
                <td className="ledger-close">{money(totals.closing)}</td>
                <td className="ledger-limit">{totals.limit == null ? "N/A" : money(totals.limit)}</td>
                <td className="ledger-deposit">{money(totals.deposit)}</td>
                <td className="ledger-withdraw">{money(totals.withdraw)}</td>
                <td className="ledger-later">{money(totals.transfer_in)}</td>
                <td className="ledger-later">{money(totals.pending)}</td>
                <td className="ledger-later">{money(totals.complete)}</td>
                <td className="ledger-later">{money(totals.transfer_out)}</td>
                <td className="ledger-later">{money(totals.cash_in)}</td>
                <td className="ledger-later">{money(totals.cash_out)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {opened && (
        <BankDayDialog
          key={`${opened.bank_name}\u0000${opened.account_name}`}
          account={opened}
          group={group}
          brand={brand}
          revision={revision}
          onClose={() => setOpened(null)}
        />
      )}
    </section>
  );
});

function BankDayDialog({ account, group, brand, revision, onClose }) {
  const [day, setDay] = useState(today);
  const [state, setState] = useState({ status: "loading", body: null, error: "" });
  const requestId = useRef(0);

  useEffect(() => {
    return lockPageScroll();
  }, []);

  useEffect(() => {
    function onKey(event) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    const id = ++requestId.current;
    let stopped = false;
    setState((current) => ({
      status: "loading",
      body: current.body?.date === day ? current.body : null,
      error: "",
    }));
    const params = new URLSearchParams({
      date: day,
      group,
      brand,
      bank_name: account.bank_name,
      account_name: account.account_name,
    });
    api(`/api/bank-ledger/day/?${params.toString()}`)
      .then((body) => {
        if (stopped || id !== requestId.current) return;
        if (body?.row?.bank_name !== account.bank_name || body?.row?.account_name !== account.account_name) {
          setState({ status: "error", body: null, error: "The bank account details did not match." });
          return;
        }
        setState({ status: "ready", body, error: "" });
      })
      .catch((err) => {
        if (!stopped && id === requestId.current) setState({ status: "error", body: null, error: err.message });
      });
    return () => {
      stopped = true;
    };
  }, [account, group, brand, day, revision]);

  const row = state.body?.row;
  const transactions = state.body?.transactions || [];

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal bank-day" role="dialog" aria-modal="true" aria-labelledby="bank-day-title">
        <div className="modal-head">
          <div>
            <h2 id="bank-day-title">
              {account.bank_name} · {account.account_name}
            </h2>
            <p>{scopeLabel(group, brand)} · {formatDay(day)}</p>
          </div>
          <div className="bank-day-tools">
            <DateField value={day} onChange={setDay} />
            <button type="button" className="modal-close" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
        <div className="bank-day-body">
          {state.status === "error" && <p className="form-error">{state.error}</p>}
          {state.status === "loading" && !row && <p className="bank-hint">Loading this bank…</p>}
          {row && (
            <div className="bank-cards">
              {LEDGER_CARDS.map(([key, label, kind]) => (
                <article key={key} className={`bank-card card-${key}`}>
                  <span>{label}</span>
                  <strong className={kind === "money" ? amountTone(row[key]) : ""}>{ledgerCardValue(row, key, kind)}</strong>
                </article>
              ))}
            </div>
          )}
          <section className="detail-section">
            <h3>
              Transactions
              {state.status === "ready" ? ` · ${transactions.length.toLocaleString()}` : ""}
            </h3>
            {state.status === "ready" && transactions.length === 0 && (
              <p className="bank-hint">No transactions for this bank account on this date.</p>
            )}
            {transactions.length > 0 && (
              <div className="table-wrap bank-day-table">
                <table>
                  <thead>
                    <tr>
                      {COLUMNS.map(([key, label]) => (
                        <th key={key}>{label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {transactions.map((item) => (
                      <tr key={`${item.brand}-${item.id}`} className={rowClass(item)}>
                        {COLUMNS.map(([key]) => (
                          <td key={key}>{item[key]}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function ledgerTotals(rows) {
  const keys = [
    "opening",
    "closing",
    "deposit",
    "withdraw",
    "transfer_in",
    "pending",
    "complete",
    "transfer_out",
    "cash_in",
    "cash_out",
  ];
  const totals = {};
  for (const key of keys) {
    totals[key] = fromCents(rows.reduce((sum, row) => sum + cents(row[key]), 0));
  }
  const limits = rows.filter((row) => row.limit != null);
  totals.limit = limits.length ? fromCents(limits.reduce((sum, row) => sum + cents(row.limit), 0)) : null;
  totals.bankCount = new Set(rows.map((row) => row.bank_name).filter(Boolean)).size;
  totals.accountCount = rows.filter((row) => row.account_name).length;
  totals.activeCount = rows.filter((row) => bankIsActive(row)).length;
  totals.inactiveCount = rows.length - totals.activeCount;
  return totals;
}

function cents(value) {
  const text = String(value ?? "0").replace(/,/g, "").trim();
  if (!text || text.toUpperCase() === "N/A") return 0;
  const negative = text.startsWith("-");
  const [whole, fraction = ""] = text.replace("-", "").split(".");
  const amount = Number(whole || "0") * 100 + Number(`${fraction}00`.slice(0, 2));
  return negative ? -amount : amount;
}

function fromCents(amount) {
  const negative = amount < 0;
  const absolute = Math.abs(amount);
  const text = `${Math.floor(absolute / 100)}.${String(absolute % 100).padStart(2, "0")}`;
  return negative ? `-${text}` : text;
}

function ledgerCardValue(row, key, kind) {
  if (kind === "limit") return row.limit == null ? "N/A" : money(row.limit);
  if (kind === "money") return money(row[key]);
  return row[key] || "";
}

function bankIsActive(row) {
  return row?.activity === "Active";
}

function scopeLabel(group, brand) {
  if (brand && brand !== "All") return brand;
  if (group && group !== "All") return group;
  return "All brands";
}

const BankAccounts = memo(function BankAccounts({ date, brands, revision }) {
  const [game, setGame] = useState("");
  const [bankName, setBankName] = useState("");
  const [accountName, setAccountName] = useState("");
  const [directory, setDirectory] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const request = useRef(0);
  const accountNameRef = useRef("");

  useEffect(() => {
    if (game && !brands.some((item) => item.name === game)) {
      setGame("");
      setBankName("");
      setAccountName("");
      setDirectory(null);
    }
  }, [brands, game]);
  accountNameRef.current = accountName;

  useEffect(() => {
    if (!game) {
      setDirectory(null);
      setError("");
      setLoading(false);
      return;
    }
    const id = ++request.current;
    let stopped = false;
    setLoading(true);
    const params = new URLSearchParams({ date, brand: game });
    if (bankName) params.set("bank_name", bankName);
    const selectedName = accountNameRef.current;
    api(`/api/bank-accounts/?${params.toString()}`)
      .then((next) => {
        if (stopped || id !== request.current) return;
        setDirectory(next);
        setError("");
        if (bankName && !(next.banks || []).includes(bankName)) {
          setBankName("");
          setAccountName("");
        } else if (selectedName && !(next.accounts || []).some((item) => item.name === selectedName)) {
          setAccountName("");
        }
      })
      .catch((err) => {
        if (!stopped && id === request.current) setError(err.message);
      })
      .finally(() => {
        if (!stopped && id === request.current) setLoading(false);
      });
    return () => {
      stopped = true;
    };
  }, [date, game, bankName, revision]);

  function chooseGame(value) {
    setGame(value);
    setBankName("");
    setAccountName("");
    setDirectory(null);
  }

  function chooseBank(value) {
    setBankName(value);
    setAccountName("");
  }

  const accounts = directory?.bank_name === bankName ? directory.accounts || [] : [];
  const selected = accounts.find((item) => item.name === accountName) || null;
  const banks = directory?.banks || [];

  return (
    <section className="bank-section">
      <h3>Bank accounts</h3>
      <p className="bank-hint">
        Choose a game, then a bank name. Account names are only the ones that game uses for that bank.
      </p>
      <label>
        Game
        <select value={game} onChange={(event) => chooseGame(event.target.value)}>
          <option value="">Select a game</option>
          {brands.map((item) => (
            <option key={item.id} value={item.name}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Bank name
        <select value={bankName} onChange={(event) => chooseBank(event.target.value)} disabled={!game}>
          <option value="">{game ? "Select a bank" : "Select a game first"}</option>
          {banks.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </label>
      {error && <p className="form-error">{error}</p>}
      {!game && <p className="bank-hint">Select a game to see the banks that apply to it.</p>}
      {game && !bankName && !loading && directory && banks.length === 0 && (
        <p className="bank-hint">No bank account names for this game on this date.</p>
      )}
      {game && !bankName && loading && banks.length === 0 && <p className="bank-hint">Loading banks…</p>}
      {bankName && loading && directory?.bank_name !== bankName && <p className="bank-hint">Loading account names…</p>}
      {bankName && directory?.bank_name === bankName && (
        <>
          <div className="bank-total">
            <span>
              Final balance · {game} · {bankName}
            </span>
            <strong className={amountTone(directory.balance)}>{money(directory.balance)}</strong>
            <p>
              {money(directory.deposits)} deposits · {money(directory.withdrawals)} withdrawals ·{" "}
              {Number(directory.count).toLocaleString()} completed
            </p>
            {selected && (
              <>
                <span>Selected account · {selected.name}</span>
                <strong className={amountTone(selected.balance)}>{money(selected.balance)}</strong>
                <p>
                  {money(selected.deposits)} deposits · {money(selected.withdrawals)} withdrawals ·{" "}
                  {Number(selected.count).toLocaleString()} completed
                </p>
              </>
            )}
          </div>
          {directory.unassigned?.count > 0 && (
            <p className="bank-hint">
              {Number(directory.unassigned.count).toLocaleString()} completed{" "}
              {directory.unassigned.count === 1 ? "transaction has" : "transactions have"} no account name (
              {money(directory.unassigned.balance)}). That amount is not included.
            </p>
          )}
          {accounts.length === 0 ? (
            <p className="bank-hint">No bank account names for this bank on this date.</p>
          ) : (
            <ul className="bank-list">
              {accounts.map((account) => (
                <li key={account.name}>
                  <button
                    type="button"
                    className={`bank-account${account.name === accountName ? " selected" : ""}`}
                    aria-pressed={account.name === accountName}
                    onClick={() => setAccountName(account.name === accountName ? "" : account.name)}
                  >
                    <span className="bank-account-name">{account.name}</span>
                    <span className={`bank-account-balance ${amountTone(account.balance)}`}>{money(account.balance)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
});

function stamp(value) {
  const match = String(value || "")
    .trim()
    .match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!match) return 0;
  const [, year, month, day, hour, minute] = match;
  return Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute));
}

export function DateField({ value, onChange, label = "Date" }) {
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(() => value.slice(0, 7));
  const root = useRef(null);

  useEffect(() => {
    function onPointer(event) {
      if (root.current && !root.current.contains(event.target)) setOpen(false);
    }
    function onKey(event) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  function toggle() {
    setCursor(value.slice(0, 7));
    setOpen((current) => !current);
  }

  function pick(day) {
    onChange(day);
    setOpen(false);
  }

  return (
    <div className="date-field" ref={root}>
      <span className="date-label">{label}</span>
      <button type="button" className="date-button" onClick={toggle} aria-expanded={open}>
        {formatDay(value)}
      </button>
      {open && <Calendar month={cursor} selected={value} onMonth={setCursor} onPick={pick} />}
    </div>
  );
}

function Calendar({ month, selected, onMonth, onPick }) {
  const [year, monthIndex] = month.split("-").map(Number);
  const first = new Date(Date.UTC(year, monthIndex - 1, 1));
  const startOffset = (first.getUTCDay() + 6) % 7;
  const daysInMonth = new Date(Date.UTC(year, monthIndex, 0)).getUTCDate();
  const cells = [];
  for (let index = 0; index < startOffset; index += 1) cells.push(null);
  for (let day = 1; day <= daysInMonth; day += 1) cells.push(day);
  const sydneyToday = today();

  function shift(amount) {
    const next = new Date(Date.UTC(year, monthIndex - 1 + amount, 1));
    const text = `${next.getUTCFullYear()}-${String(next.getUTCMonth() + 1).padStart(2, "0")}`;
    onMonth(text);
  }

  return (
    <div className="calendar" key={month}>
      <div className="calendar-head">
        <button type="button" onClick={() => shift(-1)} aria-label="Previous month">
          ‹
        </button>
        <strong>{first.toLocaleDateString("en-AU", { month: "long", year: "numeric", timeZone: "UTC" })}</strong>
        <button type="button" onClick={() => shift(1)} aria-label="Next month">
          ›
        </button>
      </div>
      <div className="calendar-week">
        {["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((label) => (
          <span key={label}>{label}</span>
        ))}
      </div>
      <div className="calendar-grid">
        {cells.map((day, index) => {
          if (!day) return <span key={`empty-${index}`} />;
          const iso = `${year}-${String(monthIndex).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
          const className = ["calendar-day", iso === selected ? "selected" : "", iso === sydneyToday ? "today" : ""]
            .filter(Boolean)
            .join(" ");
          return (
            <button key={iso} type="button" className={className} onClick={() => onPick(iso)}>
              {day}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function formatDay(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return value;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return date.toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

function receivedStamp(row) {
  return stamp(row.processed) || stamp(row.time);
}

function sortRows(rows, sortBy) {
  const next = [...rows];
  next.sort((left, right) => {
    if (sortBy === "Sort by Received Time") {
      return receivedStamp(right) - receivedStamp(left) || stamp(right.time) - stamp(left.time) || compareText(right.id, left.id);
    }
    if (sortBy === "Sort by Alphabetical Order") {
      const byName = compareName(left.name, right.name);
      if (byName) return byName;
      return stamp(right.time) - stamp(left.time);
    }
    if (sortBy === "Sort by Amount") {
      const byAmount = amountValue(left) - amountValue(right);
      if (byAmount) return byAmount;
      return compareName(left.name, right.name);
    }
    return stamp(right.time) - stamp(left.time) || compareText(right.id, left.id);
  });
  return next;
}

function amountValue(row) {
  const value = Number(row.amount);
  return Number.isFinite(value) ? value : 0;
}

function compareName(left, right) {
  const a = String(left || "").trim();
  const b = String(right || "").trim();
  if (!a && b) return 1;
  if (a && !b) return -1;
  return a.localeCompare(b, undefined, { sensitivity: "base", numeric: true });
}

function compareText(left, right) {
  return String(left || "").localeCompare(String(right || ""), undefined, { sensitivity: "base", numeric: true });
}

function widgetTitle(key, widgets) {
  if (key === "net_completed") return "Net completed";
  return widgets.find((item) => item[0] === key)?.[1] || "";
}

function passesDropdown(row, status, type) {
  if (type !== "All types" && row.type !== type) return false;
  if (status === "All statuses") return true;
  if (status === "OTHER") return rowBucket(row) === "other";
  return row.status === status;
}

function matchesWidget(row, key) {
  if (key === "net_completed") {
    const bucketName = rowBucket(row);
    return bucketName === "completed_deposit" || bucketName === "completed_withdraw";
  }
  return rowBucket(row) === key;
}

function rowBucket(row) {
  const status = row.status;
  const kind = row.type;
  if (status === "PENDING" && kind === "DEPOSIT") return "pending_deposit";
  if (status === "PENDING" && kind === "WITHDRAW") return "pending_withdraw";
  if (status === "PROCESSING") return "processing";
  if (status === "REJECTED") return "rejected";
  if (status === "COMPLETED" && kind === "DEPOSIT") return "completed_deposit";
  if (status === "COMPLETED" && kind === "WITHDRAW") return "completed_withdraw";
  if (kind === "BONUS") return "bonus";
  if (kind === "FORFEITED") return "forfeited";
  return "other";
}

function bucket(stats, key) {
  return stats[key] || EMPTY_BUCKET;
}

function money(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "0.00";
  return amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function amountTone(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount === 0) return "flat";
  return amount > 0 ? "up" : "down";
}

function shareOf(count, total) {
  const value = Number(count) || 0;
  const all = Number(total) || 0;
  if (!all || value <= 0) return 0;
  return Math.min(100, (value / all) * 100);
}

function shareLabel(count, total) {
  const pct = shareOf(count, total);
  const text = pct > 0 && pct < 10 ? pct.toFixed(1) : String(Math.round(pct));
  return `${text}% of the day`;
}

function netSplit(depositAmount, withdrawAmount) {
  const incoming = Math.abs(Number(depositAmount) || 0);
  const outgoing = Math.abs(Number(withdrawAmount) || 0);
  const total = incoming + outgoing;
  if (!total) return { inPct: 0, outPct: 0 };
  return {
    inPct: (incoming / total) * 100,
    outPct: (outgoing / total) * 100,
  };
}

function moveWidgetFocus(event) {
  const key = event.key;
  if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(key)) return;
  const buttons = [...event.currentTarget.querySelectorAll(":scope > .widget")];
  const index = buttons.indexOf(document.activeElement);
  if (index < 0) return;
  const columns = getComputedStyle(event.currentTarget).gridTemplateColumns.split(" ").filter(Boolean).length || 1;
  let next = index;
  if (key === "ArrowRight") next = index + 1;
  if (key === "ArrowLeft") next = index - 1;
  if (key === "ArrowDown") next = index + columns;
  if (key === "ArrowUp") next = index - columns;
  if (key === "Home") next = 0;
  if (key === "End") next = buttons.length - 1;
  if (next === index || next < 0 || next >= buttons.length) return "";
  event.preventDefault();
  buttons[next].focus();
  return buttons[next].dataset.stat || "";
}

function useStatPulse(stats) {
  const previous = useRef(null);
  const [pulse, setPulse] = useState({});
  useEffect(() => {
    const before = previous.current;
    previous.current = stats;
    if (!before || before === EMPTY_STATS) return undefined;
    const keys = [...WIDGETS.map(([key]) => key), "other", "net_completed"];
    const changed = {};
    for (const key of keys) {
      const left = before[key];
      const right = stats?.[key];
      if (!left || !right) continue;
      if (left.amount !== right.amount || left.count !== right.count) changed[key] = true;
    }
    if (!Object.keys(changed).length) return undefined;
    setPulse(changed);
    const timer = window.setTimeout(() => setPulse({}), 900);
    return () => window.clearTimeout(timer);
  }, [stats]);
  return pulse;
}

function friendlyStatus(live, refreshing, data) {
  if (refreshing) return { title: "Refreshing", detail: "Reading the brand APIs" };
  const line = data?.status_line || "Waiting for the first API response.";
  const time = line.match(/\d{2}:\d{2}:\d{2}/)?.[0] || "";
  const rows = line.match(/([\d,]+)\s+(?:API|saved) rows/);
  const count = rows ? Number(rows[1].replace(/,/g, "")).toLocaleString() : "";
  if (line.includes("refused") || (line && !time && !count)) {
    return { title: live ? "Live" : "Paused", detail: line };
  }
  return {
    title: time ? (live ? `Updated ${time}` : `Paused · ${time}`) : (live ? "Waiting for an update" : "Paused"),
    detail: count ? `${count} transactions in this view` : line,
  };
}

function rowClass(row) {
  if (row.status === "PENDING") return "pending";
  if (row.status === "REJECTED") return "rejected";
  if (row.type === "DEPOSIT") return "deposit";
  if (row.type === "WITHDRAW") return "withdraw";
  if (row.type === "BONUS") return "bonus";
  if (row.type === "FORFEITED") return "forfeited";
  return "";
}
