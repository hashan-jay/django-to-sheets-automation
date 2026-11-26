import { useEffect, useState } from "react";
import { api } from "../api";
import { lockPageScroll } from "./Dashboard";

const EMPTY_BRAND = { name: "", domain: "", access_id: "", merchant_id: "", token: "" };

export default function SystemSettings({ group = "KABOOM77" }) {
  const [groups, setGroups] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [emails, setEmails] = useState({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [editing, setEditing] = useState(null);
  const [removing, setRemoving] = useState(null);

  useEffect(() => {
    let stopped = false;
    function load() {
      api(`/api/system-settings/?group=${encodeURIComponent(group)}`)
        .then((body) => {
          if (!stopped) setGroups(body.groups || []);
        })
        .catch((err) => {
          if (!stopped) setError(err.message);
        });
    }
    load();
    const timer = window.setInterval(load, 8000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [group]);

  useEffect(() => {
    setEmails((current) => {
      const next = { ...current };
      for (const item of groups) {
        if (next[item.code] === undefined) next[item.code] = item.google_email || "";
      }
      return next;
    });
    setDrafts((current) => {
      const next = { ...current };
      for (const item of groups) {
        if (!next[item.code]) next[item.code] = { ...EMPTY_BRAND };
      }
      return next;
    });
  }, [groups]);

  function applyGroups(next) {
    setGroups(next);
    const emailMap = {};
    const draftMap = {};
    for (const group of next) {
      emailMap[group.code] = group.google_email || "";
      draftMap[group.code] = { ...EMPTY_BRAND };
    }
    setEmails(emailMap);
    setDrafts(draftMap);
  }

  async function save(code, brand) {
    setBusy(code);
    setError("");
    setMessage("");
    try {
      const saved = await api("/api/system-settings/", {
        method: "POST",
        body: { group: code, google_email: emails[code] || "", brand },
      });
      setGroups((current) => current.map((group) => (group.code === code ? saved : group)));
      setDrafts((current) => ({ ...current, [code]: { ...EMPTY_BRAND } }));
      setMessage(`${code} settings were saved.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function saveEdit() {
    if (!editing) return;
    setBusy(editing.group);
    setError("");
    setMessage("");
    try {
      const saved = await api("/api/system-settings/", {
        method: "POST",
        body: {
          group: editing.group,
          google_email: emails[editing.group] || "",
          brand: { ...editing, previous_name: editing.previous_name },
        },
      });
      setGroups((current) => current.map((group) => (group.code === editing.group ? saved : group)));
      setEditing(null);
      setMessage("API key was updated.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function confirmDelete() {
    if (!removing) return;
    setBusy(removing.group);
    setError("");
    setMessage("");
    try {
      const saved = await api("/api/system-settings/", {
        method: "DELETE",
        body: { group: removing.group, name: removing.name },
      });
      setGroups((current) => current.map((group) => (group.code === removing.group ? saved : group)));
      setRemoving(null);
      setMessage("API key was deleted.");
    } catch (err) {
      setError(err.message);
      setRemoving(null);
    } finally {
      setBusy("");
    }
  }

  return (
    <main className="settings-page">
      <header className="users-head">
        <div>
          <h2>System Settings</h2>
          <p>Google account and brand API keys for {group}.</p>
        </div>
      </header>
      {error && <p className="sheet-url-note is-error">{error}</p>}
      {message && <p className="sheet-url-note is-ok">{message}</p>}
      <div className="settings-groups">
        {groups.map((group) => (
          <GroupCard
            key={group.code}
            group={group}
            email={emails[group.code] || ""}
            draft={drafts[group.code] || EMPTY_BRAND}
            busy={busy === group.code}
            onEmail={(value) => setEmails((current) => ({ ...current, [group.code]: value }))}
            onDraft={(draft) => setDrafts((current) => ({ ...current, [group.code]: draft }))}
            onSave={save}
            onEdit={(brand) => setEditing({ ...brand, group: group.code, previous_name: brand.name })}
            onDelete={(brand) => setRemoving({ name: brand.name, group: group.code })}
          />
        ))}
      </div>
      {editing && (
        <KeyDialog
          title={`Edit ${editing.previous_name}`}
          busy={busy === editing.group}
          onCancel={() => { if (!busy) setEditing(null); }}
          onSave={saveEdit}
        >
          <label>
            Brand name
            <input value={editing.name} onChange={(event) => setEditing({ ...editing, name: event.target.value })} />
          </label>
          <label>
            API domain
            <input value={editing.domain} onChange={(event) => setEditing({ ...editing, domain: event.target.value })} />
          </label>
          <label>
            Access ID
            <input value={editing.access_id} onChange={(event) => setEditing({ ...editing, access_id: event.target.value })} />
          </label>
          <label>
            Merchant ID
            <input value={editing.merchant_id} onChange={(event) => setEditing({ ...editing, merchant_id: event.target.value })} />
          </label>
          <label>
            Token
            <input value={editing.token} onChange={(event) => setEditing({ ...editing, token: event.target.value })} />
          </label>
        </KeyDialog>
      )}
      {removing && (
        <ConfirmDelete
          busy={busy === removing.group}
          onYes={confirmDelete}
          onNo={() => { if (!busy) setRemoving(null); }}
        />
      )}
    </main>
  );
}

function GroupCard({ group, email, draft, busy, onEmail, onDraft, onSave, onEdit, onDelete }) {
  return (
    <section className="settings-group">
      <header>
        <h3>{group.code}</h3>
        <span>{group.live ? "Live group" : "Saved only, not writing yet"}</span>
      </header>
      <label>
        Google account email
        <input value={email} onChange={(event) => onEmail(event.target.value)} placeholder="service-account@project.iam.gserviceaccount.com" />
      </label>
      <div className="settings-split">
        <div>
          <h4>Add a brand</h4>
          <div className="settings-form">
            <label>
              Brand name
              <input value={draft.name} onChange={(event) => onDraft({ ...draft, name: event.target.value })} />
            </label>
            <label>
              API domain
              <input value={draft.domain} onChange={(event) => onDraft({ ...draft, domain: event.target.value })} placeholder="https://brand.example" />
            </label>
            <label>
              Access ID
              <input value={draft.access_id} onChange={(event) => onDraft({ ...draft, access_id: event.target.value })} />
            </label>
            <label>
              Merchant ID
              <input value={draft.merchant_id} onChange={(event) => onDraft({ ...draft, merchant_id: event.target.value })} />
            </label>
            <label>
              Token
              <input value={draft.token} onChange={(event) => onDraft({ ...draft, token: event.target.value })} />
            </label>
            <button type="button" className="primary" disabled={busy} onClick={() => onSave(group.code, draft)}>
              {busy ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
        <aside className="settings-saved" aria-label="Saved API keys">
          <h4>Saved API keys</h4>
          {group.brands.length === 0 ? (
            <p className="settings-empty">No brand API key is saved for this group yet.</p>
          ) : (
            group.brands.map((brand) => (
              <article key={brand.name}>
                <header>
                  <strong>{brand.name}</strong>
                  <span>{brand.active ? "Running" : "Saved"}</span>
                </header>
                {brand.error ? <p className="settings-api-error">{brand.error}</p> : null}
                <p><span>Brand name</span>{brand.name}</p>
                <p><span>API domain</span>{brand.domain || "—"}</p>
                <p><span>Access ID</span>{brand.access_id || "—"}</p>
                <p><span>Token</span>{brand.token || "—"}</p>
                <div className="settings-key-actions">
                  <button type="button" className="settings-edit" onClick={() => onEdit(brand)}>Edit</button>
                  <button type="button" className="settings-delete" onClick={() => onDelete(brand)}>Delete</button>
                </div>
              </article>
            ))
          )}
        </aside>
      </div>
    </section>
  );
}

function KeyDialog({ title, busy, onCancel, onSave, children }) {
  useEffect(() => lockPageScroll(), []);
  return (
    <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onCancel(); }}>
      <div className="modal settings-dialog" role="dialog" aria-modal="true">
        <h2>{title}</h2>
        <div className="settings-form">{children}</div>
        <div className="logout-actions">
          <button type="button" className="modal-close" onClick={onCancel} disabled={busy}>Cancel</button>
          <button type="button" className="primary" onClick={onSave} disabled={busy}>{busy ? "Saving…" : "Save"}</button>
        </div>
      </div>
    </div>
  );
}

function ConfirmDelete({ busy, onYes, onNo }) {
  useEffect(() => lockPageScroll(), []);
  return (
    <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onNo(); }}>
      <div className="modal logout-dialog" role="dialog" aria-modal="true">
        <h2>Do you really want to delete this API key?</h2>
        <div className="logout-actions">
          <button type="button" className="modal-close" onClick={onNo} disabled={busy}>No</button>
          <button type="button" className="logout-yes" onClick={onYes} disabled={busy}>Yes</button>
        </div>
      </div>
    </div>
  );
}
