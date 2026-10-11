// Reviewed platform API regression fixture, not a generated game benchmark.
function createGame(ctx) {
  const doc = ctx.root.ownerDocument;
  const state = {phase:'ready', clicks:0, keys:0, dragged:0, never:0, foreign:0, foreignRejected:false, foreignDocumentRejected:false, moved:false, unsubscribed:false, paused:false};
  const panel=doc.createElement('main');panel.innerHTML='<h1>Scoped input runtime regression</h1><p data-testid="scope-count"></p>';
  ctx.root.append(panel);
  const button=(name,text)=>{const item=doc.createElement('button');item.dataset.testid='scope-'+name;item.textContent=text;return item;};
  const count=panel.querySelector('[data-testid="scope-count"]');
  const render=()=>{count.textContent='Clicks '+state.clicks+' · keys '+state.keys+' · dragged '+state.dragged+' · detached '+state.never+' · foreign '+state.foreign;};
  const deferred=button('deferred','Ordinary control bound before append');
  const off=ctx.input.on(deferred,'click',()=>{state.clicks++;render();});
  panel.append(deferred);
  const drag=doc.createElement('div');drag.dataset.testid='scope-drag';drag.textContent='Drag this control downwards';drag.style.cssText='width:220px;height:80px;padding:12px;background:#28445f;touch-action:none';panel.append(drag);
  let dragY=null;
  ctx.input.on(drag,'pointerdown',event=>{dragY=event.clientY;drag.setPointerCapture(event.pointerId);});
  ctx.input.on(drag,'pointerup',event=>{if(dragY!==null&&event.clientY-dragY>=60)state.dragged++;dragY=null;render();});
  ctx.input.on(drag,'pointercancel',()=>{dragY=null;});
  const never=button('never','Never appended');
  ctx.input.on(never,'click',()=>{state.never++;render();});
  const foreign=button('foreign','Foreign connected control');doc.body.append(foreign);
  try{ctx.input.on(foreign,'click',()=>{state.foreign++;render();});}catch(_){state.foreignRejected=true;}
  const otherDocument=doc.implementation.createHTMLDocument('Foreign fixture document');
  const foreignDocument=otherDocument.createElement('button');
  try{ctx.input.on(foreignDocument,'click',()=>{state.foreign++;render();});}catch(_){state.foreignDocumentRejected=true;}
  const move=button('move','Move ordinary control outside');panel.append(move);
  ctx.input.on(move,'click',()=>{doc.body.append(deferred);state.moved=true;render();});
  const back=button('return','Return control into game');panel.append(back);
  ctx.input.on(back,'click',()=>{panel.append(deferred);state.moved=false;render();});
  const unsubscribe=button('unsubscribe','Remove ordinary handler');panel.append(unsubscribe);
  ctx.input.on(unsubscribe,'click',()=>{off();state.unsubscribed=true;render();});
  ctx.input.key((key,event)=>{if(key==='1'&&!event.repeat){state.keys++;render();}});
  ctx.cleanup(()=>{foreign.remove();deferred.remove();});
  render();
  return {snapshot:()=>JSON.parse(JSON.stringify(state)),dispatch(action){if(action.type==='START')state.phase='playing';render();},pause(hidden){state.paused=hidden;}};
}
