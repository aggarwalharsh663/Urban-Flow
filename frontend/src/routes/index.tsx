import { createFileRoute } from "@tanstack/react-router";
import App from "../components/urbanflow/App.jsx";

export const Route = createFileRoute("/")({
  component: App,
});