const TOKEN_KEY = "brands_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const token = getToken();
  if (token) headers.Authorization = `Token ${token}`;
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options = { ...options, body: JSON.stringify(options.body) };
  }
  const response = await fetch(path, { ...options, headers });
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  if (response.status === 401 && path !== "/api/auth/login/") {
    setToken("");
    window.location.reload();
  }
  if (!response.ok) {
    let message = data?.detail || "Request failed";
    if (typeof message !== "string") message = "Request failed";
    if (message.includes("<html") || message.includes("<!DOCTYPE")) {
      message = "The server hit an error while saving. Restart the app after the database update, then try again.";
    }
    throw new Error(message.slice(0, 500));
  }
  return data;
}
