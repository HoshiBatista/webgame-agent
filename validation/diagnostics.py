"""Bounded read-only game-frame diagnostics. No host data or DOM serialization."""

import json

MAX_BYTES = 8192
DOM = r"""() => {
 let omitted = false;
 const short = value => {
   const text = String(value || '');
   if (text.length > 200) omitted = true;
   return text.slice(0, 200);
 };
 const rows = [];
 const all = document.querySelectorAll('button,input,[role=button],canvas,[tabindex]');
 for (const e of all) {
   const r = e.getBoundingClientRect();
   if (!r.width || !r.height) continue;
   if (rows.length >= 16) { omitted = true; break; }
   const id = short(e.getAttribute('id'));
   let selector = null;
   if (id && id === e.getAttribute('id')) {
     const candidate = '#' + CSS.escape(id);
     const matches = document.querySelectorAll(candidate);
     if (candidate.length > 200) omitted = true;
     else if (matches.length === 1 && matches[0] === e) selector = candidate;
   }
   rows.push({tag:e.tagName.toLowerCase(),id,selector,role:short(e.getAttribute('role')),
     label:short(e.getAttribute('aria-label')),text:short(e.textContent),
     rect:{x:r.x,y:r.y,width:r.width,height:r.height}});
 }
 return {viewport:{width:innerWidth,height:innerHeight},controls:rows,truncated:omitted};
}"""


def bounded(value, maximum=MAX_BYTES):
    truncated = False

    def clean(item, depth=0):
        nonlocal truncated
        if depth > 5:
            truncated = True
            return "[depth limit]"
        if isinstance(item, str):
            truncated |= len(item) > 200
            return item[:200]
        if item is None or type(item) in {bool, int, float}:
            return item
        if isinstance(item, dict):
            truncated |= len(item) > 20 or any(len(str(k)) > 80 for k in item)
            return {str(k)[:80]: clean(v, depth + 1) for k, v in list(item.items())[:20]}
        if isinstance(item, list):
            truncated |= len(item) > 16
            return [clean(v, depth + 1) for v in item[:16]]
        truncated = True
        return "[unsupported]"
    result = clean(value)
    if truncated:
        result["truncated"] = True
    while len(json.dumps(result, ensure_ascii=False).encode()) > maximum:
        # Remove whole fields; output is always structured, valid JSON.
        keys = [k for k in result if k != "truncated"]
        if not keys:
            break
        largest = max(keys, key=lambda k: len(json.dumps(result[k], ensure_ascii=False).encode()))
        del result[largest]
        result["truncated"] = True
    return result


def collect(frame, check, step_index, before, after, state_script):
    result = {"check_id": check.get("id"), "step_index": step_index,
              "step": (check.get("steps") or [])[step_index] if step_index is not None else None,
              "observation": check.get("observation"), "before": before, "after": after,
              "expected": check.get("expect"), "actual_type": type(after).__name__}
    if frame is None:
        return bounded({**result, "unavailable": True})
    try:
        result.update(frame.evaluate(DOM))
        observation = check.get("observation") or {}
        if observation.get("source") == "state":
            # Reuse the descriptor-based safe reader; never enumerate window.
            value = frame.evaluate(state_script, observation.get("path", ""))
            result["state"] = value
            if "value" in value:
                result["actual_type"] = type(value["value"]).__name__
        elif observation.get("selector"):
            locator = frame.locator(observation["selector"])
            result["selector_matches"] = locator.count()
    except Exception:
        result["unavailable"] = True
    return bounded(result)
