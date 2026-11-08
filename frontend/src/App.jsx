import { useEffect, useState } from "react";
import { api, getToken, setToken } from "./api";
import BankTransfers from "./pages/BankTransfers";
import Customers from "./pages/Customers";
import Dashboard, { lockPageScroll } from "./pages/Dashboard";
import Login from "./pages/Login";
import Users from "./pages/Users";

export default function App() {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);
  const [page, setPage] = useState("dashboard");
  const [confirmLogout, setConfirmLogout] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      setReady(true);
      return;
    }
    api("/api/auth/me/")
      .then(setUser)
      .catch(() => setToken(""))
      .finally(() => setReady(true));
  }, []);

  async function logout() {
    setLoggingOut(true);
    try {
      await api("/api/auth/logout/", { method: "POST" });
    } catch {
      /* the token is cleared either way */
    }
    setToken("");
    setUser(null);
    setPage("dashboard");
    setConfirmLogout(false);
    setLoggingOut(false);
  }

  if (!ready) {
    return <div className="boot">Loading…</div>;
  }
  if (!user) {
    return <Login onSuccess={setUser} />;
  }
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand-lockup">
          <button type="button" className="brand-home" onClick={() => setPage("dashboard")}>
            <h1>KABOOM77 Automation</h1>
            <p>Live deposits and withdrawals from the KABOOM77 brand API.</p>
          </button>
        </div>
        <div className="top-actions">
          <button
            type="button"
            className={`ghost${page === "customers" ? " selected" : ""}`}
            aria-pressed={page === "customers"}
            onClick={() => setPage(page === "customers" ? "dashboard" : "customers")}
          >
            Customers
          </button>
          <button
            type="button"
            className={`ghost${page === "transfers" ? " selected" : ""}`}
            aria-pressed={page === "transfers"}
            onClick={() => setPage(page === "transfers" ? "dashboard" : "transfers")}
          >
            Bank Transfers
          </button>
          {user.is_staff && (
            <button type="button" className={`ghost${page === "users" ? " selected" : ""}`} onClick={() => setPage(page === "users" ? "dashboard" : "users")}>
              {page === "users" ? "Transactions" : "Users"}
            </button>
          )}
          <span className="who">
            <span className="who-mark" aria-hidden="true">{user.username.slice(0, 1).toUpperCase()}</span>
            {user.username}
          </span>
          <button type="button" className="ghost logout" onClick={() => setConfirmLogout(true)}>
            Log out
          </button>
        </div>
      </header>
      {page === "users" && user.is_staff ? (
        <Users />
      ) : page === "customers" ? (
        <Customers />
      ) : page === "transfers" ? (
        <BankTransfers />
      ) : (
        <Dashboard />
      )}
      {confirmLogout && (
        <LogoutConfirm busy={loggingOut} onYes={logout} onNo={() => setConfirmLogout(false)} />
      )}
    </div>
  );
}

function LogoutConfirm({ busy, onYes, onNo }) {
  useEffect(() => lockPageScroll(), []);

  useEffect(() => {
    function onKey(event) {
      if (event.key === "Escape" && !busy) onNo();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [busy, onNo]);

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onNo();
      }}
    >
      <div className="modal logout-dialog" role="dialog" aria-modal="true" aria-labelledby="logout-title">
        <h2 id="logout-title">Are you sure to log out</h2>
        <div className="logout-actions">
          <button type="button" className="modal-close" onClick={onNo} disabled={busy}>
            No
          </button>
          <button type="button" className="logout-yes" onClick={onYes} disabled={busy}>
            Yes
          </button>
        </div>
      </div>
    </div>
  );
}
