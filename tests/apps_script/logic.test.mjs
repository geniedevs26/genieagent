// Offline unit tests for apps_script/Logic.gs (no Apps Script runtime needed).
// Run directly: node tests/apps_script/logic.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(here, '..', '..', 'apps_script', 'Logic.gs'), 'utf8');

const exported = [
  'textOf',
  'headerIndex',
  'cellOf',
  'maskEmail',
  'maskPhone',
  'maskRecipient',
  'buildLeadLookup',
  'draftView',
  'pendingDrafts',
  'missingColumns',
  'decisionBlocker',
  'decisionValues',
  'activityEventId',
  'activityRow',
  'errorMessage',
  'ACTIVITY_HEADERS',
  'OUTREACH_HEADERS',
  'LEAD_HEADERS',
  'APPROVAL_PENDING',
  'APPROVAL_APPROVED',
  'APPROVAL_REJECTED',
  'EMAIL_SENDABLE_STATUSES',
  'LEAD_QUALIFIED'
];
const L = new Function(source + '\nreturn {' + exported.join(',') + '};')();

const tests = [];
function test(name, fn) {
  tests.push({ name, fn });
}

const header = [
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
  'delivery_status',
  'failure_reason',
  'follow_up_of',
  'created_at',
  'updated_at'
];

const leadHeader = [
  'lead_id',
  'company_name',
  'email_status',
  'qualification_status',
  'qualification_score',
  'do_not_contact'
];

function draftRow(overrides) {
  const row = {
    draft_id: 'draft_1',
    lead_id: 'lead_1',
    channel: 'email',
    provider: 'brevo',
    recipient: 'jane.doe@acme.example',
    recipient_masked: '',
    subject: 'Quick question about Acme logistics',
    body: 'Hello Jane,\n\nSaw your note about route planning.\n',
    approval_status: 'pending_owner_approval',
    approved_by: '',
    approved_at: '',
    sent_at: '',
    delivery_status: 'not_sent',
    failure_reason: '',
    follow_up_of: '',
    created_at: '2026-11-01T09:00:00Z',
    updated_at: '2026-11-01T09:00:00Z'
  };
  Object.assign(row, overrides || {});
  return header.map((name) => row[name]);
}

function leadRow(overrides) {
  const row = {
    lead_id: 'lead_1',
    company_name: 'Acme Logistics',
    email_status: 'valid',
    qualification_status: 'qualified',
    qualification_score: '82',
    do_not_contact: 'false'
  };
  Object.assign(row, overrides || {});
  return leadHeader.map((name) => row[name]);
}

const leadLookup = L.buildLeadLookup(leadHeader, [leadRow()]);
const qualifiedDraft = L.draftView(header, draftRow(), 2, leadLookup.lead_1);

test('textOf trims strings, blanks nullish values and normalises dates', () => {
  assert.equal(L.textOf('  x  '), 'x');
  assert.equal(L.textOf(null), '');
  assert.equal(L.textOf(undefined), '');
  assert.equal(L.textOf(new Date('2026-11-06T10:00:00.123Z')), '2026-11-06T10:00:00Z');
});

test('headerIndex matches names case-insensitively and ignores spacing style', () => {
  assert.equal(L.headerIndex(header, 'draft_id'), 0);
  assert.equal(L.headerIndex(header, 'Draft Id'), 0);
  assert.equal(L.headerIndex(header, '  approval_status '), 8);
  assert.equal(L.headerIndex(header, 'nonexistent'), -1);
  assert.equal(L.headerIndex([], 'anything'), -1);
});

test('masking never reveals the full address or number', () => {
  assert.equal(L.maskEmail('jane.doe@acme.example'), 'j******@acme.example');
  assert.equal(L.maskEmail('a@b.co'), 'a**@b.co');
  assert.equal(L.maskEmail('not-an-email'), '');
  assert.equal(L.maskPhone('+1 (555) 123-4567'), '*********67');
  assert.equal(L.maskPhone('12'), 'hidden');
  assert.equal(L.maskRecipient('email', 'jane.doe@acme.example'), 'j******@acme.example');
  assert.equal(L.maskRecipient('whatsapp', '+1 (555) 123-4567'), '*********67');
});

test('lead lookup exposes only review context', () => {
  assert.equal(leadLookup.lead_1.company, 'Acme Logistics');
  assert.equal(leadLookup.lead_1.qualificationStatus, 'qualified');
  assert.equal(leadLookup.lead_1.doNotContact, false);
  assert.equal(L.buildLeadLookup([], []).lead_1, undefined);
});

test('draftView maps a row and falls back to a masked recipient', () => {
  assert.equal(qualifiedDraft.draftId, 'draft_1');
  assert.equal(qualifiedDraft.channel, 'email');
  assert.equal(qualifiedDraft.recipientMasked, 'j******@acme.example');
  assert.equal(qualifiedDraft.hasRecipient, true);
  assert.equal(qualifiedDraft.company, 'Acme Logistics');
  assert.equal(qualifiedDraft.qualificationScore, '82');
  assert.equal(qualifiedDraft.status, 'pending_owner_approval');
  assert.deepEqual(qualifiedDraft.warnings, []);
  assert.equal('recipient' in qualifiedDraft, false);
});

test('draftView explains why a draft looks risky', () => {
  const unverified = L.draftView(header, draftRow({ approval_status: 'approved' }), 2, {
    company: 'Acme',
    emailStatus: 'risky',
    qualificationStatus: 'rejected',
    doNotContact: true
  });
  assert.ok(unverified.warnings.some((text) => text.includes('risky')));
  assert.ok(unverified.warnings.some((text) => text.includes('not qualified')));
  assert.equal(L.draftView(header, draftRow(), 2, undefined).leadFound, false);
  const whatsapp = L.draftView(header, draftRow({ channel: 'whatsapp', recipient: '+15551234567' }), 2, leadLookup.lead_1);
  assert.ok(whatsapp.warnings.some((text) => text.includes('template')));
});

test('pendingDrafts keeps only pending rows, newest first', () => {
  const rows = [
    { rowNumber: 2, values: draftRow({ draft_id: 'old', created_at: '2026-11-01T09:00:00Z' }) },
    { rowNumber: 3, values: draftRow({ draft_id: 'new', created_at: '2026-11-05T09:00:00Z' }) },
    { rowNumber: 4, values: draftRow({ draft_id: 'done', approval_status: 'approved' }) },
    { rowNumber: 5, values: draftRow({ draft_id: 'blank', channel: '' }) }
  ];
  const drafts = L.pendingDrafts(header, rows, leadLookup);
  assert.deepEqual(drafts.map((draft) => draft.draftId), ['new', 'old']);
  assert.deepEqual(
    drafts.map((draft) => draft.rowNumber),
    [3, 2]
  );
});

test('missingColumns reports every absent review column', () => {
  assert.deepEqual(L.missingColumns(header, ['draft_id', 'body']), []);
  assert.deepEqual(L.missingColumns(['draft_id'], ['draft_id', 'body', 'approved_at']), ['body', 'approved_at']);
});

test('decisionBlocker requires a configured owner and the matching account', () => {
  assert.match(L.decisionBlocker(qualifiedDraft, '', ''), /owner email/i);
  assert.match(L.decisionBlocker(qualifiedDraft, 'owner@example.com', 'someone@else.com'), /not the configured owner/i);
  assert.equal(L.decisionBlocker(qualifiedDraft, 'owner@example.com', ''), '');
  assert.equal(L.decisionBlocker(qualifiedDraft, 'owner@example.com', 'OWNER@example.com'), '');
});

test('decisionBlocker refuses stale, incomplete and unsafe drafts', () => {
  const approved = Object.assign({}, qualifiedDraft, { status: 'approved' });
  assert.match(L.decisionBlocker(approved, 'owner@example.com', ''), /no longer pending/i);

  const sent = Object.assign({}, qualifiedDraft, { status: 'sent' });
  assert.match(L.decisionBlocker(sent, 'owner@example.com', ''), /no longer pending/i);

  assert.match(L.decisionBlocker(Object.assign({}, qualifiedDraft, { body: '' }), 'owner@example.com', ''), /body is empty/i);
  assert.match(
    L.decisionBlocker(Object.assign({}, qualifiedDraft, { hasRecipient: false }), 'owner@example.com', ''),
    /no recipient/i
  );
  assert.match(
    L.decisionBlocker(Object.assign({}, qualifiedDraft, { doNotContact: true }), 'owner@example.com', ''),
    /do-not-contact/i
  );
  assert.match(
    L.decisionBlocker(Object.assign({}, qualifiedDraft, { emailStatus: 'risky' }), 'owner@example.com', ''),
    /only verified addresses/i
  );
  assert.match(
    L.decisionBlocker(Object.assign({}, qualifiedDraft, { qualificationStatus: 'rejected' }), 'owner@example.com', ''),
    /not qualified/i
  );
  assert.match(
    L.decisionBlocker(Object.assign({}, qualifiedDraft, { channel: 'sms' }), 'owner@example.com', ''),
    /unknown channel/i
  );
});

test('decisionValues records the owner and timestamp, clearing old failures', () => {
  const approved = L.decisionValues('approve', 'Oversight@Example.com', '2026-11-06T12:00:00Z', 'ignored');
  assert.equal(approved.ok, true);
  assert.deepEqual(approved.values, {
    approval_status: 'approved',
    approved_by: 'oversight@example.com',
    approved_at: '2026-11-06T12:00:00Z',
    updated_at: '2026-11-06T12:00:00Z',
    failure_reason: ''
  });
  assert.equal(L.decisionValues('approve', '   ', '2026-11-06T12:00:00Z', '').ok, false);
  assert.equal(L.decisionValues('archive', 'o@e.com', '2026-11-06T12:00:00Z', '').ok, false);
});

test('rejection keeps a bounded reason and defaults when blank', () => {
  const blank = L.decisionValues('reject', 'owner@example.com', '2026-11-06T12:00:00Z', '   ');
  assert.equal(blank.values.approval_status, 'rejected');
  assert.equal(blank.values.failure_reason, 'Rejected by owner in the GenieAgent sidebar.');

  const long = L.decisionValues('reject', 'owner@example.com', '2026-11-06T12:00:00Z', 'x'.repeat(600));
  assert.equal(long.values.failure_reason.length, 400);
  const short = L.decisionValues('reject', 'owner@example.com', '2026-11-06T12:00:00Z', 'Out of scope');
  assert.equal(short.values.failure_reason, 'Out of scope');
});

test('activity rows align to the sheet header without leaking recipients', () => {
  const row = L.activityRow(L.ACTIVITY_HEADERS, {
    eventId: 'act_1',
    timestamp: '2026-11-06T12:00:00Z',
    eventType: 'draft_approved',
    status: 'ok',
    leadId: 'lead_1',
    summary: 'Owner approved one draft in the sidebar',
    details: { draft_id: 'draft_1', channel: 'email', source: 'apps_script_sidebar' }
  });
  assert.equal(row.length, L.ACTIVITY_HEADERS.length);
  assert.equal(row[0], 'act_1');
  assert.equal(row[2], 'draft_approved');
  assert.equal(row[1], '2026-11-06T12:00:00Z');
  assert.ok(row[6].includes('draft_1'));
  assert.ok(!row.join('|').includes('@'));

  const reordered = L.activityRow(['summary', 'event_id', 'extra'], { eventId: 'act_2', summary: 'x' });
  assert.deepEqual(reordered, ['x', 'act_2', '']);
});

test('activity ids are stable per decision yet differ between outcomes', () => {
  const first = L.activityEventId('draft_1', 'approve', '2026-11-06T12:00:00Z');
  assert.equal(first, L.activityEventId('draft_1', 'approve', '2026-11-06T12:00:00Z'));
  assert.notEqual(first, L.activityEventId('draft_1', 'reject', '2026-11-06T12:00:00Z'));
  assert.match(first, /^act_[0-9a-f]+$/);
});

test('header constants cover every column the pipeline writes', () => {
  assert.equal(L.OUTREACH_HEADERS.length, 19);
  assert.equal(L.LEAD_HEADERS.length, 50);
  assert.ok(L.LEAD_HEADERS.includes('verification_status'));
  assert.ok(L.LEAD_HEADERS.includes('verification_checked_at'));
  assert.deepEqual(L.ACTIVITY_HEADERS, ['event_id', 'timestamp', 'event_type', 'status', 'lead_id', 'summary', 'details']);
  assert.ok(L.OUTREACH_HEADERS.includes('approved_by'));
  assert.ok(L.LEAD_HEADERS.includes('consent_basis'));
});

test('errorMessage unwraps script errors', () => {
  assert.equal(L.errorMessage('plain'), 'plain');
  assert.equal(L.errorMessage({ message: 'boom' }), 'boom');
  assert.equal(L.errorMessage(null), 'Unknown error.');
});

let failed = 0;
for (const { name, fn } of tests) {
  try {
    fn();
    console.log('ok   ' + name);
  } catch (error) {
    failed += 1;
    console.error('FAIL ' + name);
    console.error(error);
  }
}
console.log('\n' + (tests.length - failed) + '/' + tests.length + ' Apps Script logic tests passed');
if (failed) {
  process.exit(1);
}
