// ABOUTME: Entry point: mounts the app into the page. All code and styles are local bundle files.
// ABOUTME: Nothing here reads the posting or the report; the screens fetch what they show.
import { mount } from "svelte";
import "./app.css";
import App from "./App.svelte";

const target = document.getElementById("app");
if (!target) throw new Error("the page has no #app element");

export default mount(App, { target });
