/**
 * Generic selector component for extensions.
 * Displays a list of string options with keyboard navigation.
 */

import { Container, getKeybindings, Spacer, Text, type TUI } from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.ts";
import { CountdownTimer } from "./countdown-timer.ts";
import { DynamicBorder } from "./dynamic-border.ts";
import { keyHint, rawKeyHint } from "./keybinding-hints.ts";

export interface ExtensionSelectorFooter {
	label: string;
}

export interface ExtensionSelectorOptions {
	tui?: TUI;
	timeout?: number;
	onToggleToolsExpanded?: () => void;
	/** Max visible rows; the list scrolls inside the same window. Default: all. */
	maxVisible?: number;
	/** Separate action row below the list (e.g. Done). Tab switches focus to it. */
	footer?: ExtensionSelectorFooter;
	/** Type-to-filter: narrows options to those starting with the typed text. */
	searchable?: boolean;
	/** Static header lines rendered above the title (e.g. brand banner). */
	header?: string[];
}

export class ExtensionSelectorComponent extends Container {
	private options: string[];
	private selectedIndex = 0;
	private listContainer: Container;
	private footerContainer: Container;
	private onSelectCallback: (option: string) => void;
	private onCancelCallback: () => void;
	private titleText: Text;
	private baseTitle: string;
	private countdown: CountdownTimer | undefined;
	private onToggleToolsExpanded: (() => void) | undefined;
	private maxVisible: number | undefined;
	private footer: ExtensionSelectorFooter | undefined;
	private focus: "list" | "footer" = "list";
	private searchable: boolean;
	private query = "";
	private filtered: string[];

	constructor(
		title: string,
		options: string[],
		onSelect: (option: string) => void,
		onCancel: () => void,
		opts?: ExtensionSelectorOptions,
	) {
		super();

		this.options = options;
		this.onSelectCallback = onSelect;
		this.onCancelCallback = onCancel;
		this.onToggleToolsExpanded = opts?.onToggleToolsExpanded;
		this.maxVisible = opts?.maxVisible;
		this.footer = opts?.footer;
		this.searchable = opts?.searchable ?? false;
		this.filtered = [...options];
		this.baseTitle = title;

		this.addChild(new DynamicBorder());
		this.addChild(new Spacer(1));

		if (opts?.header) {
			for (const line of opts.header) {
				this.addChild(new Text(theme.fg("accent", line), 0, 0));
			}
			this.addChild(new Spacer(1));
		}

		this.titleText = new Text(theme.fg("accent", theme.bold(title)), 1, 0);
		this.addChild(this.titleText);
		this.addChild(new Spacer(1));

		if (opts?.timeout && opts.timeout > 0 && opts.tui) {
			this.countdown = new CountdownTimer(
				opts.timeout,
				opts.tui,
				(s) => this.titleText.setText(theme.fg("accent", theme.bold(`${this.baseTitle} (${s}s)`))),
				() => this.onCancelCallback(),
			);
		}

		this.listContainer = new Container();
		this.addChild(this.listContainer);
		this.footerContainer = new Container();
		this.addChild(this.footerContainer);
		this.addChild(new Spacer(1));
		this.addChild(
			new Text(
				rawKeyHint("↑↓", "navigate") +
					"  " +
					keyHint("tui.select.confirm", "select") +
					"  " +
					keyHint("tui.select.cancel", "cancel") +
					(this.footer ? "  " + rawKeyHint("Tab", "done") : ""),
				1,
				0,
			),
		);
		this.addChild(new Spacer(1));
		this.addChild(new DynamicBorder());

		this.updateList();
	}

	private applyFilter(): void {
		const q = this.query.toLowerCase();
		this.filtered = q ? this.options.filter((o) => o.toLowerCase().startsWith(q)) : [...this.options];
		this.selectedIndex = Math.max(0, Math.min(this.selectedIndex, this.filtered.length - 1));
		this.titleText.setText(
			theme.fg("accent", theme.bold(this.query ? `${this.baseTitle}  [${this.query}]` : this.baseTitle)),
		);
	}

	private updateList(): void {
		this.listContainer.clear();
		const total = this.filtered.length;
		let startIndex = 0;
		let endIndex = total;
		if (this.maxVisible !== undefined && total > this.maxVisible) {
			const half = Math.floor(this.maxVisible / 2);
			startIndex = Math.max(0, Math.min(this.selectedIndex - half, total - this.maxVisible));
			endIndex = Math.min(startIndex + this.maxVisible, total);
		}
		for (let i = startIndex; i < endIndex; i++) {
			const isSelected = i === this.selectedIndex && this.focus === "list";
			const text = isSelected
				? theme.fg("accent", "→ ") + theme.fg("accent", this.filtered[i])
				: `  ${theme.fg("text", this.filtered[i])}`;
			this.listContainer.addChild(new Text(text, 1, 0));
		}
		if (this.filtered.length === 0) {
			this.listContainer.addChild(new Text(theme.fg("muted", "  (no matches — Backspace to clear)"), 1, 0));
		} else if (endIndex - startIndex < total) {
			this.listContainer.addChild(
				new Text(theme.fg("muted", `  (${this.selectedIndex + 1}/${total})`), 1, 0),
			);
		}
		this.footerContainer.clear();
		if (this.footer) {
			const focused = this.focus === "footer";
			const text = focused
				? theme.fg("accent", "→ ") + theme.fg("accent", theme.bold(this.footer.label))
				: `  ${theme.fg("muted", this.footer.label)}`;
			this.footerContainer.addChild(new Text(text, 1, 0));
		}
	}

	private isPrintable(keyData: string): boolean {
		if (keyData.length !== 1) return false;
		const code = keyData.charCodeAt(0);
		return code >= 32 && code !== 127;
	}

	handleInput(keyData: string): void {
		const kb = getKeybindings();
		if (kb.matches(keyData, "app.tools.expand")) {
			this.onToggleToolsExpanded?.();
		} else if (keyData === "\t" && this.footer) {
			this.focus = this.focus === "list" ? "footer" : "list";
			this.updateList();
		} else if (kb.matches(keyData, "tui.select.up") || (!this.searchable && keyData === "k")) {
			this.focus = "list";
			this.selectedIndex = Math.max(0, this.selectedIndex - 1);
			this.updateList();
		} else if (kb.matches(keyData, "tui.select.down") || (!this.searchable && keyData === "j")) {
			this.focus = "list";
			this.selectedIndex = Math.min(this.filtered.length - 1, this.selectedIndex + 1);
			this.updateList();
		} else if (kb.matches(keyData, "tui.select.confirm") || keyData === "\n") {
			if (this.focus === "footer" && this.footer) {
				this.onSelectCallback(this.footer.label);
				return;
			}
			const selected = this.filtered[this.selectedIndex];
			if (selected) this.onSelectCallback(selected);
		} else if (kb.matches(keyData, "tui.select.cancel")) {
			this.onCancelCallback();
		} else if (this.searchable && (keyData === "\x7f" || keyData === "\b")) {
			this.focus = "list";
			this.query = this.query.slice(0, -1);
			this.applyFilter();
			this.updateList();
		} else if (this.searchable && this.isPrintable(keyData)) {
			this.focus = "list";
			this.query += keyData;
			this.applyFilter();
			this.updateList();
		}
	}

	dispose(): void {
		this.countdown?.dispose();
	}
}
