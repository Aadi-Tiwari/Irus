// Consumer side, as agent B would have written it working alone.
import { useState } from "react";

const API_BASE = process.env.API_BASE;

export function Checkout() {
  const [email, setEmail] = useState("");
  const [total, setTotal] = useState("0");

  async function submit() {
    const form = new FormData();
    form.append("user_email", email);
    form.append("total", total);

    const response = await fetch("/api/checkout", {
      method: "POST",
      body: form,
    });
    return response.json();
  }

  return null;
}
