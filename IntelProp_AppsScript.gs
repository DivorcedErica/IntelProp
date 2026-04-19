// ══════════════════════════════════════════════════════════════════
// IntelProp — Google Apps Script
// Version: 2.0 — Full read + write handler
// ══════════════════════════════════════════════════════════════════
//
// SETUP INSTRUCTIONS
// ──────────────────
// 1. Go to https://script.google.com
// 2. Create a new project (or open your existing IntelProp script)
// 3. Delete all existing code and paste this entire file
// 4. Click "Deploy" → "New deployment"
//    - Type: Web App
//    - Execute as: Me
//    - Who has access: Anyone
// 5. Click "Deploy" → copy the /exec URL
// 6. Paste that URL into index.html as APPS_SCRIPT_URL
//
// SHEET STRUCTURE (auto-created if missing)
// ─────────────────────────────────────────
// Clients               — investor profiles
// Client Communications — activity log
// Agents                — agent records
// Listings              — property listings (Agent Portal)
// Properties            — investor-linked properties
// market_benchmarks     — analytics benchmark data
// rent_benchmarks       — rent benchmark data
// liquidity_benchmarks  — liquidity data
// supply_benchmarks     — supply / demand data
// agent_verified_data   — agent-verified research
//
// ══════════════════════════════════════════════════════════════════

var SPREADSHEET_ID = '1A4e51pB7O6BxYrXDAaWH2ZvjxLIQjiq-a2WpuhSs9dc';

// Sheets allowed for reading via the API
var READABLE_SHEETS = [
  'Clients',
  'Client Communications',
  'Agents',
  'Listings',
  'Properties',
  'market_benchmarks',
  'rent_benchmarks',
  'liquidity_benchmarks',
  'supply_benchmarks',
  'agent_verified_data',
];

// Sheet headers — used when auto-creating a missing sheet
var SHEET_HEADERS = {
  'Clients': [
    'InvestorID','Name','Phone','Email','Status',
    'Created On','Last Contact','Client Type','Budget',
    'Locations','Property Types','Notes','Nationality','Source'
  ],
  'Client Communications': [
    'CommID','InvestorID','Date','Investor Name',
    'Type','Action','Property ID','Property Title','Note'
  ],
  'Agents': [
    'AgentID','Name','Firm','Phone','Email',
    'Commission %','Active','Notes','Added On'
  ],
  'Listings': [
    'ID','Developer','Title','Complex','Type','City','District',
    'Bedrooms','Area m²','Plot m²','Price','€/m²',
    'Delivery','Sea Dist km','Image URL','URL','Notes','Added On','Source Tag'
  ],
  'Properties': [
    'PropertyID','InvestorID','Developer','Title','Type','City',
    'District','Bedrooms','Total Area','Plot Size','Price',
    'Price/m²','Complex','Added At'
  ],
  'market_benchmarks': [
    'Category','City','District','Property Type','Metric',
    'Value','Unit','Period','Confidence',
    'Source Name','Source Tier','Date Added','Notes'
  ],
  'rent_benchmarks': [
    'Category','City','District','Property Type','Metric',
    'Value','Unit','Period','Confidence',
    'Source Name','Source Tier','Date Added','Notes'
  ],
  'liquidity_benchmarks': [
    'Category','City','District','Property Type','Metric',
    'Value','Unit','Period','Confidence',
    'Source Name','Source Tier','Date Added','Notes'
  ],
  'supply_benchmarks': [
    'Category','City','District','Property Type','Metric',
    'Value','Unit','Period','Confidence',
    'Source Name','Source Tier','Date Added','Notes'
  ],
  'agent_verified_data': [
    'Category','City','District','Property Type','Metric',
    'Value','Unit','Period','Confidence',
    'Source Name','Source Tier','Date Added','Notes'
  ],
};

// ── Utilities ─────────────────────────────────────────────────────

function getSpreadsheet() {
  return SpreadsheetApp.openById(SPREADSHEET_ID);
}

function getOrCreateSheet(ss, name) {
  var sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
    var headers = SHEET_HEADERS[name];
    if (headers && headers.length) {
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
      sheet.setFrozenRows(1);
      sheet.getRange(1, 1, 1, headers.length)
        .setFontWeight('bold')
        .setBackground('#f8f9fa');
    }
    Logger.log('[IntelProp] Created sheet: ' + name);
  }
  return sheet;
}

function jsonpResponse(callback, data) {
  var json = JSON.stringify(data);
  return ContentService
    .createTextOutput(callback + '(' + json + ')')
    .setMimeType(ContentService.MimeType.JAVASCRIPT);
}

// ══════════════════════════════════════════════════════════════════
// doGet — handles READ requests (JSONP)
// Called by: readSheetViaAppsScriptJSONP() in index.html
// URL format: ?action=read&sheet=Clients&callback=ipRead_xxx
// ══════════════════════════════════════════════════════════════════

function doGet(e) {
  var params   = (e && e.parameter) ? e.parameter : {};
  var action   = params.action   || '';
  var callback = params.callback || 'cb';

  Logger.log('[IntelProp:doGet] action=' + action + ' sheet=' + params.sheet);

  // ── Write request from syncViaJsonp (?data= GET param) ────────
  if (params.data) {
    try {
      var data = JSON.parse(decodeURIComponent(params.data));
      handleWrite(data);
    } catch(err) {
      Logger.log('[IntelProp:write] Parse error: ' + err.message);
    }
    return ContentService
      .createTextOutput('')
      .setMimeType(ContentService.MimeType.TEXT);
  }

  // ── Read request ──────────────────────────────────────────────
  if (action === 'read') {
    var sheetName = params.sheet || '';

    if (!sheetName || READABLE_SHEETS.indexOf(sheetName) === -1) {
      return jsonpResponse(callback, {
        success: false,
        error: 'Sheet "' + sheetName + '" is not in the readable list'
      });
    }

    try {
      var ss    = getSpreadsheet();
      var sheet = getOrCreateSheet(ss, sheetName);
      var vals  = sheet.getDataRange().getValues();

      var sanitised = (vals.length > 1 ? vals.slice(1) : []).map(function(row) {
        return row.map(function(cell) {
          if (cell instanceof Date) return Utilities.formatDate(cell, 'UTC', "yyyy-MM-dd'T'HH:mm:ss'Z'");
          if (cell === null || cell === undefined) return '';
          return String(cell);
        });
      }).filter(function(row) {
        return row.some(function(cell) { return cell !== ''; });
      });

      Logger.log('[IntelProp:read] ' + sheetName + ' → ' + sanitised.length + ' rows');

      return jsonpResponse(callback, {
        success: true,
        sheet:   sheetName,
        rows:    sanitised,
        count:   sanitised.length,
      });

    } catch(err) {
      Logger.log('[IntelProp:read] ERROR: ' + err.message);
      return jsonpResponse(callback, { success: false, error: err.message });
    }
  }

  // ── Health check ──────────────────────────────────────────────
  return ContentService
    .createTextOutput(JSON.stringify({ status: 'ok', version: '2.0', actions: ['read'] }))
    .setMimeType(ContentService.MimeType.JSON);
}

// ══════════════════════════════════════════════════════════════════
// doPost — handles WRITE requests
// ══════════════════════════════════════════════════════════════════

function doPost(e) {
  return handleWrite(e && e.postData ? JSON.parse(e.postData.contents) : {});
}

function handleWrite(data) {
  if (!data || !data.sheet || !data.row) {
    Logger.log('[IntelProp:write] Invalid data: ' + JSON.stringify(data));
    return;
  }

  var sheetName = data.sheet;
  var row       = data.row;
  var type      = data.type || '';

  Logger.log('[IntelProp:write] type=' + type + ' sheet=' + sheetName);

  try {
    var ss    = getSpreadsheet();
    var sheet = getOrCreateSheet(ss, sheetName);

    var keyCol   = -1;
    var keyValue = null;

    if (type === 'investor'      && data.investorId)  { keyCol = 0; keyValue = String(data.investorId); }
    else if (type === 'communication' && data.commId)  { keyCol = 0; keyValue = String(data.commId); }
    else if (type === 'agent'    && data.agentId)      { keyCol = 0; keyValue = String(data.agentId); }
    else if (type === 'property' && data.propertyId)   { keyCol = 0; keyValue = String(data.propertyId); }
    // listings and benchmarks always append

    if (keyCol >= 0 && keyValue) {
      var allData  = sheet.getDataRange().getValues();
      var foundRow = -1;
      for (var i = 1; i < allData.length; i++) {
        if (String(allData[i][keyCol]) === keyValue) { foundRow = i + 1; break; }
      }
      if (foundRow > 0) {
        sheet.getRange(foundRow, 1, 1, row.length).setValues([row]);
        Logger.log('[IntelProp:write] Updated row ' + foundRow + ' in ' + sheetName);
        return;
      }
    }

    sheet.appendRow(row);
    Logger.log('[IntelProp:write] Appended to ' + sheetName);

  } catch(err) {
    Logger.log('[IntelProp:write] ERROR in ' + sheetName + ': ' + err.message);
  }
}

// ══════════════════════════════════════════════════════════════════
// TEST FUNCTION — run this manually to verify everything works
// In Apps Script editor: select testSetup → Run
// ══════════════════════════════════════════════════════════════════

function testSetup() {
  Logger.log('=== IntelProp Apps Script Test ===');

  var ss = getSpreadsheet();
  Logger.log('Spreadsheet: ' + ss.getName());

  READABLE_SHEETS.forEach(function(name) {
    var sheet = getOrCreateSheet(ss, name);
    Logger.log('Sheet OK: ' + name + ' (' + sheet.getLastRow() + ' rows)');
  });

  var clientSheet = ss.getSheetByName('Clients');
  var rows = clientSheet.getDataRange().getValues();
  Logger.log('Clients sheet: ' + rows.length + ' rows (including header)');
  if (rows.length > 1) {
    Logger.log('First data row: ' + JSON.stringify(rows[1]));
  }

  Logger.log('=== Test complete — check Execution Log above ===');
}
