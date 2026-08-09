import { API_BASE } from "../config";

export class ApiError extends Error {
  readonly status: number;
  readonly body: string;

  constructor(status: number, body: string) {
    super(`Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

function url(path: string): string {
  return `${API_BASE}${path}`;
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new ApiError(response.status, await response.text());
  }
  return (await response.json()) as T;
}

export async function getJson<T>(path: string): Promise<T> {
  return parse<T>(await fetch(url(path), { method: "GET" }));
}

export async function sendJson<T>(
  method: "POST" | "PUT" | "PATCH",
  path: string,
  body: unknown,
): Promise<T> {
  const response = await fetch(url(path), {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parse<T>(response);
}

// Content-Type is intentionally unset: the browser must add the multipart boundary.
export async function sendForm<T>(
  method: "POST" | "PUT",
  path: string,
  form: FormData,
): Promise<T> {
  return parse<T>(await fetch(url(path), { method, body: form }));
}
