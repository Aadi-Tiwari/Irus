export function Checkout() {
  async function submit() {
    const form = new FormData();
    form.append("user_email", "a@b.c");
    form.append("total", "10");
    const res = await fetch("/api/checkout", { method: "POST", body: form });
    const { orderId, status } = await res.json();
    return status;
  }
  return <button onClick={submit}>Pay</button>;
}
