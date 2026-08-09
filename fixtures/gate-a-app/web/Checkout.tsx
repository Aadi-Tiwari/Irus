export function Checkout() {
  async function submit() {
    await fetch("/api/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "a@b.c", amount: 10 }),
    });
  }
  return <button onClick={submit}>Pay</button>;
}
