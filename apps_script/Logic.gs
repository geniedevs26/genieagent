/**
 * GenieAgent approval sidebar - pure helpers.
 *
 * Everything in this file works on plain arrays and returns plain objects, so
 * the same code can run in Apps Script (V8) and under Node in
 * tests/apps_script. No SpreadsheetApp, no LockService, no network, and above
 * all no send capability: approval only writes review decisions into the
 * Outreach tab. Sending stays with pipeline_send.py and its two-key gate.
 */

var APPROVAL_DRAFT = 'draft';
var APPROVAL_PENDING = 'pending_owner_approval';
var APPROVAL_APPROVED = 'approved';
var APPROVAL_REJECTED = 'rejected';
var APPROVAL_SENT = 'sent';
var APPROVAL_FAILED = 'failed';
var APPROVAL_SUPPRESSED = 'suppressed';

var LEAD_QUALIFIED = 'qualified';
var EMAIL_SENDABLE_STATUSES = ['valid', 'deliverable'];

var OUTREACH_HEADERS = [
  'draft_id',
  'lead_id',
  'channel',
  'provider',
  'recipient',
  'recipient_masked',
  'subject',
  'body',
  'approval_status',
  'approved_by',
  'approved_at',
  'sent_at',
  'provider_message_id',
  'delivery_status',
  'failure_reason',
  'follow_up_of',
  'attempt_count',
  'created_at',
  'updated_at'
];

var LEAD_HEADERS = [
  'lead_id',
  'company_name',
  'normalized_company',
  'domain',
  'website',
  'country',
  'industry',
  'employee_range',
  'contact_name',
  'contact_title',
  'email',
  'email_type',
  'email_status',
  'email_score',
  'email_verified_at',
  'email_source',
  'phone_business',
  'phone_source',
  'phone_type',
  'source_provider',
  'source_url',
  'source_ref',
  'service_fit',
  'qualification_score',
  'qualification_status',
  'qualification_reason',
  'need_summary',
  'priority',
  'outreach_status',
  'follow_up_count',
  'last_contact_at',
  'last_reply_at',
  'order_status',
  'whatsapp_status',
  'do_not_contact',
  'consent_basis',
  'notes',
  'verification_status',
  'verification_reason',
  'identity_status',
  'verification_method',
  'verification_sources',
  'verification_checks',
  'fraud_indicators',
  'legal_basis',
  'verification_checked_at',
  'verified_at',
  'verification_fingerprint',
  'created_at',
  'updated_at'
];

var ACTIVITY_HEADERS = ['event_id', 'timestamp', 'event_type', 'status', 'lead_id', 'summary', 'details'];

var DECISION_COLUMNS = ['approval_status', 'approved_by', 'approved_at', 'updated_at', 'failure_reason'];
var DEFAULT_REJECT_REASON = 'Rejected by owner in the GenieAgent sidebar.';

/** Coerce any cell value to a trimmed string, normalising dates to ISO-8601. */
function textOf(value) {
  if (value === null || value === undefined) {
    return '';
  }
  if (Object.prototype.toString.call(value) === '[object Date]') {
    return value.toISOString().replace(/\.\d{3}Z$/, 'Z');
  }
  return String(value).trim();
}

/** Column index by header name (case-insensitive, spaces/underscores interchangeable). */
function headerIndex(header, name) {
  var wanted = String(name || '').trim().toLowerCase().replace(/\s+/g, '_');
  if (!wanted || !header) {
    return -1;
  }
  for (var i = 0; i < header.length; i++) {
    var current = String(header[i] === null || header[i] === undefined ? '' : header[i])
      .trim()
      .toLowerCase()
      .replace(/\s+/g, '_');
    if (current === wanted) {
      return i;
    }
  }
  return -1;
}

/** Read a named column from one row. Returns '' when the column is absent. */
function cellOf(header, values, name) {
  var index = headerIndex(header, name);
  if (index < 0 || !values) {
    return '';
  }
  return textOf(values[index]);
}

/** Mask an email the same way genieagent.util.mask_email does. */
function maskEmail(value) {
  var text = textOf(value);
  var at = text.indexOf('@');
  if (!text || at < 1) {
    return '';
  }
  var local = text.slice(0, at);
  var domain = text.slice(at + 1);
  var stars = Math.max(2, Math.min(6, local.length - 1));
  return local.slice(0, 1) + new Array(stars + 1).join('*') + '@' + domain;
}

/** Mask a phone number the same way genieagent.util.mask_phone does. */
function maskPhone(value) {
  var digits = textOf(value).replace(/\D/g, '');
  if (digits.length < 4) {
    return digits ? 'hidden' : '';
  }
  return new Array(digits.length - 1).join('*') + digits.slice(-2);
}

function maskRecipient(channel, value) {
  return channel === 'whatsapp' ? maskPhone(value) : maskEmail(value);
}

/** Index leads by lead_id so a draft card can show the company behind it. */
function buildLeadLookup(header, rows) {
  var lookup = {};
  var idIndex = headerIndex(header, 'lead_id');
  if (idIndex < 0) {
    return lookup;
  }
  for (var i = 0; i < rows.length; i++) {
    var id = textOf(rows[i][idIndex]);
    if (!id) {
      continue;
    }
    lookup[id] = {
      company: cellOf(header, rows[i], 'company_name'),
      contactName: cellOf(header, rows[i], 'contact_name'),
      qualificationStatus: cellOf(header, rows[i], 'qualification_status'),
      qualificationScore: cellOf(header, rows[i], 'qualification_score'),
      emailStatus: cellOf(header, rows[i], 'email_status'),
      doNotContact: cellOf(header, rows[i], 'do_not_contact').toLowerCase() === 'true',
      outreachStatus: cellOf(header, rows[i], 'outreach_status'),
      lastReplyAt: cellOf(header, rows[i], 'last_reply_at')
    };
  }
  return lookup;
}

/** Turn one Outreach row into the object the sidebar renders. */
function draftView(header, values, rowNumber, lead) {
  var channel = cellOf(header, values, 'channel').toLowerCase();
  var recipient = cellOf(header, values, 'recipient');
  var masked = cellOf(header, values, 'recipient_masked') || maskRecipient(channel, recipient);
  var leadInfo = lead || {};
  var view = {
    rowNumber: rowNumber,
    draftId: cellOf(header, values, 'draft_id'),
    leadId: cellOf(header, values, 'lead_id'),
    channel: channel,
    provider: cellOf(header, values, 'provider'),
    subject: cellOf(header, values, 'subject'),
    body: cellOf(header, values, 'body'),
    recipientMasked: masked,
    hasRecipient: !!recipient,
    status: cellOf(header, values, 'approval_status').toLowerCase(),
    approvedBy: cellOf(header, values, 'approved_by'),
    approvedAt: cellOf(header, values, 'approved_at'),
    sentAt: cellOf(header, values, 'sent_at'),
    deliveryStatus: cellOf(header, values, 'delivery_status'),
    createdAt: cellOf(header, values, 'created_at'),
    followUpOf: cellOf(header, values, 'follow_up_of'),
    company: leadInfo.company || '',
    contactName: leadInfo.contactName || '',
    qualificationStatus: leadInfo.qualificationStatus || '',
    qualificationScore: leadInfo.qualificationScore || '',
    emailStatus: leadInfo.emailStatus || '',
    doNotContact: !!leadInfo.doNotContact,
    outreachStatus: leadInfo.outreachStatus || '',
    leadFound: !!lead
  };
  view.warnings = draftWarnings(view);
  return view;
}

/** Non-blocking hints shown on the card; the hard checks live in decisionBlocker. */
function draftWarnings(draft) {
  var warnings = [];
  if (draft.followUpOf) {
    warnings.push('Follow-up draft (refers to an earlier message).');
  }
  if (!draft.leadFound) {
    warnings.push('Lead row not found in the Leads tab.');
  }
  if (draft.channel === 'email' && draft.emailStatus && EMAIL_SENDABLE_STATUSES.indexOf(draft.emailStatus) < 0) {
    warnings.push('Email status is "' + draft.emailStatus + '"; the sender will refuse unverified addresses.');
  }
  if (draft.qualificationStatus && draft.qualificationStatus !== LEAD_QUALIFIED) {
    warnings.push('Lead is "' + draft.qualificationStatus + '", not qualified; the sender will refuse it.');
  }
  if (draft.channel === 'whatsapp') {
    warnings.push('WhatsApp first contact also needs an approved template on the sending side.');
  }
  return warnings;
}

/** Pending drafts, newest first. Rows are {rowNumber, values} objects. */
function pendingDrafts(header, rows, leadLookup) {
  var drafts = [];
  for (var i = 0; i < rows.length; i++) {
    var view = draftView(header, rows[i].values, rows[i].rowNumber, leadLookup[textOf(rows[i].values[headerIndex(header, 'lead_id')])]);
    if (!view.draftId || !view.channel || view.status !== APPROVAL_PENDING) {
      continue;
    }
    drafts.push(view);
  }
  drafts.sort(function (a, b) {
    if (a.createdAt === b.createdAt) {
      return a.rowNumber - b.rowNumber;
    }
    return a.createdAt < b.createdAt ? 1 : -1;
  });
  return drafts;
}

/** Names from `names` that the sheet header is missing. */
function missingColumns(header, names) {
  var missing = [];
  for (var i = 0; i < names.length; i++) {
    if (headerIndex(header, names[i]) < 0) {
      missing.push(names[i]);
    }
  }
  return missing;
}

/**
 * Why this decision is not allowed, or '' when it may proceed.
 * Mirrors the Python approval gate for everything the sheet knows about: the
 * configured owner, draft state, verified email and lead qualification.
 */
function decisionBlocker(draft, ownerEmail, activeUserEmail) {
  var owner = textOf(ownerEmail).toLowerCase();
  var active = textOf(activeUserEmail).toLowerCase();
  if (!owner) {
    return 'Set your owner email in Settings before approving anything.';
  }
  if (active && active !== owner) {
    return 'Signed in as ' + active + ', which is not the configured owner (' + owner + ').';
  }
  if (!draft || !draft.draftId) {
    return 'This row has no draft_id.';
  }
  if (draft.status !== APPROVAL_PENDING) {
    return 'This draft is no longer pending (status: ' + (draft.status || 'empty') + '). Refresh the list.';
  }
  if (!draft.body) {
    return 'The draft body is empty.';
  }
  if (!draft.hasRecipient) {
    return 'The draft has no recipient.';
  }
  if (draft.doNotContact) {
    return 'The lead is marked do-not-contact.';
  }
  if (draft.channel === 'email') {
    if (!draft.subject) {
      return 'The email draft has no subject.';
    }
    if (draft.emailStatus && EMAIL_SENDABLE_STATUSES.indexOf(draft.emailStatus) < 0) {
      return 'Email status is "' + draft.emailStatus + '"; only verified addresses can be approved.';
    }
    if (draft.qualificationStatus && draft.qualificationStatus !== LEAD_QUALIFIED) {
      return 'Lead qualification is "' + draft.qualificationStatus + '", not qualified.';
    }
    return '';
  }
  if (draft.channel === 'whatsapp') {
    return '';
  }
  return 'Unknown channel "' + (draft.channel || '') + '".';
}

/** Cell values to write for an approval/rejection decision. */
function decisionValues(decision, ownerEmail, timestamp, reason) {
  var owner = textOf(ownerEmail).toLowerCase();
  if (!owner) {
    return { ok: false, error: 'An owner email is required before a decision can be recorded.' };
  }
  if (decision !== 'approve' && decision !== 'reject') {
    return { ok: false, error: 'Unknown decision "' + decision + '".' };
  }
  var at = textOf(timestamp) || new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
  if (decision === 'approve') {
    return {
      ok: true,
      values: {
        approval_status: APPROVAL_APPROVED,
        approved_by: owner,
        approved_at: at,
        updated_at: at,
        failure_reason: ''
      }
    };
  }
  var note = textOf(reason) || DEFAULT_REJECT_REASON;
  if (note.length > 400) {
    note = note.slice(0, 400);
  }
  return {
    ok: true,
    values: {
      approval_status: APPROVAL_REJECTED,
      approved_by: owner,
      approved_at: at,
      updated_at: at,
      failure_reason: note
    }
  };
}

/** Short stable id for the Activity tab, derived from the decision itself. */
function activityEventId(draftId, decision, timestamp) {
  var text = textOf(draftId) + '|' + textOf(decision) + '|' + textOf(timestamp);
  var hash = 5381;
  for (var i = 0; i < text.length; i++) {
    hash = ((hash * 33) ^ text.charCodeAt(i)) >>> 0;
  }
  return 'act_' + hash.toString(16);
}

/** One Activity row aligned to the given header (JSON details, no PII). */
function activityRow(columns, event) {
  var byName = {
    event_id: event.eventId,
    timestamp: event.timestamp,
    event_type: event.eventType,
    status: event.status,
    lead_id: event.leadId,
    summary: event.summary,
    details: event.details ? JSON.stringify(event.details) : ''
  };
  var row = [];
  for (var i = 0; i < columns.length; i++) {
    var key = String(columns[i] || '').trim().toLowerCase().replace(/\s+/g, '_');
    row.push(Object.prototype.hasOwnProperty.call(byName, key) ? textOf(byName[key]) : '');
  }
  return row;
}

/** Human message for anything thrown across google.script.run. */
function errorMessage(error) {
  if (!error) {
    return 'Unknown error.';
  }
  if (typeof error === 'string') {
    return error;
  }
  return textOf(error.message) || String(error);
}
