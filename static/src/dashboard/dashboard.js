import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const HEALTH = {
    good: { label: "Good", icon: "fa-check-circle" },
    watch: { label: "Watch", icon: "fa-exclamation-triangle" },
    risk: { label: "Risk", icon: "fa-times-circle" },
};

export class B2bFeeDashboard extends Component {
    static template = "otm_b2b_fee_tracker.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            data: null,
            filters: { academic_year: "", college_id: "", program_id: "" },
            trendTable: false,
            sortKey: "pending",
            trackerFilter: "all",
            tip: { show: false, x: 0, y: 0, title: "", rows: [] },
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call(
            "otm.b2bfee.dashboard",
            "get_dashboard_data",
            [],
            { filters: { ...this.state.filters } }
        );
        this.state.loading = false;
    }

    onFilterChange(key, ev) {
        this.state.filters[key] = ev.target.value;
        this.load();
    }

    // ------------------------------------------------------------ payment tracker
    get trackerRows() {
        const rows = this.state.data.tracker || [];
        const f = this.state.trackerFilter;
        if (f === "pending") {
            return rows.filter((r) => r.cells.some((c) => c.status !== "received"));
        }
        if (f === "received") {
            return rows.filter((r) => r.cells.length && r.cells.every((c) => c.status === "received"));
        }
        return rows;
    }

    get trackerColumns() {
        const max = Math.max(0, ...(this.state.data.tracker || []).map((r) => r.cells.length));
        return Array.from({ length: max }, (_, idx) => idx);
    }

    get trackerCounts() {
        const counts = { received: 0, partial: 0, not_received: 0, awaiting: 0 };
        for (const row of this.state.data.tracker || []) {
            for (const c of row.cells) {
                counts[c.status] += 1;
            }
        }
        return counts;
    }

    registerPayment(row, c) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Register Payment",
            res_model: "otm.b2bfee.payment",
            views: [[false, "form"]],
            target: "current",
            context: {
                default_college_id: row.college_id,
                default_batch_id: row.batch_id,
                default_amount: c.balance,
            },
        });
    }

    setTrackerFilter(value) {
        this.state.trackerFilter = value;
    }

    cellLabel(c) {
        if (c.status === "received") {
            return "Received";
        }
        if (c.status === "partial") {
            return "Part received";
        }
        if (c.status === "not_received") {
            return "Not received";
        }
        return "Awaiting";
    }

    cellNote(c) {
        if (c.status === "received") {
            const late = c.late_days;
            const when = late > 0 ? `${late} d late` : late < 0 ? `${-late} d early` : "on time";
            return `${c.received_on || ""} · ${when}`;
        }
        if (c.status === "partial") {
            const base = `${this.fmt(c.balance)} left`;
            return c.days_to_due < 0 ? `${base} · ${-c.days_to_due} d overdue` : `${base} · due ${c.due_date}`;
        }
        if (c.status === "not_received") {
            return `${-c.days_to_due} d overdue · due ${c.due_date}`;
        }
        return c.days_to_due === 0 ? "Due today" : `Due in ${c.days_to_due} d · ${c.due_date}`;
    }

    cellIcon(c) {
        return {
            received: "fa-check-circle",
            partial: "fa-adjust",
            not_received: "fa-times-circle",
            awaiting: "fa-clock-o",
        }[c.status];
    }

    // ------------------------------------------------------------ formatting
    fmt(value) {
        const cur = this.state.data.currency;
        const num = Number(value || 0).toLocaleString("en-IN", {
            minimumFractionDigits: 0,
            maximumFractionDigits: cur.decimals > 0 && Math.abs(value) < 1000 ? cur.decimals : 0,
        });
        return cur.position === "after" ? `${num} ${cur.symbol}` : `${cur.symbol}${num}`;
    }

    compact(value) {
        const abs = Math.abs(value || 0);
        const sym = this.state.data.currency.symbol;
        if (abs >= 1e7) {
            return `${sym}${(value / 1e7).toFixed(2)}Cr`;
        }
        if (abs >= 1e5) {
            return `${sym}${(value / 1e5).toFixed(2)}L`;
        }
        if (abs >= 1e3) {
            return `${sym}${(value / 1e3).toFixed(1)}K`;
        }
        return `${sym}${Math.round(value || 0)}`;
    }

    pct(value, max) {
        return max > 0 ? Math.max((value / max) * 100, value > 0 ? 1.5 : 0) : 0;
    }

    isSel(key, value) {
        return String(this.state.filters[key]) === String(value);
    }

    get meterWidth() {
        return Math.min(this.state.data.kpis.collection_pct, 100);
    }

    health(key) {
        return HEALTH[key];
    }

    // ------------------------------------------------------------ chart helpers
    get trendMax() {
        return Math.max(1, ...this.state.data.trend.flatMap((m) => [m.expected, m.collected]));
    }
    get ageingMax() {
        return Math.max(1, ...this.state.data.ageing.map((a) => a.amount));
    }
    get forecastMax() {
        return Math.max(1, ...this.state.data.forecast.map((f) => f.amount));
    }
    get topColleges() {
        return this.state.data.colleges.filter((c) => c.pending > 0).slice(0, 8);
    }
    get collegeMax() {
        return Math.max(1, ...this.topColleges.map((c) => c.pending));
    }
    get termMax() {
        return Math.max(1, ...this.state.data.by_term.map((t) => t.amount));
    }
    get programMax() {
        return Math.max(1, ...this.state.data.by_program.map((t) => t.amount));
    }
    get sortedColleges() {
        const key = this.state.sortKey;
        const rows = [...this.state.data.colleges];
        const desc = key !== "name";
        rows.sort((a, b) => {
            const av = a[key] ?? -1;
            const bv = b[key] ?? -1;
            if (key === "name") {
                return String(av).localeCompare(String(bv));
            }
            return desc ? bv - av : av - bv;
        });
        return rows;
    }
    setSort(key) {
        this.state.sortKey = key;
    }

    // ------------------------------------------------------------ tooltip
    showTip(ev, title, rows) {
        Object.assign(this.state.tip, {
            show: true,
            x: ev.clientX + 14,
            y: ev.clientY + 14,
            title,
            rows,
        });
    }
    moveTip(ev) {
        if (this.state.tip.show) {
            this.state.tip.x = ev.clientX + 14;
            this.state.tip.y = ev.clientY + 14;
        }
    }
    hideTip() {
        this.state.tip.show = false;
    }
    tipTrend(ev, m) {
        this.showTip(ev, m.label, [
            { label: "Expected", value: this.fmt(m.expected), color: "var(--b2b-neutral)" },
            { label: "Collected", value: this.fmt(m.collected), color: "var(--b2b-blue)" },
        ]);
    }
    tipAmount(ev, title, label, value, color) {
        this.showTip(ev, title, [{ label, value: this.fmt(value), color }]);
    }
    tipSplit(ev, row) {
        this.showTip(ev, row.label, [
            { label: "Collected", value: this.fmt(row.collected), color: "var(--b2b-blue)" },
            { label: "Pending", value: this.fmt(row.pending), color: "var(--b2b-neutral)" },
            { label: "Total", value: this.fmt(row.amount), color: "transparent" },
        ]);
    }

    // ------------------------------------------------------------ navigation
    baseDomain() {
        const f = this.state.filters;
        const domain = [["batch_id.state", "in", ["running", "closed"]]];
        if (f.academic_year) {
            domain.push(["batch_id.academic_year", "=", f.academic_year]);
        }
        if (f.college_id) {
            domain.push(["college_id", "=", parseInt(f.college_id, 10)]);
        }
        if (f.program_id) {
            domain.push(["program_id", "=", parseInt(f.program_id, 10)]);
        }
        return domain;
    }

    openInstallments(name, extra = []) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "otm.b2bfee.installment",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: [...this.baseDomain(), ...extra],
        });
    }
    openPending() {
        this.openInstallments("Pending Installments", [["balance", ">", 0]]);
    }
    openOverdue() {
        this.openInstallments("Overdue Installments", [
            ["balance", ">", 0],
            ["due_date", "<", this.state.data.today],
        ]);
    }
    openDueSoon(days) {
        const limit = new Date(this.state.data.today);
        limit.setDate(limit.getDate() + days);
        this.openInstallments(`Due in ${days} days`, [
            ["balance", ">", 0],
            ["due_date", ">=", this.state.data.today],
            ["due_date", "<=", limit.toISOString().slice(0, 10)],
        ]);
    }
    openCollegeDues(college) {
        this.openInstallments(`${college.name} – Pending`, [
            ["college_id", "=", college.id],
            ["balance", ">", 0],
        ]);
    }
    openColleges() {
        this.action.doAction("otm_b2b_fee_tracker.action_b2bfee_college");
    }
    openBatches() {
        this.action.doAction("otm_b2b_fee_tracker.action_b2bfee_batch");
    }
    openPayments() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Payments",
            res_model: "otm.b2bfee.payment",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: [["state", "=", "posted"]],
        });
    }
    openInstallment(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "otm.b2bfee.installment",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    async sendReminder(id) {
        const result = await this.orm.call("otm.b2bfee.installment", "action_send_reminder", [[id]]);
        const params = (result && result.params) || {};
        this.notification.add(params.message || "Reminder processed.", {
            title: params.title || "Reminder",
            type: params.type || "success",
        });
        await this.load();
    }
}

registry.category("actions").add("otm_b2b_fee_dashboard", B2bFeeDashboard);
