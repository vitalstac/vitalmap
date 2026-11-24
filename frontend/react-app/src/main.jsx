import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/header.css";
import "./styles/chat.css";
import "./styles/search.css";
import "./styles/map.css";
import "./styles/results.css";
import "./styles/responsive.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
