import type { ExtensionFactory, InlineExtension } from "../core/extensions/types.ts";
import { ramanujanExtension } from "@ramanujan/math-tools";
import type { PiExtensionAPI } from "@ramanujan/math-tools";
import llamaExtension from "./llama/index.ts";

// Ramanujan math tools (merge surface: this import + the array entry below +
// the @ramanujan/math-tools dep in package.json). Everything else pi-intact.
//
// The cast below is deliberate: pi's ExtensionAPI.overloads are stricter than
// the runtime contract (e.g. handler return unions include Promise), while our
// mirror declares exactly what the factory uses. Behavior at this boundary is
// covered by FakePI tests + the boot smoke script — not by this cast.
const ramanujanFactory: ExtensionFactory = (pi) => {
	ramanujanExtension(pi as unknown as PiExtensionAPI, {
		journalPath: process.env["RAMANUJAN_JOURNAL"] ?? "journal.jsonl",
		engineBin: process.env["RAMANUJAN_ENGINE_BIN"] ?? "ramanujan-engine",
	});
};

export const builtInExtensions: InlineExtension[] = [
	{ name: "llama.cpp", factory: llamaExtension, hidden: true },
	{ name: "ramanujan", factory: ramanujanFactory },
];
