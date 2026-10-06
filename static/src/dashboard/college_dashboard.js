import { useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { B2bFeeDashboard } from "./dashboard";

export class B2bFeeCollegeDashboard extends B2bFeeDashboard {
    static template = "otm_b2b_fee_tracker.CollegeDashboard";

    setup() {
        super.setup();
        const ctx = this.props.action?.context || {};
        this.collegeId = ctx.college_id || this.props.action?.params?.college_id;
        this.pay = useState({
            open: false,
            busy: false,
            batch_id: "",
            amount: "",
            date: new Date().toISOString().slice(0, 10),
            payment_mode: "bank",
            reference: "",
            note: "",
        });
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call(
            "otm.b2bfee.college.dashboard",
            "get_college_data",
            [this.collegeId]
        );
        this.state.loading = false;
    }

    get payableBatches() {
        return (this.state.data.batches || []).filter((b) => b.payable);
    }

    // ------------------------------------------------------------ quick payment
    openPay(batchId, amount) {
        const batches = this.payableBatches;
        const chosen = batchId || (batches.length === 1 ? batches[0].id : "");
        const batch = batches.find((b) => b.id === chosen);
        this.pay.open = true;
        this.pay.batch_id = chosen;
        this.pay.amount = amount !== undefined ? amount : batch ? batch.pending : "";
    }

    closePay() {
        this.pay.open = false;
    }

    onPayBatch(ev) {
        const id = parseInt(ev.target.value, 10) || "";
        this.pay.batch_id = id;
        const batch = this.payableBatches.find((b) => b.id === id);
        if (batch) {
            this.pay.amount = batch.pending;
        }
    }

    onPayField(key, ev) {
        this.pay[key] = ev.target.value;
    }

    // override: a tracker cell's button prefills the inline form instead of leaving the page
    registerPayment(row, c) {
        this.openPay(row.batch_id, c.balance);
        document.querySelector(".o_b2bfee_dash")?.scrollIntoView?.({ behavior: "smooth" });
    }

    async submitPay() {
        if (this.pay.busy) {
            return;
        }
        this.pay.busy = true;
        try {
            const res = await this.orm.call(
                "otm.b2bfee.college.dashboard",
                "quick_payment",
                [this.collegeId],
                {
                    vals: {
                        batch_id: this.pay.batch_id,
                        amount: this.pay.amount,
                        date: this.pay.date,
                        payment_mode: this.pay.payment_mode,
                        reference: this.pay.reference,
                        note: this.pay.note,
                    },
                }
            );
            this.notification.add(`Payment ${res.name} posted.`, { type: "success" });
            this.pay.open = false;
            this.pay.amount = "";
            this.pay.reference = "";
            this.pay.note = "";
            await this.load();
        } finally {
            this.pay.busy = false;
        }
    }

    // ------------------------------------------------------------ navigation
    editCollege() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "otm.b2bfee.college",
            res_id: this.collegeId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openPaymentRecord(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "otm.b2bfee.payment",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openBatchRecord(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "otm.b2bfee.batch",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openCollege() {}
}

registry.category("actions").add("otm_b2b_fee_college_dashboard", B2bFeeCollegeDashboard);
