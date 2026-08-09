export async function loadOrder(id: string) {
  const res = await fetch(`/api/orders/${id}`);
  return res.json();
}
