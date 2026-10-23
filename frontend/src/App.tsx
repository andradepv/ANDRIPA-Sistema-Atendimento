import { CustomerApp } from "./pages/customer/CustomerApp";
import { StaffApp } from "./pages/staff/StaffApp";
import { usePath, navigate } from "./lib/router";
import { useEffect } from "react";

export function App() {
  const path = usePath();
  const m = path.match(/^\/m\/([A-Za-z0-9_-]{10,32})\/?$/);
  useEffect(() => {
    if (path === "/") navigate("/painel", true);
  }, [path]);
  if (m) return <CustomerApp code={m[1]!} />;
  if (path.startsWith("/m/")) {
    return (
      <main className="c-shell c-center">
        <h1 className="c-title">Mesa não encontrada</h1>
        <p>Leia novamente o QR Code ou aproxime o celular da etiqueta da mesa.</p>
      </main>
    );
  }
  return <StaffApp path={path} />;
}
