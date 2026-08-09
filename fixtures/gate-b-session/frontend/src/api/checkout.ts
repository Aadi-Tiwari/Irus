import { sendJson } from "./client";

export interface CheckoutRequest {
  email: string;
  amount_cents: number;
}

export interface CheckoutResponse {
  order_id: string;
  status: string;
}

export function checkout(request: CheckoutRequest): Promise<CheckoutResponse> {
  return sendJson<CheckoutResponse>("POST", "/orders", request);
}
