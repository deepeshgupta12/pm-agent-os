import { Link, Route, Routes } from "react-router-dom";
import Register from "./pages/Register";
import Login from "./pages/Login";
import Me from "./pages/Me";

export default function App() {
  return (
    <div style={{ maxWidth: 920, margin: "24px auto", padding: 16 }}>
      <h1>PM Agent OS (V0)</h1>
      <p>Auth V0: Email/Password + JWT (HttpOnly cookie)</p>

      <nav style={{ display: "flex", gap: 12, margin: "16px 0" }}>
        <Link to="/register">Register</Link>
        <Link to="/login">Login</Link>
        <Link to="/me">Me</Link>
      </nav>

      <Routes>
        <Route path="/" element={<Me />} />
        <Route path="/register" element={<Register />} />
        <Route path="/login" element={<Login />} />
        <Route path="/me" element={<Me />} />
      </Routes>
    </div>
  );
}