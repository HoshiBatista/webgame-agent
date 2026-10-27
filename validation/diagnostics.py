"""Bounded read-only game-frame diagnostics. No host data or DOM serialization."""

import hashlib
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

INPUT_TARGET = r"""step => {
 const elements = document.querySelectorAll(step.selector);
 if (elements.length !== 1) return {status:'ambiguous',matches:elements.length};
 const target = elements[0], r = target.getBoundingClientRect();
 if (r.width <= 0 || r.height <= 0) return {status:'hidden'};
 const fraction = step.action.endsWith('_fraction');
 const x = r.x + (step.x == null ? r.width/2 : fraction ? r.width*step.x : step.x);
 const y = r.y + (step.y == null ? r.height/2 : fraction ? r.height*step.y : step.y);
 const hit = document.elementFromPoint(x,y);
 const describe = e => e ? {tag:e.tagName.toLowerCase(),id:(e.id||'').slice(0,100),
   label:(e.getAttribute('aria-label')||e.textContent||'').slice(0,120)} : null;
 return {status:hit && (hit===target || target.contains(hit))?'reachable':'obstructed',
   target:describe(target),hit:describe(hit),point:{x,y},
   rect:{x:r.x,y:r.y,width:r.width,height:r.height}};
}"""


STATE_CATALOG = r"""root => {
 const rows=[], skipped=[], seen=new WeakSet(); let nodes=128;
 const skip=(path,reason)=>{if(skipped.length<12)skipped.push({path:path.slice(0,200),reason});};
 const walk=(value,path,depth)=>{
   if(--nodes<0||depth>3||rows.length>=12){skip(path,'limit');return;}
   if(value===null||['boolean','number','string'].includes(typeof value)){
     if(typeof value==='number'&&!Number.isFinite(value)){skip(path,'nonfinite');return;}
     if(typeof value==='string'&&value.length>200){skip(path,'size');return;}
     rows.push({path,value});return;
   }
   if(!value||typeof value!=='object'||seen.has(value)){skip(path,'type');return;}
   const proto=Object.getPrototypeOf(value);
   if(proto!==Object.prototype&&proto!==Array.prototype&&proto!==null){skip(path,'prototype');return;}
   seen.add(value);
   const keys=Reflect.ownKeys(value);
   if(keys.length>16)skip(path,'keys_limit');
   for(const key of keys.slice(0,16)){
     if(typeof key!=='string'||!/^([a-zA-Z_$][\w$]*|[0-9]+)$/.test(key)||key==='length')continue;
     const child=path+'.'+key, d=Object.getOwnPropertyDescriptor(value,key);
     if(!d||!('value' in d)){skip(child,'accessor');continue;}
     walk(d.value,child,depth+1);
   }
 };
 try{
   const d=Object.getOwnPropertyDescriptor(window,root);
   if(!d)skip(root,'absent');
   else if(!('value' in d))skip(root,'accessor');
   else walk(d.value,root,0);
 }catch{skip(root,'unsafe');}
 return {rows,skipped};
}"""


def observation_catalog(frame, check, state_script, skipped=None):
    """Only inspect the requested plain-state root and bounded visible DOM facts."""
    rows = []

    def add(observation, value):
        if value is not None and type(value) not in {str, int, float, bool}:
            return
        identity = hashlib.sha256(json.dumps(observation, sort_keys=True).encode()).hexdigest()[:12]
        rows.append({"id": "obs_" + identity, "observation": observation,
                     "type": type(value).__name__, "value": value, "phase": "diagnostic_snapshot"})

    path = (check.get("observation") or {}).get("path", "")
    parts = path.split(".")
    if parts and parts[0] == "window":
        parts = parts[1:]
    if parts and parts[0] and parts[0] not in {"__proto__", "constructor", "prototype"}:
        root = parts[0]
        snapshot = frame.evaluate(STATE_CATALOG, root)
        for item in snapshot['rows']:
            add({"source": "state", "path": item['path']}, item['value'])
        if skipped is not None:
            skipped.extend(snapshot['skipped'])
    dom = frame.evaluate(r"""() => [...document.querySelectorAll('[id]')].slice(0,40).flatMap(e=>{
      const r=e.getBoundingClientRect();
      if(!r.width||!r.height||e.tagName==='SCRIPT'||e.tagName==='STYLE'||e.children.length) return [];
      const selector='#'+CSS.escape(e.id), text=(e.textContent||'').trim();
      return text && text.length<=120 && selector.length<=200 && document.querySelectorAll(selector).length===1
        ? [{selector,value:text}] : [];
    }).slice(0,8)""")
    for item in dom:
        if len(rows) >= 16:
            break
        add({"source": "text", "selector": item["selector"]}, item["value"])
    return rows


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
        result["observation_skips"] = []
        result["observations"] = observation_catalog(frame, check, state_script, result["observation_skips"])
        step = result.get("step") or {}
        if step.get("selector") and step.get("action") in {"click", "tap", "click_fraction", "tap_fraction"}:
            result["input_probe"] = frame.evaluate(INPUT_TARGET, step)
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
