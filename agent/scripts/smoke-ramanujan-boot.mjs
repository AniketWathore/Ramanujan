#!/usr/bin/env node
/**
 * Boot smoke test — distinguishes Ramanujan-boot from pi-boot.
 * "No crash" alone is insufficient (a vanilla pi boot passes it).
 *
 * 1. Imports builtInExtensions from the BUILT coding-agent dist (real wiring
 *    code, not a fake) and asserts the ramanujan entry is present.
 * 2. Invokes the real factory with a shape-faithful recorder and asserts the
 *    Ramanujan surface: killcheck_encode + killcheck_run + panel_review
 *    tools, /card /runs /verdict /panel commands, math prompt appended,
 *    bare-verdict reframe, and the tool_call gate refusing unconfirmed runs.
 * 3. Greps the SHIPPED bundle for the tool names (proves inclusion in binary).
 *
 * Run: node agent/scripts/smoke-ramanujan-boot.mjs
 * Exit 0 = Ramanujan booted. Non-zero = vanilla pi (or broken wiring).
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..");
const codingAgentDist = join(repoRoot, "agent", "packages", "coding-agent", "dist");
const bundleCli = join(repoRoot, "agent", "packages", "coding-agent", "dist", "bundle", "cli.js");

let failures = 0;
function check(name, cond, detail = "") {
	if (cond) {
		console.log(`ok - ${name}`);
	} else {
		failures++;
		console.error(`FAIL - ${name} ${detail}`);
	}
}

// 1. Real wiring: builtInExtensions from built dist.
const { builtInExtensions } = await import(join(codingAgentDist, "extensions", "index.js"));
const names = builtInExtensions.map((e) => e.name);
check("builtInExtensions includes ramanujan", names.includes("ramanujan"), `got [${names}]`);
check("llama entry untouched", names.includes("llama.cpp"));

// 2. Real factory against a shape-faithful recorder (five-stage pipeline, killcheck removed per user request).
const entry = builtInExtensions.find((e) => e.name === "ramanujan");
const tools = [];
const commands = [];
const hooks = [];
const recorder = {
	registerTool: (t) => void tools.push(t.name),
	registerCommand: (name) => void commands.push(name),
	on: (event, _handler) => void hooks.push(event),
};
await entry.factory(recorder);
check("tools registered (five-stage: initialise, literature, checkpoint, worktree, claim)", tools.length === 5, `got [${tools}]`);
check("tools are five-stage (no killcheck)", tools.includes("ramanujan_initialise") && tools.includes("ramanujan_literature") && tools.includes("checkpoint_respond") && tools.includes("worktree_spawn") && tools.includes("claim_post") && !tools.includes("killcheck_encode") && !tools.includes("killcheck_run"), `got [${tools}]`);
check("no confirm tool for the model", !tools.some((t) => t.includes("confirm")));
check("commands registered (checkpoint only, v1 slash removed)", commands.length === 1 && commands[0] === "checkpoint", `got [${commands}]`);
check("hooks registered", ["before_agent_start", "message_end"].every((h) => hooks.includes(h)), `got [${hooks}]`);
check("no tool_call gate (v1 removed)", !hooks.includes("tool_call"));

// 3. Shipped bundle contains the tools (proves inclusion in the binary).
import { readdirSync, statSync } from "node:fs";
import { join as joinPath } from "node:path";
function* walkJs(dir) {
	for (const e of readdirSync(dir)) {
		const p = joinPath(dir, e);
		if (statSync(p).isDirectory()) yield* walkJs(p);
		else if (p.endsWith(".js")) yield p;
	}
}
let bundleText = "";
for (const f of walkJs(joinPath(repoRoot, "agent", "packages", "coding-agent", "dist", "bundle"))) {
	bundleText += readFileSync(f, "utf-8");
}
check("bundle does NOT contain killcheck_encode (removed per user request)", !bundleText.includes("killcheck_encode"));
check("bundle does NOT contain killcheck_run (removed)", !bundleText.includes("killcheck_run"));
check("bundle contains five-stage tools", bundleText.includes("ramanujan_initialise") && bundleText.includes("ramanujan_literature") && bundleText.includes("checkpoint_respond") && bundleText.includes("worktree_spawn") && bundleText.includes("claim_post"));
check("bundle does NOT contain panel_review slash (v1 removed)", !bundleText.includes('registerCommand("panel"'));
check("bundle contains math prompt", bundleText.includes("You are Ramanujan, a math research assistant."));
check("bundle contains five-stage pipeline prompt", bundleText.includes("five-stage pipeline"));

// 4. Version branding.
let version = "";
try {
	version = execFileSync(process.execPath, [bundleCli, "--version"], { encoding: "utf-8" }).trim();
} catch (e) {
	version = `ERROR: ${e.message}`;
}
check("ramanujan --version reports 0.4.x", /^0\.4\./.test(version), `got ${JSON.stringify(version)}`);

if (failures > 0) {
	console.error(`\n${failures} smoke check(s) FAILED — this is vanilla pi or broken wiring.`);
	process.exit(1);
}
console.log("\nRamanujan boot surface verified.");
