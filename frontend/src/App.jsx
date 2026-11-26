import { useEffect, useState } from "react";
import { api, getToken, setToken } from "./api";
import BankTransfers from "./pages/BankTransfers";
import Customers from "./pages/Customers";
import Dashboard, { lockPageScroll } from "./pages/Dashboard";
import Login from "./pages/Login";
import Users from "./pages/Users";
import SheetAnalytics from "./pages/SheetAnalytics";
import SystemSettings from "./pages/SystemSettings";

export default function App() {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);
  const [page, setPage] = useState("dashboard");
  const [groups, setGroups] = useState(["KABOOM77"]);
  const [group, setGroup] = useState(() => localStorage.getItem("kaboom-group") || "KABOOM77");
  const [addStep, setAddStep] = useState("");
  const [groupName, setGroupName] = useState("");
  const [groupError, setGroupError] = useState("");
  const [creating, setCreating] = useState(false);
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

  useEffect(() => {
    if (!user) return;
    api("/api/groups/")
      .then((body) => {
        const names = body.groups || [];
        setGroups(names.length ? names : ["KABOOM77"]);
        if (names.length && !names.includes(group)) {
          setGroup("KABOOM77");
          localStorage.setItem("kaboom-group", "KABOOM77");
        }
      })
      .catch(() => {});
  }, [user, group]);

  function chooseGroup(code) {
    setGroup(code);
    localStorage.setItem("kaboom-group", code);
    setPage("dashboard");
  }

  async function createGroup() {
    const name = groupName.trim();
    if (!name) return;
    setCreating(true);
    setGroupError("");
    try {
      const saved = await api("/api/groups/", { method: "POST", body: { name } });
      setGroups((current) => [...current.filter((item) => item !== saved.code), saved.code]);
      chooseGroup(saved.code);
      setAddStep("");
      setGroupName("");
    } catch (err) {
      setGroupError(err.message);
    } finally {
      setCreating(false);
    }
  }

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
            <h1>{group}</h1>
            <p>Live deposits and withdrawals for {group}.</p>
          </button>
          <div className="group-switch" role="group" aria-label="Groups">
            {groups.map((code) => (
              <button
                key={code}
                type="button"
                className={code === group ? "is-selected" : ""}
                onClick={() => chooseGroup(code)}
              >
                {code}
              </button>
            ))}
            <button type="button" className="group-add" aria-label="Add group" onClick={() => { setGroupError(""); setAddStep("ask"); }}>+</button>
          </div>
        </div>
        <div className="top-actions">
          <button
            type="button"
            className={`ghost${page === "settings" ? " selected" : ""}`}
            aria-pressed={page === "settings"}
            onClick={() => setPage(page === "settings" ? "dashboard" : "settings")}
          >
            System Settings
          </button>
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
      ) : page === "settings" ? (
        <SystemSettings group={group} />
      ) : page === "analytics" ? (
        <SheetAnalytics group={group} />
      ) : page === "customers" ? (
        <Customers group={group} />
      ) : page === "transfers" ? (
        <BankTransfers />
      ) : (
        <Dashboard group={group} />
      )}
      {addStep === "ask" && (
        <LogoutConfirm
          busy={false}
          title="Are you sure to Create a New Group?"
          yesLabel="YES"
          noLabel="NO"
          onYes={() => setAddStep("name")}
          onNo={() => setAddStep("")}
        />
      )}
      {addStep === "name" && (
        <GroupNameDialog
          name={groupName}
          error={groupError}
          busy={creating}
          onChange={setGroupName}
          onCancel={() => { if (!creating) { setAddStep(""); setGroupName(""); } }}
          onCreate={createGroup}
        />
      )}
      {confirmLogout && (
        <LogoutConfirm busy={loggingOut} onYes={logout} onNo={() => setConfirmLogout(false)} />
      )}
    </div>
  );
}

function LogoutConfirm({ busy, title = "Are you sure to log out", yesLabel = "Yes", noLabel = "No", onYes, onNo }) {
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
        <h2 id="logout-title">{title}</h2>
        <div className="logout-actions">
          <button type="button" className="modal-close" onClick={onNo} disabled={busy}>
            {noLabel}
          </button>
          <button type="button" className="logout-yes" onClick={onYes} disabled={busy}>
            {yesLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function GroupNameDialog({ name, error, busy, onChange, onCancel, onCreate }) {
  useEffect(() => lockPageScroll(), []);
  return (
    <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onCancel(); }}>
      <div className="modal logout-dialog" role="dialog" aria-modal="true">
        <h2>Enter the Group Name</h2>
        <label className="group-name-field">
          Group name
          <input value={name} onChange={(event) => onChange(event.target.value)} autoFocus />
        </label>
        {error && <p className="sheet-url-note is-error">{error}</p>}
        <div className="logout-actions">
          <button type="button" className="modal-close" onClick={onCancel} disabled={busy}>Cancel</button>
          <button type="button" className="logout-yes" onClick={onCreate} disabled={busy || !name.trim()}>
            {busy ? "Creating…" : "Create Group"}
          </button>
        </div>
      </div>
    </div>
  );
}
