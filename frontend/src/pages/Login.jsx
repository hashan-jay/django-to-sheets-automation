import { useEffect, useRef, useState } from "react";
import { api, setToken } from "../api";

export default function Login({ onSuccess }) {
  const stageRef = useRef(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [focused, setFocused] = useState("");
  const [now, setNow] = useState(() => new Date());
  const [pointer, setPointer] = useState({ x: 68, y: 32 });
  const [motionOk, setMotionOk] = useState(true);
  const [log, setLog] = useState(["awaiting operator"]);

  useEffect(() => {
    const clock = window.setInterval(() => setNow(new Date()), 1000);
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const syncMotion = () => setMotionOk(!motion.matches);
    syncMotion();
    motion.addEventListener("change", syncMotion);
    return () => {
      window.clearInterval(clock);
      motion.removeEventListener("change", syncMotion);
    };
  }, []);

  function note(line) {
    setLog((current) => [...current.slice(-3), line]);
  }

  function trackPointer(event) {
    const rect = stageRef.current?.getBoundingClientRect();
    if (!rect) return;
    setPointer({
      x: ((event.clientX - rect.left) / rect.width) * 100,
      y: ((event.clientY - rect.top) / rect.height) * 100,
    });
  }

  function readCaps(event) {
    setCapsLock(event.getModifierState?.("CapsLock") || false);
  }

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    note("handshake started");
    try {
      const data = await api("/api/auth/login/", {
        method: "POST",
        body: { username, password },
      });
      setToken(data.token);
      onSuccess(data.user);
    } catch (err) {
      setError(err.message);
      note("handshake rejected");
    } finally {
      setBusy(false);
    }
  }

  const signal = Math.min(100, username.trim().length * 9 + Math.min(password.length, 10) * 4);
  const tilt = motionOk
    ? `rotateX(${((pointer.y - 42) / 22).toFixed(2)}deg) rotateY(${((58 - pointer.x) / 22).toFixed(2)}deg)`
    : "none";
  const clock = now.toLocaleTimeString([], { hour12: false });
  const links = [
    {
      id: "edge",
      label: "Edge node",
      state: username.trim() ? "synced" : focused === "username" ? "listening" : "standby",
    },
    {
      id: "vault",
      label: "Credential vault",
      state: showPassword ? "visible" : password ? "sealed" : focused === "password" ? "armed" : "locked",
    },
    {
      id: "stream",
      label: "Live stream",
      state: busy ? "linking" : signal >= 80 ? "ready" : "armed",
    },
  ];

  return (
    <div
      className="login-stage"
      ref={stageRef}
      onMouseMove={motionOk ? trackPointer : undefined}
      onMouseLeave={motionOk ? () => setPointer({ x: 68, y: 32 }) : undefined}
    >
      <div className="login-grid" aria-hidden="true" />
      <div
        className="login-orb"
        aria-hidden="true"
        style={{
          background: `radial-gradient(circle at ${pointer.x}% ${pointer.y}%, rgba(56, 189, 248, 0.28), transparent 28%)`,
        }}
      />
      <div className="login-scan" aria-hidden="true" />

      <div className="login-frame">
        <aside className="login-telemetry" aria-hidden="true">
          <p className="login-kicker">Secure access</p>
          <p className="login-clock">{clock}</p>
          <ul className="login-links">
            {links.map((link) => (
              <li key={link.id} className={focused ? "is-live" : ""}>
                <span className={`login-dot ${link.id} ${link.state}`} />
                <span>{link.label}</span>
                <strong>{link.state}</strong>
              </li>
            ))}
          </ul>
          <div className="login-meter">
            <div>
              <span>Signal</span>
              <strong>{signal}%</strong>
            </div>
            <b>
              <i style={{ width: `${signal}%` }} />
            </b>
          </div>
          <ol className="login-log">
            {log.map((line, index) => (
              <li key={`${line}-${index}`}>{line}</li>
            ))}
          </ol>
        </aside>

        <form
          className={`login-card${error ? " has-error" : ""}${busy ? " is-busy" : ""}`}
          style={{ transform: tilt }}
          onSubmit={submit}
        >
          <div className="login-card-glow" aria-hidden="true" />
          <header>
            <span className="login-badge">SYS / AUTH</span>
            <h1>KABOOM77 Automation</h1>
            <p>Sign in to open the live transaction console.</p>
          </header>

          <label className={focused === "username" ? "is-hot" : ""}>
            Username
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              onFocus={() => {
                setFocused("username");
                note("identity field armed");
              }}
              onBlur={() => setFocused("")}
              autoComplete="username"
              spellCheck="false"
            />
          </label>
          <label className={focused === "password" ? "is-hot" : ""}>
            Password
            <span className="login-secret">
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                onFocus={() => {
                  setFocused("password");
                  note("credential field armed");
                }}
                onBlur={() => setFocused("")}
                onKeyUp={readCaps}
                onKeyDown={readCaps}
                autoComplete="current-password"
              />
              <button
                type="button"
                className="login-reveal"
                aria-pressed={showPassword}
                aria-label={showPassword ? "Hide password" : "Show password"}
                onClick={() => setShowPassword((current) => !current)}
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </span>
            {capsLock && <em className="login-caps">Caps lock is on</em>}
          </label>

          {error && (
            <div className="form-error" role="alert">
              {error}
            </div>
          )}

          <button type="submit" className="login-submit" disabled={busy}>
            <span>{busy ? "Linking session" : "Enter console"}</span>
          </button>
        </form>
      </div>
    </div>
  );
}
