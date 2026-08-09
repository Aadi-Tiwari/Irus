import { useState } from "react";

const API_BASE = process.env.API_BASE;

export function Checkout() {
  const [email, setEmail] = useState("");
  const [amount, setAmount] = useState(0);

  async function submit() {
    const response = await fetch("/api/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email, amount: amount, note: "" }),
    });
    return response.json();
  }

  return null;
}
