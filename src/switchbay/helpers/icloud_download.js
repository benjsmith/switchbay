// Download-on-demand for one already-authorized iCloud item.
// Invoked as: /usr/bin/osascript -l JavaScript icloud_download.js <action> <path>
// Paths arrive only via argv — never interpolated into this source or a shell.
// Uses NSFileManager.startDownloadingUbiquitousItemAtURL:error: (public API).
// Does not evict, pin, or start a recursive/global iCloud sync.

ObjC.import("Foundation");

function unwrap(v) {
  if (v === undefined || v === null) return null;
  try {
    return ObjC.unwrap(v);
  } catch (e) {
    return String(v);
  }
}

function nsErrorInfo(errRef) {
  try {
    var err = errRef && errRef[0];
    if (!err || err.isNil && err.isNil()) return null;
    var desc = unwrap(err.localizedDescription);
    var domain = unwrap(err.domain);
    var code = err.code !== undefined ? Number(err.code) : null;
    return { description: desc, domain: domain, code: code };
  } catch (e) {
    return null;
  }
}

function probe(url, fm) {
  var ubiquitous = false;
  try {
    ubiquitous = !!fm.isUbiquitousItemAtURL(url);
  } catch (e) {
    ubiquitous = false;
  }
  var status = null;
  var downloading = null;
  try {
    var statusRef = Ref();
    var err = $();
    var ok = url.getResourceValueForKeyError(
      statusRef,
      $.NSURLUbiquitousItemDownloadingStatusKey,
      err
    );
    if (ok) status = unwrap(statusRef[0]);
  } catch (e) {
    status = null;
  }
  try {
    var downRef = Ref();
    var err2 = $();
    var ok2 = url.getResourceValueForKeyError(
      downRef,
      $.NSURLUbiquitousItemIsDownloadingKey,
      err2
    );
    if (ok2) downloading = !!unwrap(downRef[0]);
  } catch (e) {
    downloading = null;
  }
  return {
    ok: true,
    ubiquitous: ubiquitous,
    status: status,
    downloading: downloading,
  };
}

function run(argv) {
  var action = argv && argv.length ? String(argv[0] || "") : "";
  var path = argv && argv.length > 1 ? String(argv[1] || "") : "";
  if (!path) {
    return JSON.stringify({ ok: false, error: "path required" });
  }
  if (action !== "probe" && action !== "status" && action !== "start") {
    return JSON.stringify({ ok: false, error: "unknown action" });
  }
  var url = $.NSURL.fileURLWithPath(path);
  var fm = $.NSFileManager.defaultManager;
  if (action === "probe" || action === "status") {
    return JSON.stringify(probe(url, fm));
  }
  var err = $();
  var started = false;
  try {
    started = !!fm.startDownloadingUbiquitousItemAtURLError(url, err);
  } catch (e) {
    return JSON.stringify({
      ok: false,
      started: false,
      error: String(e),
    });
  }
  var info = nsErrorInfo(err);
  return JSON.stringify({
    ok: started,
    started: started,
    error: started ? null : (info && info.description) || "startDownloadingUbiquitousItem failed",
    ns_error: info,
  });
}
