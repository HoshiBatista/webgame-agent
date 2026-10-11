// Trusted fixture UI. Production and manual advancement share dispatch().
function mountGame(root){
  const engine=new GameEngine();let audio=null,ctx=null,manual=false,raf=0,previous=0,acc=0,disposed=false,sound=false;
  const fixed=false;
  root.innerHTML='<section style="max-width:650px;margin:30px auto;padding:24px;font-family:system-ui"><h1>Три лампы · test fixture</h1><p>Зажгите все три лампы. Ход только после нажатия.</p><canvas data-testid="canvas" width="600" height="320" style="width:100%"></canvas><button data-testid="start" data-action="start">Начать</button><button data-action="toggle" data-index="0">Лампа 1</button><button data-action="toggle" data-index="1">Лампа 2</button><button data-action="toggle" data-index="2">Лампа 3</button><button data-action="pause">Пауза</button><button data-action="reset">Сначала</button><button data-testid="sound" data-action="sound" aria-pressed="false">Звук</button><p data-testid="status"></p></section>';
  const renderer=new GameRenderer(root.querySelector('canvas'));
  const render=()=>{const s=engine.snapshot();renderer.draw(s,0);root.querySelector('[data-testid="status"]').textContent=s.phase;};
  function dispatch(a){const result=engine.act(a);audio?.handleEvents(engine.drainEvents());return result;}
  function reset({seed='fixture'}={}){engine.reset({seed});audio?.dispose();audio=ctx?new GameAudio(ctx):null;audio?.setState({enabled:sound});acc=0;previous=0;render();return engine.snapshot();}
  async function click(e){const b=e.target.closest('button');if(!b)return;const type=b.dataset.action;
    if(type==='sound'){sound=!sound;b.setAttribute('aria-pressed',String(sound));if(sound&&!ctx){const AudioContextClass=window.AudioContext||window.webkitAudioContext;if(AudioContextClass){ctx=new AudioContextClass();audio=new GameAudio(ctx);}}if(sound&&ctx)await ctx.resume();if(disposed)return;audio?.setState({enabled:sound});}
    else if(type==='reset')reset();else if(type==='pause')dispatch({type,value:!engine.snapshot().paused});else dispatch({type,index:Number(b.dataset.index)});render();
  }
  root.addEventListener('click',click);
  const key=e=>{if(e.code==='Space'&&fixed&&!/INPUT|BUTTON|SELECT/.test(document.activeElement?.tagName||'')){e.preventDefault();dispatch({type:'jump'});render();}};window.addEventListener('keydown',key);
  const hidden=()=>{previous=0;acc=0;if(document.hidden)dispatch({type:'pause',value:true});};document.addEventListener('visibilitychange',hidden);
  function frame(now){if(disposed)return;const dt=previous?Math.min(.1,(now-previous)/1000):0;previous=now;
    if(fixed&&!manual&&!document.hidden){acc+=dt;let n=0;while(acc>=1/60&&n++<6){dispatch({type:'tick'});acc-=1/60;}if(n>=6)acc=0;}render();raf=requestAnimationFrame(frame);
  }
  function dispose(){if(disposed)return;disposed=true;cancelAnimationFrame(raf);root.removeEventListener('click',click);window.removeEventListener('keydown',key);window.removeEventListener('pagehide',dispose);document.removeEventListener('visibilitychange',hidden);audio?.dispose();ctx?.close();renderer.dispose();engine.dispose();if(window.__GAME_TEST__?.owner===root)delete window.__GAME_TEST__;}
  window.__GAME_TEST__={ready:true,owner:root,snapshot:()=>engine.snapshot(),act:a=>{const result=dispatch(a);render();return result;},reset,setManualMode:value=>{manual=!!value;acc=0;previous=0;},advance:frames=>{if(!manual||!fixed||!Number.isInteger(frames)||frames<1||frames>3600)throw new Error('Unsupported manual advancement');for(let i=0;i<frames;i++)dispatch({type:'tick'});render();},dispose};
  window.addEventListener('pagehide',dispose);render();raf=requestAnimationFrame(frame);return {dispose};
}
