import { Checkout } from "./Checkout";

export function Legacy() {
  return <div>never mounted</div>;
}

export default function App() {
  return (
    <main>
      <Checkout />
    </main>
  );
}
