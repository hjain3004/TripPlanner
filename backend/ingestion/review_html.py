from __future__ import annotations

import html
from collections.abc import Sequence

from ingestion.activation import ActivationBundle, ActivationBundleRecord, DryRunReport
from ingestion.contracts import ChangeProposal
from ingestion.review_types import ReviewContext

INVISIBLE = (
    frozenset(range(0x200B, 0x2010))
    | frozenset(range(0x202A, 0x202F))
    | frozenset(range(0x2066, 0x206A))
    | {0xFEFF}
)


def h(value: object) -> str:
    text = str(value)
    text = "".join(
        f"⟦U+{ord(char):04X}⟧"
        if ord(char) in INVISIBLE or (ord(char) < 0x20 and char not in "\t\n")
        else char
        for char in text
    )
    return html.escape(text, quote=True)


def page(title: str, body_html: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>"
        f"{h(title)}</title><link rel='stylesheet' href='/review/static/review.css'>"
        f"</head><body>{body_html}</body></html>"
    )


def render_login(error_code: str | None = None) -> str:
    return page(
        "FI3 review login",
        "<h1>FI3 review</h1>"
        f"<p>{h(error_code or 'Use the launch token printed by the local server.')}"
        "</p><form method='post' action='/review/login'>"
        "<input name='token' type='password'><button>Sign in</button></form>",
    )


def render_queue(proposals: Sequence[ChangeProposal]) -> str:
    rows = "".join(
        f"<li><a href='/review/proposal?id={h(p.proposal_id)}'>"
        f"{h(p.proposal_id)}</a> — {h(p.status.value)}</li>"
        for p in proposals
    )
    return page("Review queue", f"<h1>Review queue</h1><ul>{rows}</ul>")


def render_proposal(ctx: ReviewContext, *, csrf_token: str, client_event_id: str) -> str:
    evidence = "".join(
        f"<blockquote>{h(item.before)}<mark>{h(item.span.quote)}</mark>{h(item.after)}</blockquote>"
        for item in ctx.evidence
    )
    findings = "".join(
        f"<li>{h(item.code.value)}: {h(item.message)}</li>" for item in ctx.computed_findings
    )
    disabled = " disabled" if ctx.blocking_for_approval else ""
    edit = ""
    changed = next((item for item in ctx.field_diffs if item.changed and item.evidence), None)
    if changed is not None and changed.evidence:
        span = changed.evidence[0]
        edit = (
            f"<label>Edit {h(changed.field_path)}"
            f"<input name='edit_field_path' value='{h(changed.field_path)}'></label>"
            f"<input name='edit_raw_value' placeholder='source value'>"
            f"<input type='hidden' name='edit_quote' value='{h(span.quote)}'>"
            f"<input type='hidden' name='edit_snapshot_id' value='{h(span.snapshot_id)}'>"
            f"<button name='action' value='edit'{disabled}>Save edit</button>"
        )
    form = (
        "<form method='post' action='/review/decision'>"
        f"{edit}"
        f"<input type='hidden' name='csrf_token' value='{h(csrf_token)}'>"
        f"<input type='hidden' name='client_event_id' value='{h(client_event_id)}'>"
        f"<input type='hidden' name='proposal_id' value='{h(ctx.proposal.proposal_id)}'>"
        f"<input type='hidden' name='expected_version' value='{ctx.proposal.version}'>"
        "<input name='reason' required><input name='curator_confidence' value='0.90'>"
        f"<button name='action' value='approve'{disabled}>Approve</button>"
        "<button name='action' value='reject'>Reject</button>"
        "<button name='action' value='reverify'>Request re-verification</button></form>"
    )
    return page(
        "Proposal",
        f"<h1>{h(ctx.proposal.proposal_id)}</h1>"
        f"<p>{h(ctx.proposal.change_summary)}</p><ul>{findings}</ul>{evidence}{form}",
    )


def render_raw_text(snapshot_id: str, text: str) -> str:
    return page("Raw snapshot", f"<h1>{h(snapshot_id)}</h1><pre>{h(text)}</pre>")


def render_bundle(
    record: ActivationBundleRecord,
    bundle: ActivationBundle,
    report: DryRunReport | None,
    *,
    csrf_token: str,
    client_event_id: str,
) -> str:
    body = (
        f"<h1>Activation bundle {h(record.bundle_sha256)}</h1>"
        f"<p>Applicable: {h(bundle.applicable)}</p>"
    )
    if report:
        body += (
            "<ul>"
            + "".join(f"<li>{h(e.target_id)}: {h(e.status)}</li>" for e in report.entries)
            + "</ul>"
        )
    return page("Activation bundle", body)


def render_error(status: int, code: str) -> str:
    return page(f"Error {status}", f"<h1>Error {status}</h1><p>{h(code)}</p>")
