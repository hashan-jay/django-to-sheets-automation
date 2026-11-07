import fs from "node:fs";
import path from "node:path";

const root = path.resolve("node_modules/rollup");
const wasm = path.resolve("node_modules/@rollup/wasm-node");
const native = path.join(root, "dist", "native.js");

if (!fs.existsSync(wasm)) {
  console.error("Install frontend dependencies before starting Vite.");
  process.exit(1);
}

if (fs.existsSync(native)) {
  fs.rmSync(root, { recursive: true, force: true });
  fs.symlinkSync(wasm, root, "junction");
}
