// Diagnostic projections only; assertions always use the original full snapshot.
export function snapshotPreview(value, budget = 16000) {
  let truncated = false;
  const trim = (item, remaining) => {
    if (JSON.stringify(item).length <= remaining) return item;
    truncated = true;
    if (remaining < 120) return '<omitted from diagnostic snapshot>';
    if (item && typeof item === 'object') {
      const entries = Object.entries(item).slice(0, 24);
      const output = entries.map(([key, child]) => [key, trim(child, Math.max(0, Math.floor(remaining / entries.length) - key.length - 8))]);
      return Array.isArray(item) ? output.map(([, child]) => child) : Object.fromEntries(output);
    }
    return String(item).slice(0, remaining - 4) + '…';
  };
  return {snapshot: trim(value, budget), snapshot_truncated: truncated};
}

export function createInputEvidence(write, requestHash) {
  const data = {schema_version: 1, request_sha256: requestHash, dropped_records: 0, records: []};
  const persist = () => {
    let text = JSON.stringify(data);
    while (Buffer.byteLength(text) > 2000000 && data.records.length > 1) {
      data.records.shift(); data.dropped_records++; text = JSON.stringify(data);
    }
    write(text);
  };
  return {
    begin(context, action, before) {
      const entry = {...context, action, status: 'running', before: snapshotPreview(before)};
      data.records.push(entry); persist(); return entry;
    },
    finish(entry, snapshot, input, error) {
      if (!entry) return;
      Object.assign(entry, snapshot === undefined ? {} : snapshotPreview(snapshot),
        {status: error ? 'failed' : 'completed', input: input ?? null},
        error ? {error: String(error.message).slice(0, 1000), touch_reachability: error.touch_scroll ?? null} : {});
      persist();
    },
  };
}
