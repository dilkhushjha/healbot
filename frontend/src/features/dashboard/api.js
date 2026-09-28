export const API = (
  process.env.REACT_APP_HEALBOT_API_URL ||
  process.env.REACT_APP_API_URL ||
  "http://localhost:8000"
).replace(/\/$/, "");

export async function apiRequest(apiKey, method, path, body) {
  const response = await fetch(`${API}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || data.message || `Request failed: ${path}`);
  }
  return data;
}

export async function persistLocalProfile(apiKey) {
  if (!apiKey) return null;
  const response = await fetch(`${API}/auth/local-profile`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      api_url: API,
      dashboard_url: window.location.origin,
    }),
  });
  if (!response.ok) return null;
  return response.json();
}
