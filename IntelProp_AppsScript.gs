function doGet(e) {
  var params = e && e.parameter ? e.parameter : {};

  // ── READ handler ────────────────────────────────────────────────────────────
  if (params.action === 'read') {
    var cb = params.callback || 'cb';
    try {
      var ss    = SpreadsheetApp.openById('1A4e51pB7O6BxYrXDAaWH2ZvjxLIQjiq-a2WpuhSs9dc');
      var sheet = ss.getSheetByName(params.sheet);
      if (!sheet) {
        return ContentService
          .createTextOutput(cb + '({"error":"Sheet not found"})')
          .setMimeType(ContentService.MimeType.JAVASCRIPT);
      }
      var vals = sheet.getDataRange().getValues();
      var rows = vals.slice(1).map(function(r) {
        return r.map(function(c) {
          if (c instanceof Date) return c.toISOString();
          return c === null || c === undefined ? '' : String(c);
        });
      }).filter(function(r) {
        return r.some(function(c) { return c !== ''; });
      });
      return ContentService
        .createTextOutput(cb + '(' + JSON.stringify({rows: rows}) + ')')
        .setMimeType(ContentService.MimeType.JAVASCRIPT);
    } catch(err) {
      return ContentService
        .createTextOutput(cb + '({"error":"' + err.message + '"})')
        .setMimeType(ContentService.MimeType.JAVASCRIPT);
    }
  }

  // ── Existing doGet / doPost write logic goes below ──────────────────────────
}
