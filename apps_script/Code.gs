/**
 * GenieAgent approval sidebar - spreadsheet bindings.
 *
 * Container-bound Apps Script for the GenieAgent CRM spreadsheet. It reads the
 * Outreach tab, writes owner approval/rejection decisions, and appends a line to
 * the Activity tab. It never sends email or WhatsApp messages and never calls an
 * external API: delivery belongs to scripts/pipeline_send.py, which re-checks
 * every gate itself.
 *
 * Setup: see apps_script/README.md.
 */

var OWNER_EMAIL_PROP = 'GENIE_OWNER_EMAIL';
var OUTREACH_SHEET_PROP = 'GENIE_OUTREACH_SHEET';
var LEADS_SHEET_PROP = 'GENIE_LEADS_SHEET';
var ACTIVITY_SHEET_PROP = 'GENIE_ACTIVITY_SHEET';
var DEFAULT_OUTREACH_SHEET = 'Outreach';
var DEFAULT_LEADS_SHEET = 'Leads';
var DEFAULT_ACTIVITY_SHEET = 'Activity';
var SIDEBAR_TITLE = 'GenieAgent approvals';

/** Sidebar needs these Outreach columns to review or record a decision. */
var REVIEW_COLUMNS = [
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

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('GenieAgent')
    .addItem('Review pending drafts', 'showSidebar')
    .addItem('Check sheet setup', 'showSetupReport')
    .addToUi();
}

function showSidebar() {
  var html = HtmlService.createTemplateFromFile('Sidebar')
    .evaluate()
    .setTitle(SIDEBAR_TITLE)
    .setWidth(420);
  SpreadsheetApp.getUi().showSidebar(html);
}

function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}

/* --------------------------------------------------------------- context */

function getSpreadsheet_() {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  if (!spreadsheet) {
    throw new Error('Open this sidebar from the GenieAgent CRM spreadsheet (Extensions > Apps Script).');
  }
  return spreadsheet;
}

function property_(name, fallback) {
  var value = textOf(PropertiesService.getScriptProperties().getProperty(name));
  return value || fallback;
}

function findSheet_(nameHint, keyColumn) {
  var spreadsheet = getSpreadsheet_();
  var named = nameHint ? spreadsheet.getSheetByName(nameHint) : null;
  if (named) {
    return named;
  }
  var sheets = spreadsheet.getSheets();
  for (var i = 0; i < sheets.length; i++) {
    var values = sheets[i].getDataRange().getValues();
    if (!values.length) {
      continue;
    }
    var header = values[0].map(textOf);
    if (headerIndex(header, keyColumn) >= 0) {
      return sheets[i];
    }
  }
  return null;
}

function readTable_(sheet) {
  var values = sheet.getDataRange().getValues();
  if (!values.length) {
    return { header: [], rows: [] };
  }
  var header = values[0].map(textOf);
  var rows = [];
  for (var i = 1; i < values.length; i++) {
    var row = values[i];
    var blank = true;
    for (var j = 0; j < row.length; j++) {
      if (textOf(row[j])) {
        blank = false;
        break;
      }
    }
    if (!blank) {
      rows.push({ rowNumber: i + 1, values: row });
    }
  }
  return { header: header, rows: rows };
}

function nowIso_() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function activeUserEmail_() {
  try {
    var email = textOf(Session.getActiveUser().getEmail());
    if (email) {
      return email.toLowerCase();
    }
  } catch (err) {
    // Fall through to the effective user; some consumer accounts hide both.
  }
  try {
    return textOf(Session.getEffectiveUser().getEmail()).toLowerCase();
  } catch (err) {
    return '';
  }
}

function readState_() {
  var spreadsheet = getSpreadsheet_();
  var outc = findSheet_(property_(OUTREACH_SHEET_PROP, DEFAULT_OUTREACH_SHEET), 'draft_id');
  var leadsSheet = findSheet_(property_(LEADS_SHEET_PROP, DEFAULT_LEADS_SHEET), 'lead_id');
  var activitySheet = findSheet_(property_(ACTIVITY_SHEET_PROP, DEFAULT_ACTIVITY_SHEET), 'event_id');
  var outreachTable = outc ? readTable_(outc) : { header: [], rows: [] };
  return {
    spreadsheetName: spreadsheet.getName(),
    ownerEmail: property_(OWNER_EMAIL_PROP, '').toLowerCase(),
    activeUserEmail: activeUserEmail_(),
    outreachSheetName: outc ? outc.getName() : '',
    leadsSheetName: leadsSheet ? leadsSheet.getName() : '',
    activitySheetName: activitySheet ? activitySheet.getName() : '',
    outreachFound: !!outc,
    leadsFound: !!leadsSheet,
    activityFound: !!activitySheet,
    pendingVisible:
      outreachTable.header.length && headerIndex(outreachTable.header, 'approval_status') >= 0
        ? outreachTable.rows.filter(function (row) {
            return textOf(row.values[headerIndex(outreachTable.header, 'approval_status')]).toLowerCase() === APPROVAL_PENDING;
          }).length
        : 0,
    missingColumns: outreachTable.header.length ? missingColumns(outreachTable.header, REVIEW_COLUMNS) : REVIEW_COLUMNS.slice(),
    sheets: spreadsheet.getSheets().map(function (sheet) {
      return sheet.getName();
    })
  };
}

/* ---------------------------------------------------------------- review */

/** Everything the sidebar needs to render, in one call. */
function loadApprovalState() {
  try {
    var state = readState_();
    if (!state.outreachFound) {
      return {
        ok: false,
        error: 'No tab with a draft_id header was found. Run the pipeline once so it can create the Outreach tab.',
        state: state,
        drafts: []
      };
    }
    if (state.missingColumns.length) {
      return {
        ok: false,
        error: 'The Outreach tab is missing column(s): ' + state.missingColumns.join(', ') + '. Run pipeline_sync.py to repair the header.',
        state: state,
        drafts: []
      };
    }
    var outreachSheet = findSheet_(property_(OUTREACH_SHEET_PROP, DEFAULT_OUTREACH_SHEET), 'draft_id');
    var outreach = readTable_(outreachSheet);
    var leadLookup = {};
    var leadsSheet = findSheet_(property_(LEADS_SHEET_PROP, DEFAULT_LEADS_SHEET), 'lead_id');
    if (leadsSheet) {
      var leads = readTable_(leadsSheet);
      leadLookup = buildLeadLookup(
        leads.header,
        leads.rows.map(function (row) {
          return row.values;
        })
      );
    }
    return { ok: true, state: state, drafts: pendingDrafts(outreach.header, outreach.rows, leadLookup) };
  } catch (error) {
    return { ok: false, error: errorMessage(error), state: null, drafts: [] };
  }
}

function approveDraft(draftId) {
  return decide_(draftId, 'approve', '');
}

function rejectDraft(draftId, reason) {
  return decide_(draftId, 'reject', reason);
}

/**
 * Record one decision. Guarded by a document lock, re-reads the row so a stale
 * sidebar cannot approve something that was already decided or sent, and never
 * touches any column other than the decision columns.
 */
function decide_(draftId, decision, reason) {
  var lock = LockService.getDocumentLock();
  if (!lock.tryLock(20000)) {
    return { ok: false, error: 'The spreadsheet is busy. Try again in a moment.' };
  }
  try {
    var wanted = textOf(draftId);
    if (!wanted) {
      return { ok: false, error: 'No draft was selected.' };
    }
    var state = readState_();
    if (!state.ownerEmail) {
      return { ok: false, error: 'Set your owner email in Settings before recording a decision.', needsOwner: true };
    }
    if (!state.outreachFound) {
      return { ok: false, error: 'No Outreach tab with a draft_id header was found.' };
    }
    var outreachSheet = findSheet_(property_(OUTREACH_SHEET_PROP, DEFAULT_OUTREACH_SHEET), 'draft_id');
    var table = readTable_(outreachSheet);
    var missing = missingColumns(table.header, REVIEW_COLUMNS.concat(DECISION_COLUMNS));
    if (missing.length) {
      return { ok: false, error: 'The Outreach tab is missing column(s): ' + missing.join(', ') + '.' };
    }

    var draftIndex = headerIndex(table.header, 'draft_id');
    var target = null;
    for (var i = 0; i < table.rows.length; i++) {
      if (textOf(table.rows[i].values[draftIndex]) === wanted) {
        target = table.rows[i];
        break;
      }
    }
    if (!target) {
      return { ok: false, error: 'Draft ' + wanted + ' is no longer in the Outreach tab. Refresh the list.', refresh: true };
    }

    var leadLookup = {};
    var leadsSheet = findSheet_(property_(LEADS_SHEET_PROP, DEFAULT_LEADS_SHEET), 'lead_id');
    if (leadsSheet) {
      var leads = readTable_(leadsSheet);
      leadLookup = buildLeadLookup(
        leads.header,
        leads.rows.map(function (row) {
          return row.values;
        })
      );
    }
    var leadId = cellOf(table.header, target.values, 'lead_id');
    var view = draftView(table.header, target.values, target.rowNumber, leadLookup[leadId]);
    var blocker = decisionBlocker(view, state.ownerEmail, state.activeUserEmail);
    if (blocker) {
      return { ok: false, error: blocker, refresh: true };
    }

    var built = decisionValues(decision, state.ownerEmail, nowIso_(), reason);
    if (!built.ok) {
      return { ok: false, error: built.error };
    }
    Object.keys(built.values).forEach(function (column) {
      var index = headerIndex(table.header, column);
      if (index >= 0) {
        outreachSheet.getRange(target.rowNumber, index + 1).setValue(built.values[column]);
      }
    });
    SpreadsheetApp.flush();

    var logged = appendActivity_(state, view, decision, built.values);
    return {
      ok: true,
      draftId: view.draftId,
      status: built.values.approval_status,
      decidedAt: built.values.approved_at,
      activityLogged: logged,
      message:
        decision === 'approve'
          ? 'Approved. Nothing was sent; run pipeline_send.py --execute when you are ready.'
          : 'Rejected and recorded in the sheet.'
    };
  } catch (error) {
    return { ok: false, error: errorMessage(error) };
  } finally {
    lock.releaseLock();
  }
}

/** Append one line to Activity. Missing tab is reported, never fatal. */
function appendActivity_(state, draft, decision, values) {
  try {
    var activitySheet = findSheet_(property_(ACTIVITY_SHEET_PROP, DEFAULT_ACTIVITY_SHEET), 'event_id');
    if (!activitySheet) {
      activitySheet = getSpreadsheet_().insertSheet(property_(ACTIVITY_SHEET_PROP, DEFAULT_ACTIVITY_SHEET));
      activitySheet.getRange(1, 1, 1, ACTIVITY_HEADERS.length).setValues([ACTIVITY_HEADERS]);
    }
    var table = readTable_(activitySheet);
    var header = table.header.length ? table.header : ACTIVITY_HEADERS.slice();
    var timestamp = values.approved_at;
    var row = activityRow(header, {
      eventId: activityEventId(draft.draftId, decision, timestamp),
      timestamp: timestamp,
      eventType: decision === 'approve' ? 'draft_approved' : 'draft_rejected',
      status: 'ok',
      leadId: draft.leadId,
      summary: decision === 'approve' ? 'Owner approved one draft in the sidebar' : 'Owner rejected one draft in the sidebar',
      details: {
        draft_id: draft.draftId,
        channel: draft.channel,
        approval_status: values.approval_status,
        reason: decision === 'reject' ? values.failure_reason : '',
        source: 'apps_script_sidebar'
      }
    });
    activitySheet.appendRow(row);
    return true;
  } catch (error) {
    return false;
  }
}

/* -------------------------------------------------------------- settings */

function saveOwnerEmail(email) {
  try {
    var value = textOf(email).toLowerCase();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(value)) {
      return { ok: false, error: 'Enter a valid email address, e.g. owner@example.com.' };
    }
    PropertiesService.getScriptProperties().setProperty(OWNER_EMAIL_PROP, value);
    return {
      ok: true,
      message: 'Owner email saved. It must match GENIE_OWNER_EMAIL in .env or the sender will refuse these approvals.',
      state: readState_()
    };
  } catch (error) {
    return { ok: false, error: errorMessage(error) };
  }
}

function showSetupReport() {
  var lines = [];
  try {
    var state = readState_();
    lines.push('Spreadsheet: ' + state.spreadsheetName);
    lines.push('Owner email: ' + (state.ownerEmail || 'not set'));
    lines.push('Signed in as: ' + (state.activeUserEmail || 'unknown'));
    lines.push('Outreach tab: ' + (state.outreachSheetName || 'not found'));
    lines.push('Leads tab: ' + (state.leadsSheetName || 'not found'));
    lines.push('Activity tab: ' + (state.activitySheetName || 'not found'));
    lines.push('Pending drafts: ' + state.pendingVisible);
    if (state.missingColumns.length) {
      lines.push('Missing Outreach columns: ' + state.missingColumns.join(', '));
      lines.push('Run: python scripts/pipeline_sync.py --direction push');
    }
    if (state.ownerEmail && state.activeUserEmail && state.ownerEmail !== state.activeUserEmail) {
      lines.push('Warning: this account is not the configured owner, so approvals are blocked.');
    }
    lines.push('');
    lines.push('This sidebar only records decisions. Sending stays with pipeline_send.py.');
  } catch (error) {
    lines.push('Setup check failed: ' + errorMessage(error));
  }
  SpreadsheetApp.getUi().alert('GenieAgent setup', lines.join('\n'), SpreadsheetApp.getUi().ButtonSet.OK);
}
