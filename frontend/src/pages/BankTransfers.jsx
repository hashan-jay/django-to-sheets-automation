import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../api";
import { DateField, formatDay, lockPageScroll, today } from "./Dashboard";

function formatMoney(value) {
  const cents = amountCents(value);
  const negative = cents < 0;
  const abs = Math.abs(cents);
  const text = `${Math.floor(abs / 100).toLocaleString()}.${String(abs % 100).padStart(2, "0")}`;
  return negative ? `-${text}` : text;
}

function amountCents(value) {
  const text = String(value ?? "0").replace(/,/g, "").trim();
  const negative = text.startsWith("-");
  const [whole, fraction = ""] = text.replace("-", "").split(".");
  const amount = Number(whole || "0") * 100 + Number(`${fraction}00`.slice(0, 2));
  return negative ? -amount : amount;
}

function accountKey(account) {
  return `${account.bank_name}\n${account.account_name}`;
}

function accountFromKey(key) {
  const [bank_name, account_name] = String(key || "").split("\n");
  return { bank_name: bank_name || "", account_name: account_name || "" };
}

function accountLabel(account) {
  return `${account.bank_name} · ${account.account_name}`;
}

function highlightMatch(text, query) {
  const needle = query.trim();
  if (!needle) return text;
  const lower = text.toLowerCase();
  const target = needle.toLowerCase();
  const parts = [];
  let cursor = 0;
  let index = lower.indexOf(target);
  while (index !== -1) {
    if (index > cursor) parts.push(text.slice(cursor, index));
    parts.push(<mark key={`${index}-${cursor}`}>{text.slice(index, index + needle.length)}</mark>);
    cursor = index + needle.length;
    index = lower.indexOf(target, cursor);
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return parts;
}

function AccountPicker({ label, placeholder, accounts, value, blockedKey, onChange }) {
  const [open, setOpen] = useState(false);
  const [menuBox, setMenuBox] = useState(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const rootRef = useRef(null);
  const menuRef = useRef(null);
  const inputRef = useRef(null);
  const listId = useId();
  const labelId = `${listId}-label`;

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return accounts;
    return accounts.filter((account) => accountLabel(account).toLowerCase().includes(needle));
  }, [accounts, query]);

  useEffect(() => {
    if (!open) return undefined;
    inputRef.current?.focus();
    function onPointer(event) {
      if (rootRef.current?.contains(event.target) || menuRef.current?.contains(event.target)) return;
      setOpen(false);
      setQuery("");
    }
    function place(event) {
      if (menuRef.current?.contains(event.target)) return;
      placeMenu();
    }
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    document.addEventListener("mousedown", onPointer);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      document.removeEventListener("mousedown", onPointer);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const selectedIndex = matches.findIndex((account) => accountKey(account) === value);
    if (!query.trim() && selectedIndex >= 0) {
      setActive(selectedIndex);
      return;
    }
    const selectable = matches.findIndex((account) => accountKey(account) !== blockedKey);
    setActive(selectable < 0 ? 0 : selectable);
  }, [open, query, matches, value, blockedKey]);

  useEffect(() => {
    if (!open) return;
    const item = menuRef.current?.querySelector(".account-picker-option.is-active");
    const list = item?.closest("ul");
    if (!item || !list) return;
    const itemRect = item.getBoundingClientRect();
    const listRect = list.getBoundingClientRect();
    if (itemRect.top < listRect.top) list.scrollTop -= listRect.top - itemRect.top;
    else if (itemRect.bottom > listRect.bottom) list.scrollTop += itemRect.bottom - listRect.bottom;
  }, [open, active, matches]);

  function closeMenu() {
    setOpen(false);
    setQuery("");
  }

  function placeMenu() {
    const button = rootRef.current?.querySelector(".account-picker-button");
    if (!button) return;
    const rect = button.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    const spaceAbove = rect.top;
    const dropUp = spaceBelow < 280 && spaceAbove > spaceBelow;
    const available = Math.max(160, (dropUp ? spaceAbove : spaceBelow) - 12);
    setMenuBox({
      position: "fixed",
      left: rect.left,
      width: rect.width,
      right: "auto",
      top: dropUp ? "auto" : rect.bottom + 6,
      bottom: dropUp ? window.innerHeight - rect.top + 6 : "auto",
      maxHeight: Math.min(320, available),
      zIndex: 60,
    });
  }

  function openMenu() {
    placeMenu();
    setQuery("");
    setOpen(true);
  }

  function choose(account) {
    const key = accountKey(account);
    if (key === blockedKey) return;
    onChange(key);
    closeMenu();
  }

  function moveActive(step) {
    if (matches.length === 0) return;
    setActive((current) => {
      let next = current;
      for (let i = 0; i < matches.length; i += 1) {
        next = (next + step + matches.length) % matches.length;
        if (accountKey(matches[next]) !== blockedKey) return next;
      }
      return current;
    });
  }

  function onSearchKey(event) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveActive(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      moveActive(-1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const account = matches[active];
      if (account) choose(account);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closeMenu();
    }
  }

  const selected = accounts.find((account) => accountKey(account) === value);

  return (
    <div
      className={`account-picker${open ? " is-open" : ""}`}
      ref={rootRef}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.preventDefault();
          event.stopPropagation();
          closeMenu();
        }
      }}
    >
      <span id={labelId}>{label}</span>
      <button
        type="button"
        className="account-picker-button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-labelledby={labelId}
        onClick={() => {
          if (open) closeMenu();
          else openMenu();
        }}
      >
        <span className={selected ? "account-picker-value" : "account-picker-placeholder"}>
          {selected ? accountLabel(selected) : placeholder}
        </span>
        <svg className="account-picker-caret" viewBox="0 0 20 20" width="16" height="16" aria-hidden="true">
          <path d="M5.5 7.5 10 12l4.5-4.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && menuBox && createPortal(
        <div className="account-picker-menu" ref={menuRef} style={menuBox}>
          <div className="account-picker-search">
            <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true">
              <circle cx="8.5" cy="8.5" r="5.25" fill="none" stroke="currentColor" strokeWidth="1.8" />
              <path d="M12.5 12.5 16.5 16.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
            <input
              ref={inputRef}
              type="text"
              role="searchbox"
              value={query}
              placeholder="Search bank or account"
              autoComplete="off"
              spellCheck={false}
              aria-label={`Search ${label.toLowerCase()}`}
              aria-controls={listId}
              aria-autocomplete="list"
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={onSearchKey}
            />
          </div>
          <ul id={listId} role="listbox" aria-labelledby={labelId}>
            {matches.length === 0 && (
              <li className="account-picker-empty">
                {accounts.length === 0 ? "No accounts available" : "No matching accounts"}
              </li>
            )}
            {matches.map((account, index) => {
              const key = accountKey(account);
              const blocked = key === blockedKey;
              const isSelected = key === value;
              return (
                <li key={key} role="presentation">
                  <button
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    disabled={blocked}
                    className={`account-picker-option${isSelected ? " is-selected" : ""}${index === active ? " is-active" : ""}`}
                    onMouseEnter={() => setActive(index)}
                    onClick={() => choose(account)}
                  >
                    {highlightMatch(accountLabel(account), query)}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>,
        document.body,
      )}
    </div>
  );
}

const TOAST_MS = 6000;

function TransferToast({ notice, onDone }) {
  const [leaving, setLeaving] = useState(false);
  const timer = useRef(null);
  const deadline = useRef(0);
  const remaining = useRef(TOAST_MS);
  const closing = useRef(false);

  function finish() {
    window.clearTimeout(timer.current);
    onDone();
  }

  function dismiss() {
    if (closing.current) return;
    closing.current = true;
    window.clearTimeout(timer.current);
    setLeaving(true);
    timer.current = window.setTimeout(finish, 180);
  }

  function arm(ms) {
    window.clearTimeout(timer.current);
    const delay = Math.max(0, ms);
    remaining.current = delay;
    deadline.current = Date.now() + delay;
    timer.current = window.setTimeout(dismiss, delay);
  }

  useEffect(() => {
    arm(TOAST_MS);
    return () => window.clearTimeout(timer.current);
  }, []);

  function pause() {
    if (closing.current) return;
    window.clearTimeout(timer.current);
    remaining.current = Math.max(0, deadline.current - Date.now());
  }

  function resume() {
    if (closing.current) return;
    arm(remaining.current);
  }

  return (
    <aside
      className={`transfer-toast${leaving ? " is-leaving" : ""}`}
      role="status"
      onMouseEnter={pause}
      onMouseLeave={resume}
      onFocus={pause}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) resume();
      }}
    >
      <div className="transfer-toast-body">
        <span className="transfer-toast-mark" aria-hidden="true">
          <svg viewBox="0 0 20 20" width="16" height="16">
            <path d="M5 10.5 8.2 13.5 15 6.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
        <div className="transfer-toast-copy">
          <strong>Transfer saved</strong>
          <p>
            {notice.from} sent {notice.amount} to {notice.to} on {notice.date}.
          </p>
        </div>
        <button type="button" className="transfer-toast-close" aria-label="Dismiss notification" onClick={dismiss}>
          <svg viewBox="0 0 20 20" width="14" height="14" aria-hidden="true">
            <path d="M5.5 5.5 14.5 14.5M14.5 5.5 5.5 14.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
        </button>
      </div>
      <span className="transfer-toast-bar" />
    </aside>
  );
}

export default function BankTransfers() {
  const [date, setDate] = useState(today);
  const [rows, setRows] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(null);
  const [toastKey, setToastKey] = useState(0);
  const [freshId, setFreshId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let stopped = false;
    api("/api/bank-transfers/accounts/")
      .then((body) => {
        if (!stopped) setAccounts(body?.accounts || []);
      })
      .catch((err) => {
        if (!stopped) setError(err.message);
      });
    return () => {
      stopped = true;
    };
  }, []);

  useEffect(() => {
    let stopped = false;
    setLoading(true);
    const params = new URLSearchParams({ date });
    api(`/api/bank-transfers/?${params.toString()}`)
      .then((body) => {
        if (stopped) return;
        setRows(body?.rows || []);
        setError("");
      })
      .catch((err) => {
        if (!stopped) setError(err.message);
      })
      .finally(() => {
        if (!stopped) setLoading(false);
      });
    return () => {
      stopped = true;
    };
  }, [date, reloadToken]);

  const total = useMemo(() => {
    const cents = rows.reduce((sum, row) => sum + amountCents(row.amount), 0);
    const negative = cents < 0;
    const abs = Math.abs(cents);
    const text = `${Math.floor(abs / 100).toLocaleString()}.${String(abs % 100).padStart(2, "0")}`;
    return negative ? `-${text}` : text;
  }, [rows]);

  function saved(row) {
    setOpen(false);
    setNotice({
      from: `${row.from_bank_name} · ${row.from_account_name}`,
      to: `${row.to_bank_name} · ${row.to_account_name}`,
      amount: formatMoney(row.amount),
      date: formatDay(row.transfer_date),
    });
    setFreshId(row.id);
    setToastKey((key) => key + 1);
    if (row.transfer_date === date) {
      setRows((current) => [row, ...current.filter((item) => item.id !== row.id)]);
      setReloadToken((token) => token + 1);
    } else {
      setRows([row]);
      setDate(row.transfer_date);
    }
  }

  return (
    <div className="users-page transfers-page">
      <header className="users-head">
        <div>
          <h2>Bank transfers</h2>
          <p>
            Record cash moved by hand from one bank app to another. The transfer date is the day the money moved.
            Day created is the day this row was entered. Bank balances use the transfer date.
          </p>
        </div>
        <button type="button" className="primary" onClick={() => setOpen(true)}>
          Transfer money
        </button>
      </header>

      {error && <div className="form-error">{error}</div>}
      {notice && createPortal(
        <TransferToast
          key={toastKey}
          notice={notice}
          onDone={() => {
            setNotice(null);
            setFreshId(null);
          }}
        />,
        document.body,
      )}

      <section className="card transfers-panel">
        <div className="transfers-tools">
          <DateField value={date} onChange={setDate} label="Transfer date" />
          <p className="transfers-count">
            <strong>{rows.length.toLocaleString()}</strong>
            {rows.length === 1 ? " transfer" : " transfers"}
            <span> · {total}</span>
          </p>
        </div>
        <div className="table-wrap transfers-table">
          <table>
            <thead>
              <tr>
                <th>Transfer date</th>
                <th>From bank</th>
                <th>From account</th>
                <th>To bank</th>
                <th>To account</th>
                <th>Amount</th>
                <th>Remarks</th>
                <th>Day created</th>
                <th>Transfer time</th>
                <th>User</th>
              </tr>
            </thead>
            <tbody>
              {loading && rows.length === 0 && (
                <tr>
                  <td className="empty" colSpan={10}>Loading bank transfers…</td>
                </tr>
              )}
              {!loading && rows.length === 0 && (
                <tr>
                  <td className="empty" colSpan={10}>No bank transfers on {formatDay(date)}.</td>
                </tr>
              )}
              {rows.map((row) => (
                <tr key={row.id} className={row.id === freshId ? "is-fresh" : undefined}>
                  <td>{formatDay(row.transfer_date)}</td>
                  <td className="bank-name">{row.from_bank_name}</td>
                  <td className="bank-account">{row.from_account_name}</td>
                  <td className="bank-name">{row.to_bank_name}</td>
                  <td className="bank-account">{row.to_account_name}</td>
                  <td className="transfer-amount">{formatMoney(row.amount)}</td>
                  <td className="transfer-remarks">{row.remarks}</td>
                  <td>{formatDay(row.created_on)}</td>
                  <td className="transfer-time">{row.transfer_time}</td>
                  <td className="transfer-user">{row.username}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {open && (
        <TransferDialog
          accounts={accounts}
          initialDate={date}
          onClose={() => setOpen(false)}
          onSaved={saved}
        />
      )}
    </div>
  );
}

function TransferDialog({ accounts, initialDate, onClose, onSaved }) {
  const [date, setDate] = useState(initialDate || today);
  const [fromKey, setFromKey] = useState("");
  const [toKey, setToKey] = useState("");
  const [amount, setAmount] = useState("");
  const [remarks, setRemarks] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => lockPageScroll(), []);

  useEffect(() => {
    function onKey(event) {
      if (event.key !== "Escape") return;
      if (document.querySelector(".transfer-dialog .calendar")) return;
      if (document.querySelector(".account-picker-menu")) return;
      onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function submit(event) {
    event.preventDefault();
    const from = accountFromKey(fromKey);
    const to = accountFromKey(toKey);
    if (!from.bank_name || !to.bank_name) {
      setError("Choose the bank the money leaves and the bank it arrives in.");
      return;
    }
    if (fromKey === toKey) {
      setError("Choose two different bank accounts.");
      return;
    }
    const text = amount.trim();
    if (!/^\d+(\.\d{1,2})?$/.test(text) || Number(text) <= 0) {
      setError("Enter an amount greater than zero, with at most two decimal places.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const body = await api("/api/bank-transfers/", {
        method: "POST",
        body: {
          date,
          from_bank_name: from.bank_name,
          from_account_name: from.account_name,
          to_bank_name: to.bank_name,
          to_account_name: to.account_name,
          amount: text,
          remarks: remarks.trim(),
        },
      });
      onSaved(body.row);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <form className="modal transfer-dialog" role="dialog" aria-modal="true" aria-labelledby="transfer-title" onSubmit={submit}>
        <div className="modal-head">
          <div>
            <h2 id="transfer-title">Transfer money</h2>
            <p>The date below is the day the money moved between the bank apps.</p>
          </div>
          <button type="button" className="modal-close" onClick={onClose}>Close</button>
        </div>
        <DateField value={date} onChange={setDate} label="Transfer date" />
        <AccountPicker
          label="From bank"
          placeholder="Select the account the money leaves"
          accounts={accounts}
          value={fromKey}
          blockedKey={toKey}
          onChange={setFromKey}
        />
        <AccountPicker
          label="To bank"
          placeholder="Select the account the money arrives in"
          accounts={accounts}
          value={toKey}
          blockedKey={fromKey}
          onChange={setToKey}
        />
        <label>
          Amount
          <input
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            inputMode="decimal"
            placeholder="0.00"
            autoComplete="off"
          />
        </label>
        <label>
          Remarks
          <input
            value={remarks}
            onChange={(event) => setRemarks(event.target.value)}
            placeholder="Why this transfer was done"
            maxLength={500}
            autoComplete="off"
          />
        </label>
        {error && <div className="form-error">{error}</div>}
        <button type="submit" className="primary" disabled={busy}>
          {busy ? "Saving…" : "Save transfer"}
        </button>
      </form>
    </div>
  );
}
