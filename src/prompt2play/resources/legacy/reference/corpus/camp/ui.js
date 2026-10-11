/* Full reviewed camp UI, adapted only for Forge mounting and QA surfaces. */
function mountGame(host){
let uiDisposed=false,uiManualMode=false,uiRaf=null;
const uiListeners=[];
function uiListen(target,event,handler,options){
  target.addEventListener(event,handler,options);
  uiListeners.push(()=>target.removeEventListener(event,handler,options));
}
/* Пепельный свод 2.0.1 — лагерь, интерфейс и сохранение кампании. */
const ASHEN_SAVE_KEY = 'game-forge.corpus.camp.v2';
const ASHEN_LEGACY_SAVE_KEY = 'game-forge.corpus.camp.legacy.v1';
const ASHEN_PREF_KEY = 'game-forge.corpus.camp.preferences.v1';
const ASHEN_FLOORS = ['Погасшие залы', 'Корни забвения', 'Костяная часовня', 'Печь без огня', 'Сердце свода'];
const ASHEN_ROMAN = ['I', 'II', 'III', 'IV', 'V'];
const escapeHTML = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clampUI = (v, a, b) => Math.max(a, Math.min(b, Number(v) || 0));
const storage = {
  available: true,
  read(key) { try { const value=localStorage.getItem(key); this.available=true; return {ok:true,value}; } catch (_) { this.available=false; return {ok:false,value:null}; } },
  get(key) { return this.read(key).value; },
  set(key,value) { try { localStorage.setItem(key,value); this.available=true; return true; } catch (_) { this.available=false; return false; } }
};
let preferences = {sound:true,music:true,musicVolume:.55,reduceMotion:typeof matchMedia==='function'&&matchMedia('(prefers-reduced-motion: reduce)').matches};
try { const p=JSON.parse(storage.get(ASHEN_PREF_KEY)||'{}'); if(p&&typeof p==='object'&&!Array.isArray(p))preferences={...preferences,...p}; } catch (_) {}
preferences.sound=!!preferences.sound;preferences.music=!!preferences.music;
preferences.musicVolume=typeof preferences.musicVolume==='number'&&Number.isFinite(preferences.musicVolume)?clampUI(preferences.musicVolume,0,1):.55;
const style = document.createElement('style');
style.textContent = `
:root{color-scheme:dark;--bg:#0b1011;--panel:#11191a;--line:#2c3531;--ink:#e9e0cb;--muted:#8d9993;--amber:#e5b975;--copper:#ad7742;--green:#8da98b;--red:#d76e65;--blue:#7bbbbf;--shadow:0 24px 80px #0009}
*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:var(--bg);color:var(--ink);font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}body{overscroll-behavior:none}button,input{font:inherit}button{cursor:pointer;color:inherit}button:disabled{opacity:.38;cursor:not-allowed}button:focus-visible,input:focus-visible{outline:2px solid var(--amber);outline-offset:4px}button{touch-action:manipulation}button,input,a{-webkit-tap-highlight-color:transparent}button{user-select:none}button kbd{pointer-events:none}kbd{font:11px ui-monospace,SFMono-Regular,Consolas,monospace;display:inline-grid;place-items:center;min-width:21px;height:21px;border:1px solid #5b635047;border-radius:4px;padding:0 5px;background:#ffffff06;color:#bec8b8}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}[hidden]{display:none!important}
#ashen-root{min-height:100dvh;isolation:isolate;background:radial-gradient(ellipse at 25% -10%,#26332645,transparent 50%),var(--bg)}
.ash-top{height:74px;padding:0 28px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);gap:18px;background:#0d1312ed}
.ash-brand{display:flex;align-items:center;gap:15px}.ash-sigil{width:30px;height:36px;position:relative;display:block}.ash-sigil:before{content:'';position:absolute;left:5px;top:6px;width:20px;height:25px;border:1px solid var(--copper);transform:rotate(30deg) skewY(30deg);box-shadow:0 0 25px #d98c2630}.ash-sigil:after{content:'✦';position:absolute;inset:0;display:grid;place-items:center;font-size:21px;color:var(--amber)}.ash-brand strong{display:block;font:600 18px Georgia,'Times New Roman',serif;letter-spacing:.6px}.ash-brand small{display:block;color:var(--muted);font-size:9px;letter-spacing:3px;margin-top:4px;text-transform:uppercase}.ash-top-actions{display:flex;align-items:center;gap:8px}.ash-top-actions button{border:1px solid transparent;background:transparent;padding:9px 12px;border-radius:5px;font-size:12px;color:#aab4ab}.ash-top-actions button:hover{background:#ffffff07;border-color:var(--line);color:var(--ink)}.ash-status{font-size:11px;color:var(--muted);margin-right:18px}.ash-status:before{content:'';display:inline-block;width:5px;height:5px;background:var(--green);border-radius:50%;margin-right:8px;box-shadow:0 0 8px #8da98b55}
.ash-layout{padding:22px 26px 16px;max-width:1760px;margin:auto;display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:20px;height:calc(100dvh - 110px);min-height:580px}.ash-main{min-width:0;min-height:0;display:flex;flex-direction:column;gap:12px}.ash-world-frame{position:relative;min-height:280px;flex:1;overflow:hidden;border:1px solid #374037;border-radius:9px;background:#080c0d;box-shadow:0 8px 40px #0004}.ash-world-frame:after{pointer-events:none;position:absolute;inset:0;content:'';box-shadow:inset 0 0 70px #0004;border-radius:8px}.ash-world{display:block;width:100%;height:100%;position:absolute;inset:0;touch-action:none}.ash-world-top{position:absolute;left:21px;right:19px;top:18px;display:flex;align-items:start;justify-content:space-between;gap:12px;pointer-events:none;z-index:2}.ash-depth{background:#0a1011c9;padding:9px 12px;border:1px solid #4450475c;border-radius:5px;backdrop-filter:blur(8px)}.ash-depth .eyebrow{font-size:9px;letter-spacing:2px;color:var(--amber);text-transform:uppercase}.ash-depth strong{font:19px Georgia,serif;display:block;margin-top:5px}.ash-turn{font:10px ui-monospace,monospace;padding:10px;color:#9caca3;text-shadow:0 2px 6px #000;background:#0a10118c;border-radius:5px}.ash-world-bottom{position:absolute;left:20px;bottom:17px;right:20px;display:flex;justify-content:space-between;align-items:end;gap:14px;z-index:2;pointer-events:none}.ash-world-hint{max-width:370px;color:#d0d5c1;font-size:11px;line-height:1.6;text-shadow:0 2px 5px #000;padding:8px 11px;border-left:2px solid #b59151a1;background:linear-gradient(90deg,#0a1111e8,#0a111100)}.ash-mini-wrap{pointer-events:auto;display:flex;flex-direction:column;align-items:end;gap:6px}.ash-mini{width:128px;height:91px;border:1px solid #546b5050;background:#09100deb;border-radius:4px;image-rendering:pixelated;opacity:.92}.ash-mini-label{font:9px ui-monospace,monospace;color:#99a695}.ash-hover{position:absolute;pointer-events:none;z-index:3;right:20px;top:75px;background:#111915ed;border:1px solid #55604c;padding:10px 13px;border-radius:5px;font-size:12px;max-width:235px;box-shadow:var(--shadow)}.ash-hover b{display:block;margin-bottom:4px;font-size:13px}.ash-hover span{color:var(--muted);font-size:11px}.ash-hover.danger{border-color:#946254}
.ash-commands{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}.ash-command{min-height:66px;background:linear-gradient(150deg,#1a2320,#131b19);border:1px solid #344033;border-radius:7px;padding:10px 12px;display:flex;align-items:center;gap:11px;text-align:left;transition:border-color .15s,background .15s,transform .15s}.ash-command:hover:not(:disabled){border-color:var(--copper);background:#20291f;transform:translateY(-1px)}.ash-command:active:not(:disabled){transform:translateY(1px)}.ash-command .cmd-icon{font-family:Georgia,serif;font-size:25px;min-width:22px;text-align:center;color:var(--amber)}.ash-command .cmd-copy{min-width:0;flex:1}.ash-command strong{font-size:11px;display:block;font-weight:550;white-space:nowrap}.ash-command small{font-size:10px;color:var(--muted);display:block;margin-top:5px;white-space:nowrap}.ash-command.magic .cmd-icon{color:var(--blue)}.ash-command.heal .cmd-icon{color:#d99187}.ash-command kbd{align-self:start;height:18px;min-width:18px;font-size:10px}.ash-command.wait .cmd-icon{font-size:21px}
.ash-sidebar{min-height:0;display:flex;flex-direction:column;gap:14px}.ash-card{border:1px solid var(--line);border-radius:7px;background:linear-gradient(145deg,#17201be6,#111917);padding:17px}.ash-card-title{font-size:9px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin:0 0 13px;display:flex;justify-content:space-between}.ash-hero-heading{display:flex;align-items:center;gap:12px;margin-bottom:18px}.ash-hero-mark{width:42px;height:47px;display:grid;place-items:center;font:31px Georgia,serif;color:var(--amber);border:1px solid #80643e73;border-radius:22px 22px 8px 8px;background:radial-gradient(ellipse at center,#b3864c16,#0000)}.ash-hero-heading h2{font:21px Georgia,serif;margin:0 0 4px}.ash-hero-heading p{font-size:10px;letter-spacing:.4px;margin:0;color:var(--muted)}.ash-bar-head{display:flex;justify-content:space-between;font-size:10px;margin-bottom:6px;color:#b3bcae}.ash-bar-head b{font:11px ui-monospace,monospace;font-weight:400;color:var(--ink)}.ash-bar{height:7px;border-radius:4px;background:#050b09;border:1px solid #ffffff0b;overflow:hidden;margin-bottom:13px}.ash-bar-fill{height:100%;width:0;background:linear-gradient(90deg,#963e3a,#cb8071);transition:width .15s;border-radius:3px}.ash-bar.mana .ash-bar-fill{background:linear-gradient(90deg,#2d646b,#76b8bb)}.ash-bar.xp{height:4px;margin:8px 0 0}.ash-bar.xp .ash-bar-fill{background:#aa9161}.ash-stats{display:grid;grid-template-columns:repeat(3,1fr);margin-top:16px;padding-top:14px;border-top:1px solid var(--line);gap:8px}.ash-stat b{font:20px Georgia,serif;display:block;color:#d7d4bc}.ash-stat span{display:block;font-size:9px;color:var(--muted);margin-top:5px}.ash-equipment{display:grid;gap:11px}.ash-equipment-row{display:flex;align-items:center;gap:11px}.ash-equipment-row .equip-icon{font:21px Georgia,serif;color:var(--copper);width:25px;text-align:center}.ash-equipment-row strong{font-size:11px;font-weight:500;display:block}.ash-equipment-row small{font-size:9px;color:var(--muted);display:block;margin-top:3px}.ash-relics{display:flex;gap:6px;flex-wrap:wrap;margin-top:13px;padding-top:12px;border-top:1px solid var(--line)}.ash-relic{font-size:9px;line-height:1.6;padding:3px 7px;border:1px solid #7766434d;border-radius:4px;color:#d0ba8c;background:#65501d16}.ash-relic.empty{padding:0;border:0;color:var(--muted);background:none}.ash-log-card{flex:1;min-height:145px;overflow:hidden;display:flex;flex-direction:column}.ash-log{display:flex;flex-direction:column;gap:9px;overflow:auto;scrollbar-width:thin;scrollbar-color:#384434 transparent;mask-image:linear-gradient(#000 92%,transparent)}.ash-log p{font-size:11px;line-height:1.55;margin:0;padding-left:10px;border-left:1px solid #425040;color:#a3afa2}.ash-log p:first-child{color:#d4dcca;border-color:var(--amber)}.ash-log p.bad,.ash-log p.damage{color:#d39888}.ash-log p.good,.ash-log p.loot,.ash-log p.level{color:#d6c094}.ash-log .log-turn{font:8px ui-monospace,monospace;color:#637261;margin-right:6px}.ash-log-card .ash-card-title{margin-bottom:12px}.ash-footer{height:36px;display:flex;align-items:center;justify-content:space-between;padding:0 29px;font-size:10px;color:#718072;letter-spacing:.2px;max-width:1760px;margin:auto}.ash-footer em{font-style:normal;color:#9eac97}.ash-footer kbd{height:15px;min-width:17px;font-size:8px;margin:0 3px}.ash-dpad{display:none}
.ash-overlay{position:fixed;inset:0;background:radial-gradient(ellipse at 50% 25%,#101e199e,#040908ed);backdrop-filter:blur(7px);z-index:10;overflow:auto;display:flex;align-items:center;justify-content:center;padding:30px 20px}.ash-modal{width:min(880px,100%);margin:auto;position:relative}.ash-modal:before{content:'';height:1px;position:absolute;left:10%;right:10%;top:0;background:linear-gradient(90deg,transparent,#8e714f,transparent)}.ash-kicker{font-size:10px;font-weight:500;letter-spacing:3.5px;color:var(--amber);text-align:center;margin:34px 0 21px;text-transform:uppercase}.ash-title{font:clamp(42px,7vw,78px)/.99 Georgia,'Times New Roman',serif;text-align:center;margin:0;color:#eee0bd;font-weight:400;letter-spacing:-2.5px;text-shadow:0 0 50px #cca36620}.ash-title .title-soft{color:#a79372}.ash-subtitle{font-size:13px;line-height:1.9;text-align:center;max-width:540px;margin:23px auto 27px;color:#a8b2a2}.ash-title-rule{display:flex;align-items:center;justify-content:center;gap:15px;color:var(--copper);margin:20px auto 26px;font-size:15px}.ash-title-rule:before,.ash-title-rule:after{content:'';width:70px;height:1px;background:linear-gradient(90deg,transparent,#725633)}.ash-title-rule:after{transform:rotate(180deg)}.ash-class-label{font-size:9px;letter-spacing:2.5px;text-align:center;text-transform:uppercase;color:#87987e;margin-bottom:13px}.ash-classes{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.ash-class{background:#141d18c9;border:1px solid #344333;border-radius:8px;padding:19px 17px 17px;text-align:left;position:relative;transition:all .2s}.ash-class:hover{border-color:#877548;background:#1c281d}.ash-class.selected{border-color:#b59a5a;background:linear-gradient(140deg,#35412a7a,#142119e6);box-shadow:inset 0 0 25px #c69d3a0a,0 0 28px #9372320b}.ash-class.selected:after{content:'✦';position:absolute;right:14px;top:15px;color:var(--amber);font-size:12px}.ash-class-symbol{font:29px Georgia,serif;color:var(--amber);display:block;margin-bottom:13px}.ash-class h3{font:21px Georgia,serif;margin:0 0 8px}.ash-class p{font-size:11px;line-height:1.65;color:#9cac98;margin:0;min-height:52px}.ash-class-trait{display:block;margin-top:14px;font-size:9px;text-transform:uppercase;letter-spacing:1.1px;color:#c2bc95}.ash-start-row{display:flex;justify-content:center;gap:12px;margin-top:27px;flex-wrap:wrap}.ash-primary,.ash-secondary{border-radius:5px;padding:14px 25px;min-height:47px;font-size:12px;font-weight:600;letter-spacing:.2px}.ash-primary{background:linear-gradient(135deg,#d8b579,#b38f57);border:1px solid #e5c892;color:#172018;box-shadow:0 4px 24px #a98b451b}.ash-primary:hover{filter:brightness(1.13);transform:translateY(-1px)}.ash-secondary{border:1px solid #4a5742;background:#152018;color:#c5cfb7}.ash-secondary:hover{border-color:#84956f;background:#23301e}.ash-seed{display:flex;justify-content:center;align-items:center;gap:10px;margin:21px 0 0;font-size:10px;color:#778871}.ash-seed input{background:#09130d85;border:1px solid #32402c;border-radius:4px;padding:7px 9px;color:#bac8b0;width:190px;font:10px ui-monospace,monospace}.ash-seed input::placeholder{color:#64705e}.ash-menu-bottom{display:flex;justify-content:center;gap:22px;flex-wrap:wrap;margin:25px 0 5px;font-size:10px;color:#84957a}.ash-link{border:0;background:none;padding:3px;color:#a4b194;font-size:11px;text-decoration:underline;text-underline-offset:5px;text-decoration-color:#52613a}.ash-menu-note{color:#62705d;text-align:center;font-size:9px;margin:15px 0 5px;line-height:1.7}.ash-dialog{background:linear-gradient(155deg,#19251cfa,#0e1912fa);border:1px solid #586447;border-radius:12px;padding:32px;width:min(600px,100%);box-shadow:var(--shadow);margin:auto}.ash-dialog.wide{width:min(900px,100%)}.ash-dialog h2{font:36px/1.15 Georgia,serif;margin:0 0 13px;color:#e8ddba;font-weight:400}.ash-dialog .lead{font-size:13px;color:#a7b59a;line-height:1.8;margin:0 0 23px}.ash-dialog .ash-kicker{text-align:left;margin:0 0 16px;letter-spacing:2px;font-size:9px}.ash-dialog-actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:23px}.ash-dialog .ash-primary,.ash-dialog .ash-secondary{padding:12px 19px}.ash-help-grid{display:grid;grid-template-columns:1fr 1fr;gap:15px 25px}.ash-help-grid h3{font-size:11px;font-weight:600;color:#dbc28f;margin:0 0 8px}.ash-help-grid p,.ash-help-grid li{font-size:11px;line-height:1.8;color:#b0bda2;margin:0}.ash-help-grid ul{margin:0;padding-left:17px}.ash-help-keys{display:grid;gap:7px}.ash-help-keys div{display:flex;justify-content:space-between;gap:10px;border-bottom:1px solid #ffffff07;padding:3px 0;font-size:11px;color:#aebb9f}.ash-help-grid section.full{grid-column:1/-1;border-top:1px solid var(--line);padding-top:14px}.ash-choice-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:22px}.ash-choice{padding:24px 17px;background:#17271bcc;border:1px solid #66744a;border-radius:7px;text-align:left;transition:transform .15s,border-color .15s;min-height:175px}.ash-choice:hover{transform:translateY(-4px);border-color:var(--amber);background:#27341d}.ash-choice b{font:21px Georgia,serif;display:block;margin:14px 0 10px;color:#e2d7ab}.ash-choice p{font-size:11px;line-height:1.7;color:#abb89a;margin:0}.ash-choice span{font:24px Georgia,serif;color:var(--amber)}.ash-result-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:26px 0}.ash-result-grid div{padding:15px 12px;background:#0002;border:1px solid #55633c61;border-radius:5px}.ash-result-grid b{font:30px Georgia,serif;color:var(--amber);display:block}.ash-result-grid span{font-size:10px;color:#96a887;display:block;margin-top:7px}.ash-toggle{display:flex;align-items:center;justify-content:space-between;gap:15px;border-top:1px solid var(--line);padding:14px 0;font-size:12px;color:#bdc9af}.ash-toggle button{border:1px solid #657050;background:#25321e;border-radius:4px;padding:6px 12px;font-size:10px;min-width:80px}.ash-danger{color:#db9e8d!important;border-color:#765646!important}.ash-divider{height:1px;background:var(--line);margin:19px 0}.ash-toast{position:fixed;bottom:80px;left:50%;transform:translate(-50%,15px);padding:12px 18px;border:1px solid #7c7046;background:#152218f5;border-radius:6px;color:#dcdabb;font-size:12px;z-index:25;pointer-events:none;box-shadow:var(--shadow);opacity:0;transition:opacity .15s,transform .15s;max-width:min(550px,90vw);text-align:center}.ash-toast.show{opacity:1;transform:translate(-50%,0)}.in-menu .ash-top,.in-menu .ash-sidebar,.in-menu .ash-footer,.in-menu .ash-commands{filter:brightness(.35)}
@media(min-width:1500px){.ash-layout{grid-template-columns:minmax(0,1fr) 305px;gap:24px;padding-top:25px}.ash-card{padding:21px}.ash-hero-heading h2{font-size:24px}.ash-command{min-height:72px}.ash-command strong{font-size:12px}}
@media(max-width:1120px){.ash-layout{grid-template-columns:minmax(0,1fr) 232px;padding:15px;gap:13px}.ash-card{padding:14px}.ash-command{padding:10px 8px;gap:7px}.ash-command kbd{display:none}.ash-command .cmd-icon{font-size:21px}.ash-command strong{font-size:10px}.ash-command small{font-size:9px}.ash-status{display:none}.ash-top{padding:0 19px}.ash-footer{padding:0 17px}.ash-sidebar{gap:11px}}
@media(max-width:820px){.ash-top{height:59px;padding:0 13px}.ash-brand strong{font-size:16px}.ash-brand small{font-size:8px;letter-spacing:2px}.ash-brand{gap:10px}.ash-top-actions{gap:0}.ash-top-actions button{padding:9px;font-size:11px}.ash-top-actions .optional{display:none}.ash-layout{height:auto;min-height:0;padding:11px;display:flex;flex-direction:column;gap:12px}.ash-main{height:calc(100dvh - 180px);min-height:400px;max-height:850px;gap:9px}.ash-sidebar{display:grid;grid-template-columns:1fr 1fr;gap:10px}.ash-log-card{grid-column:1/-1;min-height:130px;max-height:160px}.ash-hero-heading{margin-bottom:12px}.ash-card{padding:14px}.ash-footer{height:auto;min-height:38px;font-size:9px;gap:12px;flex-wrap:wrap;padding:8px 13px}.ash-command{min-height:60px;padding:9px 7px;gap:5px;justify-content:center}.ash-command .cmd-icon{font-size:20px;min-width:18px}.ash-world-top{left:12px;right:10px;top:11px}.ash-depth{padding:7px 9px}.ash-depth strong{font-size:16px}.ash-depth .eyebrow{font-size:8px}.ash-world-bottom{left:12px;right:12px;bottom:12px}.ash-world-hint{display:none}.ash-mini{width:94px;height:67px}.ash-mini-wrap{margin-left:auto}.ash-dpad{display:grid;grid-template-columns:repeat(3,37px);grid-template-rows:repeat(3,35px);position:absolute;bottom:13px;left:13px;z-index:4;gap:3px;touch-action:none}.ash-dpad button{background:#13211ccf;backdrop-filter:blur(3px);border:1px solid #67754c88;border-radius:6px;color:#d2d9b6;font-size:20px;display:grid;place-items:center}.ash-dpad button:active{background:#647148}.ash-dpad .up{grid-column:2;grid-row:1}.ash-dpad .left{grid-column:1;grid-row:2}.ash-dpad .wait{grid-column:2;grid-row:2;font-size:13px}.ash-dpad .right{grid-column:3;grid-row:2}.ash-dpad .down{grid-column:2;grid-row:3}.ash-overlay{padding:20px 15px}.ash-title{font-size:58px}.ash-kicker{margin-top:20px}.ash-subtitle{font-size:12px;margin:20px auto}.ash-class{padding:15px 13px}.ash-class p{font-size:10px}.ash-dialog{padding:25px}.ash-dialog h2{font-size:31px}}
@media(max-width:520px){.ash-top-actions button{font-size:0;width:34px;padding:8px}.ash-top-actions button:before{content:attr(data-short);font:15px Georgia,serif}.ash-top-actions button[data-action='help']{font-size:0}.ash-brand strong{font-size:15px}.ash-command .cmd-icon{display:none}.ash-command strong{font-size:10px}.ash-command small{font-size:8px}.ash-commands{gap:5px}.ash-title{font-size:48px;letter-spacing:-1.8px}.ash-classes{gap:7px}.ash-class{padding:14px 10px}.ash-class h3{font-size:17px}.ash-class-symbol{font-size:23px;margin-bottom:10px}.ash-class p{font-size:10px;line-height:1.55;min-height:77px}.ash-class-trait{font-size:8px;letter-spacing:.4px;margin-top:11px}.ash-subtitle{font-size:11px;margin:16px auto 22px}.ash-kicker{font-size:8px;letter-spacing:2.5px}.ash-start-row{margin-top:20px;gap:9px}.ash-primary,.ash-secondary{padding:13px 18px}.ash-menu-bottom{gap:15px;font-size:9px;margin-top:20px}.ash-menu-note{font-size:8px}.ash-dialog{padding:23px 18px}.ash-help-grid{grid-template-columns:1fr;gap:16px}.ash-choice-grid{grid-template-columns:1fr;gap:10px}.ash-choice{min-height:0;padding:16px}.ash-choice b{display:inline;font-size:20px;margin-left:10px}.ash-choice p{margin-top:9px}.ash-result-grid{gap:7px}.ash-result-grid div{padding:12px 9px}.ash-result-grid b{font-size:26px}.ash-toast{bottom:75px;font-size:11px}.ash-seed input{width:145px}.ash-sidebar{grid-template-columns:1fr 1fr}.ash-card{padding:12px}.ash-hero-heading{gap:8px}.ash-hero-mark{width:32px;height:37px;font-size:25px}.ash-hero-heading h2{font-size:17px}.ash-hero-heading p{font-size:9px}.ash-stat b{font-size:17px}.ash-equipment-row{gap:7px}.ash-equipment-row strong{font-size:10px}.ash-equipment-row .equip-icon{width:17px;font-size:18px}.ash-world-frame{border-radius:6px}.ash-log-card{display:none}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important;animation:none!important}}
`;
style.textContent+=`\n.ash-toggle small{display:block;margin-top:5px;color:var(--muted);font-size:10px}.ash-music-volume{display:grid;grid-template-columns:minmax(0,1fr) 42px;align-items:center;gap:10px 12px;padding:3px 0 19px;color:#aab69e;font-size:11px}.ash-music-volume label{grid-column:1/-1}.ash-music-volume input{width:100%;min-width:0;accent-color:var(--amber);cursor:pointer;height:24px}.ash-music-volume output{text-align:right;font:11px ui-monospace,monospace;color:var(--amber)}\n`;
document.head.appendChild(style);
document.documentElement.lang = 'ru';
document.title = 'Пепельный свод — Лагерь последней искры';
style.textContent += `
.ash-layout{grid-template-columns:minmax(0,1fr) 300px}.ash-top{padding:0 24px}.ash-status.unsaved{color:#e6a178}.ash-status.unsaved:before{background:#e6a178}
#ashen-root.is-camp .ash-layout{grid-template-columns:minmax(0,1fr) 340px;height:calc(100dvh - 110px);min-height:670px}#ashen-root.is-camp .ash-main{gap:12px}#ashen-root.is-camp .ash-world-frame{border-color:#5a513b;min-height:430px}#ashen-root.is-camp .ash-world-frame:after{box-shadow:inset 0 0 40px #0002}#ashen-root.is-camp .ash-dpad{display:none}#ashen-root.is-camp .ash-sidebar{gap:14px}#ashen-root.is-camp .ash-world-bottom{bottom:17px}#ashen-root.is-camp .ash-world-hint{max-width:440px;color:#d7d3ae}
.ash-camp-eyebrow{font-size:9px;letter-spacing:2.6px;color:var(--amber);text-transform:uppercase;margin:2px 0 13px}.ash-camp-intro h1{font:31px/1.09 Georgia,serif;font-weight:400;letter-spacing:-.45px;margin:0 0 13px;color:#e8dec2}.ash-camp-intro h1 em{font-style:normal;color:#b6ae8c}.ash-camp-intro>p:last-child{font-size:11px;line-height:1.8;color:#98a392;margin:0;max-width:320px}
.ash-bank{padding:15px}.ash-bank .ash-card-title{margin-bottom:11px}.ash-bank .ash-card-title span{font-size:8px;color:#a0ad90;letter-spacing:0;text-transform:none}.ash-resource-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:5px}.ash-resource{text-align:center;min-width:0}.ash-resource .symbol{display:block;font:20px/1 Georgia,serif;color:var(--resource-color);margin:0 0 6px}.ash-resource b{display:block;font:19px Georgia,serif;font-weight:400}.ash-resource small{font-size:8px;color:#97a18d;display:block;margin-top:4px;white-space:nowrap}.ash-resource.resource-missing b{color:#db9682}
.ash-npc-list{display:grid;gap:8px}.ash-npc{display:grid;grid-template-columns:43px minmax(0,1fr) auto;align-items:center;gap:12px;text-align:left;padding:12px 13px;min-height:79px;border:1px solid #354437;background:linear-gradient(125deg,#1b2820,#131d18);border-radius:7px;transition:border-color .16s,background .16s}.ash-npc:hover{border-color:#908056;background:#243022}.ash-npc-portrait{width:42px;height:49px;display:grid;place-items:center;border:1px solid #81764a55;border-radius:24px 24px 9px 9px;background:#090f0b55;color:var(--npc-color)}.ash-npc-portrait svg{width:28px;height:28px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}.ash-npc strong{font:17px Georgia,serif;display:block}.ash-npc small{font-size:10px;line-height:1.5;display:block;margin-top:4px;color:#99a78f}.ash-npc .ash-npc-status{font-size:9px;color:#c5b989}.ash-npc .ash-npc-status.ready{color:#9dd3a3}.ash-npc .ash-npc-status.locked{color:#7d8b77}.ash-npc-rank{text-align:center;color:#908b64;font:12px Georgia,serif;min-width:22px}.ash-npc-rank span{display:block;font-size:8px;color:#697862;margin-top:5px}.ash-camp-bonuses{padding:14px 15px}.ash-camp-bonuses p{margin:9px 0 0;font-size:9px;color:#7f907b;line-height:1.6}.ash-bonus-pills{display:flex;gap:6px;flex-wrap:wrap}.ash-bonus{font-size:10px;padding:5px 8px;border:1px solid #5c65433d;background:#9f97460c;border-radius:4px;color:#c5c79f}.ash-bonus.empty{border:0;padding:0;font-size:11px;color:#8e9e85;line-height:1.6}
.ash-camp-actions{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px}.ash-depart{display:flex;align-items:center;justify-content:space-between;text-align:left;padding:15px 21px;font:18px Georgia,serif}.ash-depart small{display:block;font:8px ui-sans-serif,system-ui,sans-serif;font-weight:600;letter-spacing:2px;text-transform:uppercase;opacity:.7;margin-bottom:6px}.ash-depart>span:last-child{font:28px Georgia,serif;margin-left:15px}.ash-camp-actions>.ash-secondary{font-size:11px}.ash-return-rule{font-size:10px;line-height:1.55;color:#8a9985;min-height:16px}.ash-run-tools{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:9px;align-items:center}.ash-run-tools .ash-secondary{padding:10px 13px;min-height:45px;font-size:11px}.ash-run-tools .ash-secondary span{margin-right:5px}.ash-pack{padding:7px 10px;border:1px solid #303d32;border-radius:5px;background:#101913;min-height:45px}.ash-pack>span{display:block;font-size:8px;letter-spacing:1px;color:#82907c;margin-bottom:5px}.ash-material-line{display:flex;gap:11px;flex-wrap:wrap;font:11px ui-monospace,monospace}.ash-material-line span{white-space:nowrap;color:var(--resource-color)}.ash-material-line small{font:9px ui-sans-serif,system-ui,sans-serif;color:#85947e}
.ash-build-cost .ash-material-line{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.ash-build-cost .ash-material-line>span{white-space:normal;line-height:1.7}.ash-build-cost .ash-resource-available{display:block;font-size:9px;line-height:1.6;color:var(--resource-color)}
.ash-dialog.npc-dialog{width:min(980px,100%);padding:28px}.ash-dialog-top{display:flex;justify-content:space-between;align-items:start;gap:15px;margin-bottom:15px}.ash-dialog-top h2{font-size:31px;margin:0 0 7px}.ash-dialog-close{padding:8px 13px;border:1px solid #45523c;border-radius:5px;background:#101a12;color:#aebca0;font-size:11px;white-space:nowrap}.ash-dialog-top .ash-kicker{margin-bottom:9px}.ash-npc-greeting{font:italic 15px/1.7 Georgia,serif;color:#c4c8ac;margin:0 0 21px;padding-left:15px;border-left:2px solid #8c7549}.ash-npc-columns{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:22px}.ash-section-label{font-size:9px;text-transform:uppercase;letter-spacing:2px;color:#8d9f81;margin:0 0 13px}.ash-quest-card{border:1px solid #465439;border-radius:6px;background:#111d1399;padding:16px;margin-bottom:10px}.ash-quest-card.locked,.ash-quest-card.claimed{border-color:#2f3c2c;padding:11px 14px;background:#101a1255}.ash-quest-card.ready{border-color:#829b5d;box-shadow:inset 0 0 35px #acc76706}.ash-quest-title{display:flex;align-items:center;justify-content:space-between;gap:9px}.ash-quest-title h4{font:18px/1.25 Georgia,serif;color:#d8d9b8;margin:0}.ash-quest-title small{font-size:8px;letter-spacing:.5px;color:#a4b184;white-space:nowrap}.ash-quest-card.locked h4{color:#87947a;font-size:14px}.ash-quest-card.claimed h4{font-size:14px;color:#9cac87}.ash-quest-card p{font-size:11px;color:#9fab91;line-height:1.7;margin:10px 0 0}.ash-quest-goal{font-size:11px;line-height:1.7;color:#c3ceb1;margin:12px 0 7px}.ash-quest-progress{height:4px;border-radius:3px;background:#060e09;overflow:hidden}.ash-quest-progress i{display:block;height:100%;background:#b5b071;width:0}.ash-quest-reward{font-size:10px;line-height:1.7;color:#c5b87f;border-top:1px solid #35432e;padding-top:10px;margin-top:12px}.ash-quest-card .ash-primary,.ash-quest-card .ash-secondary{padding:9px 15px;font-size:11px;min-height:37px;margin-top:12px}.ash-build-panel{padding:20px;border:1px solid #6d6945;border-radius:8px;background:radial-gradient(ellipse at 70% 10%,#ab8b3417,transparent 70%),#172016}.ash-build-panel h3{font:27px Georgia,serif;font-weight:400;margin:13px 0 8px;color:#e2d4a7}.ash-build-panel>p{font-size:11px;line-height:1.8;color:#a3b195;margin:11px 0}.ash-build-levels{display:flex;gap:7px;margin:12px 0 16px}.ash-build-levels i{display:block;flex:1;height:5px;background:#070f09;border-radius:2px}.ash-build-levels i.filled{background:#baaa6a}.ash-build-gain{margin:16px 0;border-top:1px solid #58643c50;border-bottom:1px solid #58643c50;padding:14px 0}.ash-build-gain small{display:block;font-size:9px;color:#8fa17d;margin-bottom:7px}.ash-build-gain strong{font-size:12px;line-height:1.8;font-weight:500;color:#d4d6b2}.ash-build-cost{margin:15px 0}.ash-build-cost .ash-material-line{gap:14px;line-height:2}.ash-build-gate{font-size:10px!important;color:#c6b782!important}.ash-build-panel .ash-primary{width:100%;margin-top:8px}.ash-build-reason{min-height:18px}.ash-dialog-save{margin:15px 0 0;font-size:9px;line-height:1.7;color:#7f9374}.ash-dialog-save.unsaved{color:#d7a17d}.ash-journal-list{display:grid;grid-template-columns:1fr 1fr;gap:14px}.ash-journal-list .ash-quest-card{margin:0}.ash-journal-owner{display:block;color:#a69c6e;font-size:9px;text-transform:uppercase;letter-spacing:1px;margin-bottom:11px}.ash-expedition-stats{font-size:10px;line-height:1.8;color:#bbc6a5;margin-top:12px}.ash-summary-strip{padding:15px 18px;border:1px solid #586244;border-radius:6px;background:#172418;margin:15px 0}.ash-summary-strip h3{font:19px Georgia,serif;font-weight:400;margin:0 0 8px;color:#d7cfab}.ash-summary-strip p{font-size:11px;color:#b1bca0;line-height:1.8;margin:5px 0}.ash-empty-journal{padding:28px 20px;border:1px dashed #50603d;border-radius:6px;font-size:13px;color:#aab89a;line-height:1.9}.ash-save-note{font-size:10px!important;line-height:1.7!important}.ash-warning{color:#dda28b!important}.ash-menu-note.large{font-size:10px;line-height:1.9}.ash-dialog .ash-class h3{font-size:20px}.ash-dialog .ash-class p{min-height:55px}.ash-storage-warning{border:1px solid #825c40;background:#44281333;border-radius:6px;padding:12px 14px;font-size:11px;line-height:1.8;color:#d7aa8b;margin:15px 0}.ash-readonly-note{font-size:10px;color:#acb38b;line-height:1.7;margin:11px 0 0}
@media(min-width:1500px){#ashen-root.is-camp .ash-layout{grid-template-columns:minmax(0,1fr) 370px}.ash-camp-intro h1{font-size:35px}.ash-npc{padding:14px;min-height:86px}.ash-camp-sidebar .ash-bank{padding:17px}.ash-camp-sidebar{gap:17px}}
@media(max-width:1120px){#ashen-root.is-camp .ash-layout{grid-template-columns:minmax(0,1fr) 285px;min-height:640px}.ash-camp-intro h1{font-size:27px}.ash-npc{grid-template-columns:35px minmax(0,1fr) auto;gap:9px;padding:10px;min-height:72px}.ash-npc-portrait{width:34px;height:43px}.ash-npc strong{font-size:16px}.ash-npc small{font-size:9px}.ash-camp-actions{grid-template-columns:1fr}.ash-camp-actions>.ash-secondary{padding:10px;min-height:36px}.ash-camp-intro>p:last-child{font-size:10px}.ash-run-tools{grid-template-columns:auto minmax(0,1fr)}.ash-run-tools>button:last-child{grid-column:1/-1;padding:7px;min-height:30px}.ash-run-tools .ash-secondary{font-size:10px}.ash-pack .ash-material-line{gap:6px}}
@media(max-width:820px){#ashen-root.is-camp .ash-layout{display:flex;height:auto;min-height:0;gap:18px}#ashen-root.is-camp .ash-main{height:auto;max-height:none;min-height:0}#ashen-root.is-camp .ash-world-frame{height:58dvh;min-height:410px;flex:none}#ashen-root.is-camp .ash-sidebar{display:grid;grid-template-columns:1fr 1fr;gap:13px}#ashen-root.is-camp .ash-camp-intro{grid-column:1/-1;display:none}.ash-camp-sidebar .ash-bank{grid-column:1/-1}.ash-npc-list{grid-column:1/-1;grid-template-columns:1fr 1fr;gap:9px}.ash-camp-bonuses{grid-column:1/-1}.ash-camp-actions{grid-template-columns:minmax(0,1fr) auto}.ash-depart{font-size:16px}.ash-camp-actions>.ash-secondary{font-size:10px;padding:12px}.ash-camp-actions kbd{display:none}.ash-resource b{font-size:22px}.ash-resource small{font-size:9px}.ash-npc{min-height:80px}.ash-return-rule{font-size:10px}.ash-run-tools{grid-template-columns:auto minmax(0,1fr) auto;gap:6px}.ash-run-tools>button:last-child{grid-column:auto}.ash-run-tools kbd{display:none}.ash-pack{padding:7px}.ash-pack>span{font-size:7px}.ash-pack .ash-material-line{font-size:10px;gap:7px}.ash-run-tools .ash-secondary{padding:9px;min-height:48px}#ashen-root:not(.is-camp) .ash-main{height:auto;min-height:0;max-height:none}#ashen-root:not(.is-camp) .ash-world-frame{height:calc(100dvh - 235px);min-height:320px;flex:none}.ash-npc-columns{grid-template-columns:1fr}.ash-journal-list{grid-template-columns:1fr}.ash-dialog.npc-dialog{padding:22px}.ash-overlay{padding:17px 12px}.ash-dialog-top h2{font-size:27px}}
@media(max-width:480px){.ash-top-actions button{padding:8px 7px}.ash-top-actions button[data-action=help]{display:none}.ash-brand strong{font-size:14px}.ash-brand small{font-size:7px;letter-spacing:1.8px}.ash-camp-actions{grid-template-columns:1fr}.ash-camp-actions>.ash-secondary{padding:9px;min-height:36px}.ash-depart{font-size:17px}.ash-npc-list{grid-template-columns:1fr 1fr}.ash-npc{grid-template-columns:minmax(0,1fr) auto;gap:5px;min-height:83px}.ash-npc-portrait{display:none}.ash-npc strong{font-size:16px}.ash-npc .ash-npc-status{font-size:8px}.ash-run-tools{grid-template-columns:auto minmax(0,1fr)}.ash-run-tools>button:last-child{grid-column:1/-1;min-height:32px}.ash-camp-intro h1{font-size:29px}.ash-dialog .ash-classes{grid-template-columns:1fr}.ash-dialog .ash-class{padding:14px 16px}.ash-dialog .ash-class-symbol{float:left;width:28px;margin:0 14px 0 0}.ash-dialog .ash-class p{min-height:0;margin-left:42px}.ash-dialog .ash-class-trait{margin-left:42px}.ash-dialog .ash-expedition-stats{margin-left:42px}.ash-dialog{padding:24px 20px}.ash-dialog-top h2{font-size:25px}.ash-dialog-close{padding:7px 10px;font-size:10px}.ash-npc-greeting{font-size:14px}.ash-footer{font-size:8px}.ash-resource-grid{gap:4px}.ash-readonly-note{font-size:9px}}
@media(prefers-reduced-motion:reduce){.ash-npc,.ash-primary,.ash-command,.ash-bar-fill,.ash-toast{transition:none!important}}
#ashen-root.reduced-motion .ash-npc,#ashen-root.reduced-motion .ash-primary,#ashen-root.reduced-motion .ash-command,#ashen-root.reduced-motion .ash-bar-fill,#ashen-root.reduced-motion .ash-toast{transition:none!important}
`;

const root = document.createElement('div');
root.id = 'ashen-root';
root.innerHTML = `
<header class="ash-top">
  <div class="ash-brand"><span class="ash-sigil" aria-hidden="true"></span><div><strong>Пепельный свод</strong><small>Лагерь последней искры</small></div></div>
  <nav class="ash-top-actions" aria-label="Меню игры"><span class="ash-status" id="ash-save-status" role="status">Лагерь ждёт вас</span><button data-action="help" data-short="?" title="Правила и управление (?)">Путеводитель</button><button data-action="sound" data-short="♫" id="ash-sound-button" title="Включить или выключить звук">Звук: вкл.</button><button data-action="fullscreen" class="optional" data-short="⛶" title="На весь экран">Весь экран</button><button data-action="pause" data-short="Ⅱ" title="Меню (Esc)">Меню <kbd>Esc</kbd></button></nav>
</header>
<main class="ash-layout">
  <section class="ash-main" aria-label="Игровой мир">
    <div class="ash-world-frame" id="ash-world-frame">
      <canvas class="ash-world" id="ash-canvas" aria-label="Карта подземелья. Передвижение стрелками или WASD." tabindex="0"></canvas>
      <div class="ash-world-top"><div class="ash-depth"><div class="eyebrow" id="ash-depth-number">ГЛУБИНА I / V</div><strong id="ash-depth-name">Погасшие залы</strong></div><span class="ash-turn" id="ash-turn">ХОД 000</span></div>
      <div class="ash-hover" id="ash-hover" hidden></div>
      <div class="ash-world-bottom"><div class="ash-world-hint" id="ash-world-hint">Пять глубин отделяют вас от Сердца свода.</div><div class="ash-mini-wrap"><canvas class="ash-mini" id="ash-minimap" width="164" height="116" aria-label="Исследованная карта"></canvas><span class="ash-mini-label">КАРТА <kbd>Tab</kbd></span></div></div>
      <div class="ash-dpad" aria-label="Передвижение"><button class="up" data-move="0,-1" aria-label="Вверх">↑</button><button class="left" data-move="-1,0" aria-label="Влево">←</button><button class="wait" data-action="wait" aria-label="Пропустить ход">·</button><button class="right" data-move="1,0" aria-label="Вправо">→</button><button class="down" data-move="0,1" aria-label="Вниз">↓</button></div>
    </div>
    <div class="ash-commands" id="ash-dungeon-commands">
      <button class="ash-command magic" data-action="bolt" id="ash-bolt" title="Q: магическая искра в выбранного или ближайшего видимого врага. 3 маны."><span class="cmd-icon">ϟ</span><span class="cmd-copy"><strong>Искра</strong><small>3 маны · цель</small></span><kbd>Q</kbd></button>
      <button class="ash-command magic" data-action="nova" id="ash-nova" title="F: Кольцо пепла — удар по окружающим врагам. 5 маны."><span class="cmd-icon">✧</span><span class="cmd-copy"><strong>Кольцо</strong><small>5 маны · вокруг</small></span><kbd>F</kbd></button>
      <button class="ash-command heal" data-action="potion" id="ash-potion" title="H: выпить лечебное зелье. Расходует ход."><span class="cmd-icon">♧</span><span class="cmd-copy"><strong>Зелье</strong><small id="ash-potion-count">2 в сумке</small></span><kbd>H</kbd></button>
      <button class="ash-command" data-action="interact" id="ash-interact" title="E: спуститься, стоя на лестнице; использовать ближайший объект."><span class="cmd-icon">⇣</span><span class="cmd-copy"><strong id="ash-interact-name">Действие</strong><small id="ash-interact-detail">лестница · объект</small></span><kbd>E</kbd></button>
      <button class="ash-command wait" data-action="wait" id="ash-wait" title="Пробел: пропустить один ход."><span class="cmd-icon">◷</span><span class="cmd-copy"><strong>Подождать</strong><small>пропустить ход</small></span><kbd>␣</kbd></button>
    </div>
    <div class="ash-run-tools" id="ash-run-tools" hidden>
      <button class="ash-secondary" data-action="return" id="ash-return"><span>⇡</span> В лагерь <kbd>R</kbd></button>
      <div class="ash-pack"><span>Добыча вылазки</span><div id="ash-run-resources"></div></div>
      <button class="ash-secondary" data-action="quests">Задания <kbd>J</kbd><span id="ash-run-quest-count"></span></button>
    </div>
    <div class="ash-camp-actions" id="ash-camp-actions">
      <button class="ash-primary ash-depart" data-action="depart"><span><small>Искра снова зовёт</small>Отправиться в подземелье</span><span aria-hidden="true">→</span></button>
      <button class="ash-secondary" data-action="quests">Журнал заданий <kbd>J</kbd></button>
    </div>
    <div class="ash-return-rule" id="ash-return-rule"></div>
  </section>
  <aside class="ash-sidebar" id="ash-dungeon-sidebar" aria-label="Персонаж и события">
    <section class="ash-card"><div class="ash-hero-heading"><span class="ash-hero-mark" id="ash-hero-mark">♜</span><div><h2 id="ash-class-name">Страж</h2><p id="ash-level">Хранитель последней искры</p></div></div>
      <div class="ash-bar-head"><span>Жизнь</span><b id="ash-hp-text">—</b></div><div class="ash-bar"><div class="ash-bar-fill" id="ash-hp"></div></div>
      <div class="ash-bar-head"><span>Мана</span><b id="ash-mana-text">—</b></div><div class="ash-bar mana"><div class="ash-bar-fill" id="ash-mana"></div></div>
      <div class="ash-bar-head"><span id="ash-level-label">Уровень 1</span><b id="ash-xp-text">—</b></div><div class="ash-bar xp"><div class="ash-bar-fill" id="ash-xp"></div></div>
      <div class="ash-stats"><div class="ash-stat"><b id="ash-attack">—</b><span>Атака</span></div><div class="ash-stat"><b id="ash-armor">—</b><span>Защита</span></div><div class="ash-stat"><b id="ash-gold">—</b><span>Золото</span></div></div>
    </section>
    <section class="ash-card"><h3 class="ash-card-title">Снаряжение <span id="ash-kills">0 побед</span></h3><div class="ash-equipment"><div class="ash-equipment-row"><span class="equip-icon">†</span><div><strong id="ash-weapon">Старый клинок</strong><small>Оружие</small></div></div><div class="ash-equipment-row"><span class="equip-icon">◇</span><div><strong id="ash-armor-name">Походный плащ</strong><small>Доспех</small></div></div></div><div class="ash-relics" id="ash-relics"><span class="ash-relic empty">Реликвии ещё не найдены.</span></div></section>
    <section class="ash-card ash-log-card"><h3 class="ash-card-title">Шёпот свода <span aria-hidden="true">···</span></h3><div class="ash-log" id="ash-log" role="log" aria-live="polite" aria-relevant="additions"></div></section>
  </aside>
  <aside class="ash-sidebar ash-camp-sidebar" id="ash-camp-sidebar" aria-label="Лагерь и его жители">
    <section class="ash-camp-intro"><p class="ash-camp-eyebrow">Убежище среди пепла</p><h1>Здесь начинается<br><em>новый рассвет.</em></h1><p id="ash-camp-guidance">Поговорите с жителями. У каждого есть поручение — и надежда на вашу помощь.</p></section>
    <section class="ash-card ash-bank"><h2 class="ash-card-title">Запас лагеря <span>Сохраняется</span></h2><div class="ash-resource-grid" id="ash-bank-resources"></div></section>
    <nav class="ash-npc-list" id="ash-npc-list" aria-label="Жители лагеря"></nav>
    <section class="ash-card ash-camp-bonuses"><h2 class="ash-card-title">Сила построек <span id="ash-building-total">0 / 12</span></h2><div id="ash-camp-bonuses"></div><p>Действуют с начала каждой вылазки.</p></section>
  </aside>
</main>
<footer class="ash-footer"><span id="ash-controls-footer"><kbd>WASD</kbd> / <kbd>↑↓←→</kbd> движение и удар · <kbd>Q</kbd> / <kbd>F</kbd> магия</span><span id="ash-seed-footer">Свод помнит каждый шаг.</span></footer>
<div class="ash-overlay" id="ash-overlay" role="dialog" aria-modal="true" aria-label="Меню игры"></div>
<div class="ash-toast" id="ash-toast" role="status"></div>
<input type="file" id="ash-import" accept="application/json,.json" hidden>
`;
host.appendChild(root);
const $ = id => document.getElementById(id);
const canvas = $('ash-canvas');
const renderer = new GameRenderer(canvas);
const overlay = $('ash-overlay');
const campRenderer = new AshenCampRenderer(canvas);

let campaign = new GameEngine();
let engine = null, demo = null;
let screen='', returnScreen='', selectedClass='warden', selectedTarget=null, selectedNpc=null, lastSeed='', mapMode=false, hoverTile=null, campHover=null;
let moveQueue=[], nextAutoStep=0, lastInputTime=0, toastUntil=0, lastFrame=0, endedAt=0;
let saveState='unknown', persistenceBlocked=false, persistenceIssue='', lastSavedText=null, observedSaveText=null, hasSaveBaseline=false, importTicket=0, sessionRevision=0;
let modalOrigin=null, journalReturn='', saveWarningShown=false;
const classPresentation = {
  warden:{name:'Страж',symbol:'♜',desc:'Крепкая броня и тяжёлый клинок. Прощает первые ошибки.',trait:'Живучесть · ближний бой'},
  rogue:{name:'Тень',symbol:'†',desc:'Точный удар и лёгкий шаг. Риск вознаграждается.',trait:'Критические удары · уклонение'},
  mage:{name:'Искровед',symbol:'✧',desc:'Древняя магия подчиняется искре. Держите врагов на расстоянии.',trait:'Запас маны · заклинания'}
};
class AshenSound {
  constructor(){this.ctx=null;this.master=null;this.music=null;this.masterLevel=null;this.pageActive=true;this.last=0;}
  init(){
    if(!preferences.sound)return;
    try{
      const AudioClass=window.AudioContext||window.webkitAudioContext;
      if(!AudioClass)return;
      if(!this.ctx||this.ctx.state==='closed'){
        if(this.music)this.music.dispose();
        this.ctx=new AudioClass();this.master=this.ctx.createGain();this.master.gain.value=0;this.masterLevel=null;this.master.connect(this.ctx.destination);
        this.music=new GameAudio(this.ctx,this.ctx.destination);
        this.ctx.onstatechange=()=>{if(this.ctx.state==='running')this.updateMusic();};
      }
      if(this.ctx.state!=='running'&&this.resumeContext!==this.ctx){const ctx=this.ctx;this.resumeContext=ctx;Promise.resolve(ctx.resume()).then(()=>{if(this.ctx===ctx)this.updateMusic();}).catch(()=>{}).finally(()=>{if(this.resumeContext===ctx)this.resumeContext=null;});}
      this.updateMusic();
    }catch(_){}
  }
  updateMusic(){
    if(!this.ctx||!this.master)return;
    const active=this.pageActive&&!document.hidden;
    const level = preferences.sound && active ? 0.09 : 0;
    if(level!==this.masterLevel){this.masterLevel=level;this.master.gain.setTargetAtTime(level,this.ctx.currentTime,.025);}
    if(!this.music)return;
    const s=engine&&engine.state;
    let mode='menu';
    if(s&&campaign.mode!=='camp'){
      if(s.status==='won')mode='victory';else if(s.status==='dead')mode='defeat';
      else if(!screen){const enemies=visibleEnemies(s);mode=enemies.some(e=>e.type==='boss')?'boss':enemies.length?'battle':'explore';}
    }
    this.music.setState({enabled:!!preferences.sound&&!!preferences.music&&active,volume:preferences.musicVolume,mode});
    this.music.tick();
  }
  setPageActive(active){this.pageActive=active;if(active&&this.ctx&&!document.hidden)this.init();this.updateMusic();}
  tone(freq=220,duration=.12,type='sine',volume=.3,delay=0,endFreq=null){
    if(!preferences.sound||!this.pageActive||document.hidden||!this.ctx||this.ctx.state!=='running')return;
    try{const at=this.ctx.currentTime+delay;const osc=this.ctx.createOscillator();const gain=this.ctx.createGain();osc.type=type;osc.frequency.setValueAtTime(freq,at);if(endFreq)osc.frequency.exponentialRampToValueAtTime(Math.max(25,endFreq),at+duration);gain.gain.setValueAtTime(0,at);gain.gain.linearRampToValueAtTime(volume,at+.008);gain.gain.exponentialRampToValueAtTime(.001,at+duration);osc.connect(gain);gain.connect(this.master);osc.onended=()=>{osc.disconnect();gain.disconnect();};osc.start(at);osc.stop(at+duration+.02);}catch(_){}
  }
  play(type){
    if(type==='step'){this.tone(90,.05,'triangle',.10,0,50);return;}
    if(type==='hit'){this.tone(150,.10,'triangle',.7,0,45);this.tone(550,.045,'sawtooth',.08);}
    if(type==='cast'){this.tone(250,.24,'sine',.35,0,950);this.tone(630,.27,'triangle',.14,.05,300);}
    if(type==='heal'){[330,440,660].forEach((f,i)=>this.tone(f,.32,'sine',.3,i*.07));}
    if(type==='loot'){this.tone(660,.11,'sine',.2);this.tone(990,.2,'sine',.2,.07);}
    if(type==='death'){this.tone(155,.28,'triangle',.45,0,42);}
    if(type==='level'||type==='floor'){[220,330,440,660].forEach((f,i)=>this.tone(f,.6,'sine',.2,i*.08));}
    if(type==='win'){[293.665,369.994,440,587.33,739.989].forEach((f,i)=>this.tone(f,1,'triangle',.15,i*.13));}
  }
}
const sound = new AshenSound();

function toast(message){$('ash-toast').textContent=message;$('ash-toast').classList.add('show');toastUntil=performance.now()+2900;}
function visibleEnemies(s){return(s.enemies||[]).filter(e=>e.hp>0&&s.visible[e.y]&&s.visible[e.y][e.x]);}
function currentClass(){return classPresentation[(engine&&engine.state.player.classId)||selectedClass]||classPresentation.warden;}
function updateSoundButton(){
  for(const button of root.querySelectorAll('[data-action="sound"]')){button.textContent=button.id==='ash-sound-button'?(preferences.sound?'Звук: вкл.':'Звук: выкл.'):(preferences.sound?'Включены':'Выключены');button.setAttribute('aria-pressed',String(preferences.sound));}
  for(const button of root.querySelectorAll('[data-action="music"]')){button.textContent=button.dataset.musicLabel==='compact'?(preferences.music?'♫ Музыка: вкл.':'♫ Музыка: выкл.'):(preferences.music?'Включена':'Выключена');button.setAttribute('aria-pressed',String(preferences.music));}
  const slider=$('ash-music-volume');if(slider)slider.value=Math.round(preferences.musicVolume*100);
  const value=$('ash-music-volume-value');if(value)value.textContent=Math.round(preferences.musicVolume*100)+'%';
}
function toggleSound(){preferences.sound=!preferences.sound;storage.set(ASHEN_PREF_KEY,JSON.stringify(preferences));updateSoundButton();sound.init();sound.updateMusic();if(preferences.sound)sound.play('loot');}
function toggleMusic(){preferences.music=!preferences.music;if(preferences.music)preferences.sound=true;storage.set(ASHEN_PREF_KEY,JSON.stringify(preferences));updateSoundButton();sound.init();sound.updateMusic();}

function drawMinimap(s){
  const c=$('ash-minimap'),ctx=c.getContext('2d');if(!ctx||!s)return;const sx=c.width/s.w,sy=c.height/s.h;ctx.fillStyle='#09100d';ctx.fillRect(0,0,c.width,c.height);
  for(let y=0;y<s.h;y++)for(let x=0;x<s.w;x++){if(!s.seen[y][x])continue;ctx.fillStyle=s.tiles[y][x]===0?'#26342a':s.visible[y][x]?'#68735a':'#3b4938';ctx.fillRect(x*sx,y*sy,Math.ceil(sx),Math.ceil(sy));if(s.tiles[y][x]===2){ctx.fillStyle='#82c6bc';ctx.fillRect(x*sx,y*sy,sx,sy);}}
  for(const e of visibleEnemies(s)){ctx.fillStyle='#c66752';ctx.fillRect(e.x*sx,e.y*sy,sx,sy);}ctx.fillStyle='#f1d190';ctx.fillRect(s.player.x*sx-1,s.player.y*sy-1,sx+2,sy+2);
}

function renderDungeonHUD(){
  const s=engine?engine.state:demo&&demo.state;if(!s)return;const p=s.player;const cp=classPresentation[p.classId]||currentClass();
  $('ash-depth-number').textContent=`ГЛУБИНА ${ASHEN_ROMAN[s.floor-1]||s.floor} / V`;
  $('ash-depth-name').textContent=ASHEN_FLOORS[s.floor-1]||'Подземелье';$('ash-turn').textContent=`ХОД ${String(s.turn).padStart(3,'0')}`;
  $('ash-class-name').textContent=cp.name;$('ash-hero-mark').textContent=cp.symbol;$('ash-level').textContent=`${(s.stats&&s.stats.kills)||0} повержено · ${Math.round((p.crit||0)*100)}% крит. удара`;
  $('ash-hp-text').textContent=`${Math.max(0,p.hp)} / ${p.maxHp}`;$('ash-hp').style.width=clampUI(p.hp/p.maxHp*100,0,100)+'%';
  $('ash-mana-text').textContent=`${p.mana} / ${p.maxMana}`;$('ash-mana').style.width=clampUI(p.mana/p.maxMana*100,0,100)+'%';
  $('ash-level-label').textContent=`Уровень ${p.level}`;$('ash-xp-text').textContent=`${p.xp} / ${p.xpNext}`;$('ash-xp').style.width=clampUI(p.xp/p.xpNext*100,0,100)+'%';
  $('ash-attack').textContent=p.atk;$('ash-armor').textContent=p.armor;$('ash-gold').textContent=p.gold;
  $('ash-weapon').textContent=p.weaponName||'Походный клинок';$('ash-armor-name').textContent=p.armorName||'Плащ странника';$('ash-kills').textContent=`${(s.stats&&s.stats.kills)||0} побед`;
  $('ash-relics').innerHTML=(p.relics||[]).length?p.relics.map(r=>`<span class="ash-relic" title="${escapeHTML(typeof r==='object'?r.desc||'':'')}">${escapeHTML(typeof r==='object'?r.name||r.id:r)}</span>`).join(''):'<span class="ash-relic empty">Реликвии ещё не найдены.</span>';
  const entries=(s.log||[]).slice(-7).reverse();$('ash-log').innerHTML=entries.map(l=>`<p class="${escapeHTML(l.kind||'info')}"><span class="log-turn">${String(l.turn||0).padStart(3,'0')}</span>${escapeHTML(l.text)}</p>`).join('');
  const playing=!!engine&&s.status==='playing'&&!screen;
  $('ash-bolt').disabled=!playing||p.mana<3;$('ash-nova').disabled=!playing||p.mana<5;$('ash-potion').disabled=!playing||p.potions<1||p.hp>=p.maxHp;$('ash-interact').disabled=!playing;$('ash-wait').disabled=!playing;
  $('ash-potion-count').textContent=`${p.potions} в сумке`;
  const stairs=s.stairs&&p.x===s.stairs.x&&p.y===s.stairs.y;
  $('ash-interact-name').textContent=stairs?(s.floor===5?'Выход':'Спуститься'):'Действие';$('ash-interact-detail').textContent=stairs?(s.floor===5?'вернуть искру':'следующая глубина'):'лестница · объект';
  const danger=visibleEnemies(s).length;
  $('ash-world-hint').textContent=stairs?(s.floor===5?(s.bossDefeated?'Сердце ваше. Нажмите E, чтобы вернуться.':'Хранитель ещё жив. Сначала победите его.'):'E — спуститься глубже. R — закончить вылазку и вынести добычу.'):danger?`${danger} враг${danger===1?'':danger<5?'а':'ов'} в поле зрения. Удар — шаг в противника. Q — искра.`:s.turn<8?'Исследуйте свод. Двигайтесь стрелками или WASD. Удар — шаг в противника.':'Ищите лестницу, сундуки и святилища. Карта запоминает исследованное.';
  $('ash-seed-footer').textContent=`Семя: ${s.seed}${!storage.available?' · автосохранение недоступно':''}`;
  drawMinimap(s);
}

function castBolt(){
  if(!engine||screen)return;const s=engine.state,p=s.player;const candidates=visibleEnemies(s).filter(e=>Math.hypot(e.x-p.x,e.y-p.y)<=9).sort((a,b)=>(Math.abs(a.x-p.x)+Math.abs(a.y-p.y))-(Math.abs(b.x-p.x)+Math.abs(b.y-p.y)));
  const target=candidates.find(e=>e.id===selectedTarget)||candidates[0];if(!target){toast('Искре нужна видимая цель.');return;}selectedTarget=target.id;perform({type:'cast',skill:'bolt',x:target.x,y:target.y});
}

function knownPath(s,target){
  const p=s.player;const key=(x,y)=>y*s.w+x;const origin=key(p.x,p.y),dest=key(target.x,target.y);const queue=[origin],prev=new Map([[origin,null]]);const occupied=new Set((s.enemies||[]).filter(e=>e.hp>0).map(e=>key(e.x,e.y)));
  for(let i=0;i<queue.length;i++){const cur=queue[i];if(cur===dest)break;const x=cur%s.w,y=Math.floor(cur/s.w);for(const [dx,dy]of[[0,-1],[1,0],[0,1],[-1,0]]){const nx=x+dx,ny=y+dy,n=key(nx,ny);if(nx<0||ny<0||nx>=s.w||ny>=s.h||prev.has(n)||!s.seen[ny][nx]||s.tiles[ny][nx]===0||occupied.has(n))continue;prev.set(n,cur);queue.push(n);}}
  if(!prev.has(dest))return[];const path=[];let current=dest;while(current!==origin){path.push({x:current%s.w,y:Math.floor(current/s.w)});current=prev.get(current);}return path.reverse();
}

function updateHover(tile){
  hoverTile=tile;const box=$('ash-hover');if(!engine||screen||!tile){box.hidden=true;return;}const s=engine.state;if(!s.visible[tile.y]||!s.visible[tile.y][tile.x]){box.hidden=true;return;}
  const enemy=s.enemies.find(e=>e.x===tile.x&&e.y===tile.y&&e.hp>0);if(enemy){box.innerHTML=`<b>${escapeHTML(enemy.name)}</b><span>${enemy.hp}/${enemy.maxHp} жизни · атака ${enemy.atk} · броня ${enemy.armor||0}${enemy.intent?'<br>Готовит сильную атаку!':''}</span>`;box.className='ash-hover danger';box.hidden=false;return;}
  const f=s.features.find(f=>f.x===tile.x&&f.y===tile.y&&!f.used);if(f){const names={chest:'Древний сундук',fountain:'Последняя вода',shrine:'Святилище искры'};box.innerHTML=`<b>${names[f.type]||'Находка'}</b><span>Подойдите или нажмите E рядом.</span>`;box.className='ash-hover';box.hidden=false;return;}box.hidden=true;
}

function toggleMap(){if(!engine||screen||campaign.mode!=='run')return;mapMode=!mapMode;moveQueue=[];toast(mapMode?'Исследованная карта. Tab — вернуться к герою.':'Следуем за искрой.');}


// Campaign UI has one owner of persistence; renderers never change resources.
const npcIcons = {
  warden:'<path d="M14 3c3 6-2 7 2 10 0-4 4-5 4-8 6 8 5 17-4 19C7 24 3 18 6 12c1 3 3 4 4 4-2-6 4-8 4-13Z"/>',
  smith:'<path d="m8 3 10 7-3 4L5 7zM14 12 5 25M3 25h21M7 19h14l-3 6H9zM20 4l4 4"/>',
  herbalist:'<path d="M14 26V12M14 20C5 21 2 15 3 10c7-1 12 3 11 10ZM14 15c0-8 5-12 11-11 1 7-3 12-11 11ZM14 13C7 9 9 3 12 1c4 2 6 8 2 12Z"/>',
  archivist:'<path d="M14 7C9 4 5 4 2 6v18c5-2 8-1 12 1 4-2 7-3 12-1V6c-3-2-7-2-12 1ZM14 7v18M6 10l4 1M6 14l4 1M18 11l4-1M18 15l4-1"/>'
};
const resourceIds = ['gold','wood','ore','herb','crystal'];
let campView = null;
const blockedMovementKeys = new Set();
const movementCodes = ['ArrowUp','KeyW','ArrowDown','KeyS','ArrowLeft','KeyA','ArrowRight','KeyD'];
const npcById = id => ASHEN_NPCS.find(n => n.id===id);
const resourceDef = id => ASHEN_RESOURCES[id] || {name:id,symbol:'·',color:'#b6bf9c'};
const questStates = {available:'Можно принять',active:'В работе',ready:'Можно сдать',claimed:'Выполнено',locked:'Пока закрыто'};

function resourcesHTML(values={},full=false,available=null){
  const shown=resourceIds.filter(id=>full||Number(values[id])>0);
  if(!shown.length)return '<span class="ash-bonus empty">Пока ничего.</span>';
  if(full)return shown.map(id=>{const d=resourceDef(id);return `<div class="ash-resource" style="--resource-color:${escapeHTML(d.color)}"><span class="symbol" aria-hidden="true">${escapeHTML(d.symbol)}</span><b>${Number(values[id])||0}</b><small title="${escapeHTML(d.name)}">${id==='herb'?'Трава':escapeHTML(d.name)}</small></div>`;}).join('');
  return `<div class="ash-material-line">${shown.map(id=>{const d=resourceDef(id),owned=Number(available&&available[id])||0,needed=Number(values[id])||0,missing=available&&owned<needed;return `<span title="${escapeHTML(d.name)}" style="--resource-color:${missing?'#dc9583':escapeHTML(d.color)}">${escapeHTML(d.symbol)} ${needed}<small> ${escapeHTML(d.name)}</small>${available?`<small class="ash-resource-available">В запасе ${owned}${missing?' · не хватает '+(needed-owned):''}</small>`:''}</span>`;}).join('')}</div>`;
}
function resourcesText(values={}){return resourceIds.filter(id=>Number(values[id])>0).map(id=>`${Number(values[id])} ${resourceDef(id).name.toLowerCase()}`).join(', ')||'нет';}
function bonusesHTML(b){
  const labels={hp:'к здоровью',mana:'к мане',atk:'к атаке',armor:'к броне',potions:'к зельям',spellPower:'к магии'};
  const parts=Object.entries(labels).filter(([id])=>Number(b[id])>0).map(([id,label])=>`<span class="ash-bonus">+${Number(b[id])} ${label}</span>`);
  return `<div class="ash-bonus-pills">${parts.join('')||'<span class="ash-bonus empty">Восстановите постройки, чтобы укрепить будущих героев.</span>'}</div>`;
}
function saveMessage(){
  if(saveState==='saved')return 'Кампания сохранена в этом браузере.';
  if(saveState==='blocked'&&persistenceIssue==='conflict')return 'Другая вкладка изменила сохранение. Ваш текущий прогресс пока только здесь; в меню можно выгрузить его или выбрать общую версию.';
  if(saveState==='blocked')return 'Старое сохранение не удалось прочитать. Текущая игра пока только в этой вкладке; выгрузите её в файл.';
  if(saveState==='memory')return 'Прогресс пока только в этой вкладке. Автосохранение не удалось — выгрузите кампанию в файл.';
  return 'Кампания сохранится после первого действия.';
}
function renderSaveStatus(){
  const status=$('ash-save-status');
  status.textContent=saveState==='saved'?'Кампания сохранена':saveState==='unknown'?'Лагерь ждёт вас':'Прогресс только во вкладке';
  status.classList.toggle('unsaved',saveState==='memory'||saveState==='blocked');
  status.title=saveMessage();
  for(const el of root.querySelectorAll('[data-save-note]')){el.textContent=saveMessage();el.classList.toggle('unsaved',saveState==='memory'||saveState==='blocked');}
}
function initCampControls(){
  $('ash-npc-list').innerHTML=ASHEN_NPCS.map((npc,i)=>`<button class="ash-npc" data-npc="${escapeHTML(npc.id)}" aria-label="${escapeHTML(npc.name)}, ${escapeHTML(npc.role)}" style="--npc-color:${escapeHTML(npc.color)}"><span class="ash-npc-portrait" aria-hidden="true"><svg viewBox="0 0 28 28">${npcIcons[npc.id]||''}</svg></span><span><strong>${escapeHTML(npc.name)}</strong><small>${escapeHTML(npc.role)}</small><small class="ash-npc-status" data-npc-status></small></span><span class="ash-npc-rank"><b data-npc-rank>—</b><span>${i+1}</span></span></button>`).join('');
}
function renderCampHUD(){
  const quests=campaign.getQuestViews(),buildings=campaign.getBuildingViews(),meta=campaign.meta;
  campView={buildings,quests,npcs:ASHEN_NPCS,classId:selectedClass};
  $('ash-depth-number').textContent='УБЕЖИЩЕ · ПОСТОЯННЫЙ ПРОГРЕСС';
  $('ash-depth-name').textContent='Лагерь последней искры';
  $('ash-turn').textContent=`ВЫЛАЗОК ${meta.stats.runs||0}`;
  $('ash-world-hint').textContent='Выберите жителя в лагере или справа. Задания открывают новые постройки.';
  $('ash-bank-resources').innerHTML=resourcesHTML(meta.resources,true);
  $('ash-camp-bonuses').innerHTML=bonusesHTML(campaign.getBonuses());
  $('ash-building-total').textContent=`${Object.values(meta.buildings).reduce((a,b)=>a+(Number(b)||0),0)} / 12`;
  const ready=quests.filter(q=>q.status==='ready'),active=quests.filter(q=>q.status==='active');
  $('ash-camp-guidance').textContent=ready.length?`Жители ждут вас: можно сдать ${ready.length} заданий. Награды и допуски выдаёт заказчик.`:active.length?`В журнале ${active.length} поручений. Их можно выполнять одновременно, за несколько вылазок.`:'У каждого жителя есть поручение — и постройка, которую можно восстановить с вашей помощью.';
  for(const npc of ASHEN_NPCS){
    const button=root.querySelector(`[data-npc="${npc.id}"]`),list=quests.filter(q=>q.npc===npc.id),b=buildings.find(b=>b.npc===npc.id);
    const q=list.find(q=>q.status==='ready')||list.find(q=>q.status==='active')||list.find(q=>q.status==='available');
    const status=button.querySelector('[data-npc-status]');status.className='ash-npc-status '+(q?q.status:'claimed');
    status.textContent=q?(q.status==='active'?`${q.progress}/${q.target} · ${q.name}`:questStates[q.status]):'Все поручения выполнены';
    button.querySelector('[data-npc-rank]').textContent=b&&b.level?ASHEN_ROMAN[b.level-1]:'—';
    button.title=`${npc.name} · ${b?b.name:''} ${b?b.level:0}/3`;
  }
  $('ash-return-rule').textContent=campaign.lastRun?`${({return:'Вылазка завершена',victory:'Владыка повержен',death:'Вы снова у костра',abandon:'Вылазка оставлена'})[campaign.lastRun.outcome]||'Вы вернулись'}. Банк и постройки сохраняются; следующий герой начнёт с уровня 1.`:'Возьмите задания у жителей перед первой вылазкой. Начальные поручения выполняются на первой глубине.';
  $('ash-seed-footer').textContent=saveState==='saved'?'Постройки остаются. Каждая вылазка — новая жизнь.':saveMessage();
}
function renderHUD(){
  const camp=campaign.mode==='camp';
  root.classList.toggle('is-camp',camp);root.classList.toggle('reduced-motion',!!preferences.reduceMotion);
  $('ash-camp-sidebar').hidden=!camp;$('ash-dungeon-sidebar').hidden=camp;
  $('ash-camp-actions').hidden=!camp;$('ash-dungeon-commands').hidden=camp;$('ash-run-tools').hidden=camp;
  root.querySelector('.ash-mini-wrap').hidden=camp;
  root.querySelector('.ash-dpad').hidden=camp;
  canvas.setAttribute('aria-label',camp?'Лагерь. Выберите жителя на карте или кнопками. 1–4 — жители, E — новая вылазка.':'Подземелье. WASD/стрелки — движение и удар. R — вернуться у входа или лестницы.');
  if(camp)renderCampHUD();
  else if(engine){
    renderDungeonHUD();
    const s=engine.state,bag={gold:s.player.gold,...s.player.materials};
    $('ash-run-resources').innerHTML=resourcesHTML(bag);
    const can=campaign.canReturn();$('ash-return').disabled=!!screen||campaign.mode!=='run'||!can.ok;$('ash-return').title=can.reason||'Закончить вылазку и доставить добычу в лагерь.';
    $('ash-return-rule').textContent=can.ok?'R — безопасно вернуться с добычей. Уровень и дары текущей вылазки будут сброшены.':can.reason;
    const quests=campaign.getQuestViews();const count=quests.filter(q=>['active','ready'].includes(q.status)).length;
    $('ash-run-quest-count').textContent=count?` · ${count}`:'';
    $('ash-seed-footer').textContent=`Семя: ${s.seed}${saveState!=='saved'?' · '+saveMessage():''}`;
  }
  $('ash-controls-footer').innerHTML=camp?'<kbd>1</kbd>–<kbd>4</kbd> жители · <kbd>E</kbd> вылазка · <kbd>J</kbd> журнал · <kbd>Esc</kbd> меню':'<kbd>WASD</kbd> движение и удар · <kbd>Q</kbd>/<kbd>F</kbd> магия · <kbd>R</kbd> в лагерь · <kbd>J</kbd> задания';
  renderSaveStatus();
}
function setScreen(value){
  if(value&&!screen)modalOrigin=document.activeElement;
  screen=value;moveQueue=[];for(const code of movementCodes)blockedMovementKeys.add(code);hoverTile=null;campHover=null;$('ash-hover').hidden=true;
  overlay.hidden=!value;root.classList.remove('in-menu');
  const layout=root.querySelector('.ash-layout');if(layout)layout.inert=!!value;
  const top=root.querySelector('.ash-top');if(top)top.inert=!!value;
  if(!value){overlay.innerHTML='';if(modalOrigin&&root.contains(modalOrigin)&&!modalOrigin.disabled){modalOrigin.focus({preventScroll:true});}else canvas.focus({preventScroll:true});modalOrigin=null;}
  renderHUD();sound.updateMusic();
}
function mountDialog(html,focusKey=null){
  const previousTop=overlay.scrollTop;
  overlay.innerHTML=html;
  const heading=overlay.querySelector('h2');overlay.setAttribute('aria-label',heading?heading.textContent.trim():'Меню игры');
  const key=focusKey&&String(focusKey).replace(/[^a-zA-Z0-9_-]/g,'');
  let focus=key&&overlay.querySelector(`[data-focus="${key}"]`);
  if(!focus||focus.disabled)focus=overlay.querySelector('[data-default-focus]')||overlay.querySelector('button:not([disabled]), input:not([disabled])');
  if(focus)focus.focus({preventScroll:true});
  overlay.scrollTop=focusKey?previousTop:0;renderSaveStatus();updateSoundButton();
}
function showCamp(){
  if(campaign.mode==='result'){showEnd();return;}
  if(campaign.mode!=='camp'){resumeGame();return;}
  engine=null;endedAt=0;selectedTarget=null;mapMode=false;setScreen('');renderHUD();
}
function showTitle(){showCamp();}
function randomSeed(){try{const data=new Uint32Array(1);crypto.getRandomValues(data);return data[0].toString(36).toUpperCase();}catch(_){return(Date.now().toString(36)+Math.random().toString(36).slice(2,5)).toUpperCase();}}
function showDepart(focusKey=null){
  if(campaign.mode!=='camp')return;
  const field=$('ash-seed-input');if(field)lastSeed=field.value;
  const b=campaign.getBonuses(),taken=campaign.getQuestViews().filter(q=>['active','ready'].includes(q.status)).length;
  setScreen('depart');campRenderer.visit('portal');
  mountDialog(`<section class="ash-dialog wide"><div class="ash-dialog-top"><div><p class="ash-kicker">Новая вылазка · пять глубин</p><h2>Кто понесёт искру?</h2></div><button class="ash-dialog-close" data-action="resume">В лагерь <kbd>Esc</kbd></button></div><p class="lead">Каждый герой начинает с первого уровня. Постройки лагеря усиливают его ещё до входа в подземелье.</p><div class="ash-classes">${ASHEN_CLASSES.map(c=>{const p=classPresentation[c.id];return `<button class="ash-class ${c.id===selectedClass?'selected':''}" data-class="${c.id}" data-focus="class-${c.id}" aria-pressed="${c.id===selectedClass}"><span class="ash-class-symbol" aria-hidden="true">${p.symbol}</span><h3>${p.name}</h3><p>${p.desc}</p><span class="ash-class-trait">${p.trait}</span><div class="ash-expedition-stats">${c.hp+b.hp} жизни · ${c.atk+b.atk} атаки<br>${c.armor+b.armor} брони · ${c.mana+b.mana} маны</div></button>`;}).join('')}</div><div style="margin-top:18px">${bonusesHTML(b)}</div><label class="ash-seed">Семя подземелья <input id="ash-seed-input" maxlength="40" autocomplete="off" spellcheck="false" placeholder="случайное" value="${escapeHTML(lastSeed)}"></label><p class="ash-menu-note large">${taken?`Принято поручений: ${taken}. Журнал доступен в подземелье по J.`:'Поручений пока нет. Лучше сначала поговорить с жителями лагеря.'}<br>Вернуться с добычей можно у входа на этаж или на лестнице, если не видно врагов.</p><div class="ash-dialog-actions"><button class="ash-primary" data-action="new" data-default-focus>Войти в подземелье →</button><button class="ash-secondary" data-action="resume">Ещё подготовиться</button></div></section>`,focusKey);
}
function startRun(options={}){
  if(campaign.mode!=='camp')return false;
  const seedInput=$('ash-seed-input');if(seedInput)lastSeed=seedInput.value.trim();
  if(!options||typeof options!=='object')options={};
  const ok=campaign.startRun({seed:options.seed||lastSeed||randomSeed(),classId:options.classId||selectedClass});
  if(!ok){toast(campaign.notice);return false;}
  engine=campaign.engine;selectedClass=engine.state.player.classId;selectedTarget=null;selectedNpc=null;mapMode=false;moveQueue=[];endedAt=0;sessionRevision++;
  renderer.reset();setScreen('');canvas.focus({preventScroll:true});sound.init();sound.play('floor');saveRun();renderHUD();
  toast('Задания — J. Шаг во врага — удар. Вынесите материалы и вернитесь к жителям.');return true;
}
function requestNewRun(){return startRun();}
function markSaveConflict(){
  persistenceBlocked=true;persistenceIssue='conflict';saveState='blocked';importTicket++;moveQueue=[];
  renderSaveStatus();toast('Другая вкладка обновила кампанию. Ваши изменения пока здесь — откройте меню, чтобы выбрать сохранение.');
}
function resetSaveBaseline(){
  const current=storage.read(ASHEN_SAVE_KEY);hasSaveBaseline=current.ok;observedSaveText=current.value;return current;
}
function saveRun(){
  if(persistenceBlocked){saveState='blocked';renderSaveStatus();return false;}
  let text;try{text=campaign.serialize();}catch(_){saveState='memory';renderSaveStatus();return false;}
  const current=storage.read(ASHEN_SAVE_KEY);
  if(!current.ok){saveState='memory';renderSaveStatus();if(!saveWarningShown){saveWarningShown=true;toast('Автосохранение недоступно. В меню можно выгрузить всю кампанию в файл.');}return false;}
  // This comparison catches observed stale writes; localStorage has no atomic
  // cross-process compare-and-swap. Never silently replace a newly seen save.
  if(hasSaveBaseline?current.value!==observedSaveText:current.value!==null){markSaveConflict();return false;}
  hasSaveBaseline=true;observedSaveText=current.value;
  if(saveState==='saved'&&text===lastSavedText)return true;
  const ok=storage.set(ASHEN_SAVE_KEY,text);saveState=ok?'saved':'memory';
  if(ok){lastSavedText=text;observedSaveText=text;saveWarningShown=false;}else if(!saveWarningShown){saveWarningShown=true;toast('Автосохранение недоступно. В меню можно выгрузить всю кампанию в файл.');}
  renderSaveStatus();return ok;
}
function installCampaign(restored){
  campaign=restored;engine=campaign.engine;sessionRevision++;importTicket++;persistenceBlocked=false;persistenceIssue='';lastSavedText=null;
  if(engine)selectedClass=engine.state.player.classId;
  selectedTarget=null;selectedNpc=null;hoverTile=null;campHover=null;moveQueue=[];mapMode=false;endedAt=0;renderer.reset();campRenderer.reset();
  if(campaign.mode==='camp')showCamp();else if(campaign.mode==='result')showEnd();else if(engine.state.status==='choice')showChoice();else setScreen('');
}
function loadRun(text=null,expectedSave=null){
  try{
    const current=storage.read(ASHEN_SAVE_KEY);
    if(expectedSave){
      if(expectedSave.ok&&!current.ok){toast('Не удалось проверить общее сохранение после чтения файла. Текущая игра не изменена; выберите файл ещё раз.');return false;}
      if(current.ok&&(expectedSave.ok?current.value!==expectedSave.value:current.value!==null)){markSaveConflict();showPause();return false;}
    }
    if(text===null&&!current.ok){toast('Хранилище браузера недоступно. Текущая игра не изменена; можно загрузить сохранение из файла.');return false;}
    const candidate=text===null?(current.value??storage.get(ASHEN_LEGACY_SAVE_KEY)):text;
    if(candidate===null){toast('Сохранённой кампании пока нет.');return false;}
    const restored=GameEngine.fromSave(candidate);
    if(!restored)throw new Error('Invalid campaign');
    // An explicit valid import/load is the user's selection of the replacement
    // campaign. Invalid input never updates this baseline or the live session.
    hasSaveBaseline=current.ok;observedSaveText=current.value;
    installCampaign(restored);saveRun();renderHUD();sound.init();toast('Кампания загружена: лагерь, задания и текущая вылазка восстановлены.');return true;
  }catch(_){toast('Не удалось открыть сохранение: файл повреждён или несовместим. Текущая игра не изменена.');return false;}
}
function showPause(){
  saveRun();setScreen('pause');
  const camp=campaign.mode==='camp',conflict=persistenceIssue==='conflict';
  const persistenceWarning=!persistenceBlocked?'':conflict?'<div class="ash-storage-warning">Общее сохранение изменилось в другой вкладке. Текущая игра осталась здесь. Сначала можно выгрузить её в отдельный файл; загрузка общей версии заменит текущую игру.<div class="ash-dialog-actions"><button class="ash-secondary" data-action="load">Загрузить версию другой вкладки</button><button class="ash-link" data-action="replace-save">Сохранить текущую вместо общей</button></div></div>':'<div class="ash-storage-warning">Непрочитанное старое сохранение пока не перезаписывается. Можно загрузить другой файл или явно сохранить текущую кампанию вместо него.<br><button class="ash-link" data-action="replace-save">Сохранить текущую кампанию вместо старой</button></div>';
  mountDialog(`<section class="ash-dialog"><p class="ash-kicker">${camp?'Лагерь последней искры':'Пауза'}</p><h2>Огонь подождёт.</h2><p class="lead ash-save-note" data-save-note>${saveMessage()}</p>${persistenceWarning}<div class="ash-toggle"><span>Все звуки</span><button data-action="sound" aria-pressed="${preferences.sound}"></button></div><div class="ash-toggle"><span>Музыка<small>Поход последней искры</small></span><button data-action="music" aria-pressed="${preferences.music}"></button></div><div class="ash-music-volume"><label for="ash-music-volume">Громкость музыки</label><input type="range" id="ash-music-volume" min="0" max="100" step="5" value="${Math.round(preferences.musicVolume*100)}" aria-describedby="ash-music-volume-value"><output id="ash-music-volume-value">${Math.round(preferences.musicVolume*100)}%</output></div><div class="ash-toggle"><span>Спокойная анимация</span><button data-action="motion" aria-pressed="${preferences.reduceMotion}">${preferences.reduceMotion?'Включена':'Выключена'}</button></div><div class="ash-dialog-actions"><button class="ash-primary" data-action="resume" data-default-focus>Продолжить <kbd>Esc</kbd></button><button class="ash-secondary" data-action="help">Путеводитель</button></div><div class="ash-divider"></div><div class="ash-dialog-actions"><button class="ash-secondary" data-action="export">Выгрузить кампанию</button><button class="ash-secondary" data-action="fresh-campaign">Новая кампания</button><button class="ash-secondary" data-action="import">Загрузить из файла</button>${campaign.mode==='run'?'<button class="ash-secondary ash-danger" data-action="abandon">Оставить вылазку</button>':''}</div><p class="ash-menu-note large">Файл сохранения включает лагерь и активную вылазку.<br>${camp?'Выбирайте жителей кнопками или прямо на карте.':`Семя: ${escapeHTML(engine.state.seed)} · глубина ${engine.state.floor}/5 · ход ${engine.state.turn}`}</p></section>`);
}
function resumeGame(){
  if(campaign.mode==='camp')showCamp();else if(campaign.mode==='result')showEnd();else if(engine&&engine.state.status==='choice')showChoice();else setScreen('');
}
function showHelp(){
  if(screen!=='help')returnScreen=screen;setScreen('help');
  mountDialog(`<section class="ash-dialog wide"><p class="ash-kicker">Путеводитель странника</p><h2>Сначала — искра. Потом — дом.</h2><p class="lead">Вылазка даёт опыт герою и надежду лагерю. Сильнее становятся оба — но по разным правилам.</p><div class="ash-help-grid"><section><h3>Лагерь и поручения</h3><ul><li>Поговорите с четырьмя жителями. Кнопки 1–4 открывают их диалоги.</li><li>Задание нужно принять. Несколько поручений можно выполнять одновременно и за несколько вылазок.</li><li>Боевые и исследовательские цели сохраняют прогресс даже при гибели. Доставку материалов засчитывают после возвращения с добычей.</li><li>Готовые задания сдавайте заказчику. Каждое открывает новый уровень его постройки.</li></ul></section><section><h3>Что остаётся, а что исчезает</h3><ul><li>Остаются: здания, их уровни, банк лагеря, принятые и сданные задания.</li><li>Каждый герой начинает с уровня 1, без опыта, найденного оружия и временных даров. Бонусы зданий действуют сразу.</li><li>При гибели или оставлении вылазки теряется вся её добыча. Уже лежащие в банке ресурсы не расходуются.</li><li>Сдача задания на доставку не отнимает материалы. Стройка отдельно списывает показанную стоимость.</li></ul></section><section><h3>Как вернуться живым</h3><p>На каждом этаже запоминается вход — светящийся знак возврата. Встаньте на него или на лестницу и нажмите R, когда не видно врагов. Вся добыча попадёт в банк. На лестнице E ведёт глубже; на пятой глубине победите Владыку углей и выйдите через лестницу. Начальный вход тоже позволяет уйти: вы сами выбираете длину вылазки.</p></section><section><h3>Управление в подземелье</h3><div class="ash-help-keys"><div><span>Шаг / удар по соседнему врагу</span><kbd>WASD / стрелки</kbd></div><div><span>Искра / Кольцо пепла</span><kbd>Q / F</kbd></div><div><span>Лечебное зелье</span><kbd>H</kbd></div><div><span>Лестница / соседний объект</span><kbd>E</kbd></div><div><span>Вернуться с добычей</span><kbd>R</kbd></div><div><span>Журнал / карта / пауза</span><kbd>J / Tab / Esc</kbd></div><div><span>Подождать ход</span><kbd>Пробел</kbd></div></div></section><section><h3>Бой и исследования</h3><p>Мир пошаговый: пока вы думаете, враги стоят. За опыт выбирайте дары текущей вылазки. Ожидание возвращает ману, но даёт ход противникам. Покидайте зоны предупреждения о взрывах. Сундуки, святилища и предметы срабатывают при входе на клетку; E также достигает соседних объектов.</p></section><section><h3>Материалы и управление мышью</h3><p>Дерево, руда и трава встречаются с первого этажа. Кристаллы редки на первом этаже и гарантированно встречаются глубже. Нажмите на исследованную клетку для движения: при появлении врага герой остановится. Клик по врагу выбирает цель для Q. На телефоне используйте крестовину и кнопки. В лагере достаточно выбрать жителя на карте или карточке.</p></section><section class="full"><h3>Как сохранить лагерь</h3><p>Одна запись хранит всю кампанию: здания, задания, банк и текущую вылазку. После каждого действия игра пытается сохранить её в этом браузере. Если запись не удалась, интерфейс прямо сообщает, что прогресс пока во вкладке. Выгрузка и загрузка JSON доступны в меню; можно импортировать сохранение старого «Пепельного свода». Один HTML содержит всю графику, анимацию и музыку. Для звука сначала нажмите любую кнопку; интернет не требуется.</p></section></div><div class="ash-dialog-actions"><button class="ash-primary" data-action="close-help" data-default-focus>Вернуться к игре →</button></div></section>`);
}
function closeHelp(){const previous=returnScreen;returnScreen='';if(previous==='pause')showPause();else if(previous==='npc'&&selectedNpc)showNpc(selectedNpc);else if(previous==='depart')showDepart();else if(previous==='journal')showQuests();else resumeGame();}
function questCard(q,interactive=true){
  const short=['locked','claimed'].includes(q.status),owner=npcById(q.npc);
  return `<article class="ash-quest-card ${escapeHTML(q.status)}">${!interactive?`<span class="ash-journal-owner">${escapeHTML(owner?owner.name:q.npc)}</span>`:''}<div class="ash-quest-title"><h4>${escapeHTML(q.name)}</h4><small>${questStates[q.status]||''}</small></div>${short?`<p>${q.status==='claimed'?'Допуск получен.':escapeHTML(q.nextPrerequisiteText||q.unlockText||q.description)}</p>`:`<p>${escapeHTML(q.description)}</p><div class="ash-quest-goal">${escapeHTML(q.objectiveText)} <b>${q.progress} / ${q.target}</b></div><div class="ash-quest-progress" role="progressbar" aria-label="${escapeHTML(q.name)}" aria-valuenow="${q.progress}" aria-valuemin="0" aria-valuemax="${q.target}"><i style="width:${clampUI(q.progress/q.target*100,0,100)}%"></i></div><div class="ash-quest-reward">Награда: ${resourcesHTML(q.reward)}<p>${escapeHTML(q.unlockText||'')}</p></div>${interactive&&['available','ready'].includes(q.status)?`<button class="${q.status==='ready'?'ash-primary':'ash-secondary'}" data-quest="${escapeHTML(q.id)}" data-quest-action="${q.status==='ready'?'claim':'accept'}" data-focus="quest-${escapeHTML(q.id)}">${q.status==='ready'?'Сдать задание →':'Принять поручение'}</button>`:''}${!interactive&&q.status==='ready'?'<p class="ash-readonly-note">За наградой вернитесь к заказчику в лагерь.</p>':''}`}</article>`;
}
function showNpc(id,focusKey=null){
  if(campaign.mode!=='camp')return false;
  const npc=npcById(id);if(!npc)return false;selectedNpc=id;campRenderer.visit(id);setScreen('npc');
  const quests=campaign.getQuestViews(id),building=campaign.getBuildingViews(id)[0];
  const next=building&&building.level<building.maxLevel;
  const build=building?`<section><h3 class="ash-section-label">Восстановление лагеря</h3><div class="ash-build-panel"><span class="ash-camp-eyebrow">${building.level?`Уровень ${building.level} / ${building.maxLevel}`:'Место для постройки'}</span><h3>${escapeHTML(building.name)}</h3><div class="ash-build-levels" aria-label="Уровень ${building.level} из ${building.maxLevel}">${Array.from({length:building.maxLevel},(_,i)=>`<i class="${i<building.level?'filled':''}"></i>`).join('')}</div><p>${escapeHTML(building.description)}</p><div class="ash-build-gain"><small>Уже действует</small><strong>${escapeHTML(building.bonusText||'Пока нет бонусов.')}</strong>${next?`<small style="margin-top:12px">${building.level?'Следующий уровень':'После строительства'}</small><strong>${escapeHTML(building.nextBonusText||'')}</strong>`:''}</div>${next?`<p class="ash-build-gate">${escapeHTML(building.gateText)}</p><div class="ash-build-cost"><small class="ash-section-label">Стоимость</small>${resourcesHTML(building.cost,false,campaign.meta.resources)}</div><button class="ash-primary" data-building="${escapeHTML(building.id)}" data-building-level="${building.level}" data-focus="building-${escapeHTML(building.id)}" ${building.canUpgrade?'':'disabled'}>${building.level?'Улучшить до уровня '+(building.level+1):'Построить'}</button><p class="ash-build-reason">${escapeHTML(building.reason||'Все условия выполнены. Ресурсы будут списаны из банка.')}</p>`:'<p>Постройка полностью восстановлена. Её сила поможет каждому следующему герою.</p>'}<p class="ash-readonly-note">Материалы берутся из запаса лагеря. Бонус применяется к следующей вылазке и сохраняется после гибели.</p></div></section>`:'';
  mountDialog(`<section class="ash-dialog npc-dialog"><div class="ash-dialog-top"><div><p class="ash-kicker">${escapeHTML(npc.role)}</p><h2>${escapeHTML(npc.name)}</h2></div><button class="ash-dialog-close" data-action="resume" data-focus="npc-close" data-default-focus>К костру <kbd>Esc</kbd></button></div><blockquote class="ash-npc-greeting">${escapeHTML(npc.greeting)}</blockquote><div class="ash-npc-columns"><section><h3 class="ash-section-label">Поручения жителя</h3>${quests.map(q=>questCard(q)).join('')}</section>${build}</div><p class="ash-dialog-save" data-save-note>${saveMessage()}</p></section>`,focusKey);
  return true;
}
function showQuests(){
  if(screen!=='journal')journalReturn=screen;
  setScreen('journal');
  const qs=campaign.getQuestViews(),current=qs.filter(q=>['active','ready'].includes(q.status)),claimed=qs.filter(q=>q.status==='claimed').length;
  mountDialog(`<section class="ash-dialog wide"><div class="ash-dialog-top"><div><p class="ash-kicker">Поручения лагеря · выполнено ${claimed} / ${qs.length}</p><h2>Обещания, которые греют.</h2></div><button class="ash-dialog-close" data-action="resume" data-default-focus>Назад <kbd>Esc</kbd></button></div><p class="lead">Принятые поручения выполняются параллельно. Боевые и исследовательские цели сохраняют прогресс при гибели; материалы для доставки нужно вынести живым.</p>${current.length?`<div class="ash-journal-list">${current.map(q=>questCard(q,false)).join('')}</div>`:'<div class="ash-empty-journal">Сейчас нет активных поручений. Поговорите с жителями в лагере: их задания открывают новые постройки и улучшения.</div>'}${campaign.mode==='camp'?`<div class="ash-dialog-actions">${ASHEN_NPCS.map(n=>`<button class="ash-secondary" data-npc="${n.id}">${escapeHTML(n.name)}</button>`).join('')}</div>`:''}<p class="ash-menu-note large">За сданный квест вы получаете награду и допуск к постройке. Сдача не отнимает принесённые материалы; строительство оплачивается отдельно.</p></section>`);
}
function showChoice(){
  if(!engine||engine.state.status!=='choice'){resumeGame();return;}
  setScreen('choice');const s=engine.state;const icons={vitality:'♡',strength:'†',armor:'◇',focus:'✧',sorcery:'ϟ',precision:'⌖',evasion:'⌁',vampire:'♧'};
  mountDialog(`<section class="ash-dialog wide"><p class="ash-kicker">Уровень ${s.player.level} · дар текущей вылазки</p><h2>Искра становится сильнее.</h2><p class="lead">Выберите один дар. Он действует до возвращения в лагерь или гибели героя.</p><div class="ash-choice-grid">${s.choices.map((c,i)=>`<button class="ash-choice" data-choice="${escapeHTML(c.id)}"><span aria-hidden="true">${icons[c.id]||'✦'}</span><kbd style="float:right">${i+1}</kbd><b>${escapeHTML(c.name)}</b><p>${escapeHTML(c.desc)}</p></button>`).join('')}</div></section>`);
}
function choosePerk(id){
  if(!engine||engine.state.status!=='choice')return false;
  if(!campaign.choose(id))return false;
  sessionRevision++;processEvents(engine.state.events||[]);sound.play('level');saveRun();
  if(engine.state.status==='choice')showChoice();else setScreen('');renderHUD();return true;
}
function showEnd(){
  if(campaign.mode!=='result'||!engine){resumeGame();return;}
  endedAt=0;setScreen('end');const s=engine.state,r=campaign.lastRun,win=r.outcome==='victory';
  mountDialog(`<section class="ash-dialog"><p class="ash-kicker">${win?'Сердце свода возвращено':'Вылазка закончилась'}</p><h2>${win?'Вы принесли рассвет.':'Костёр ещё горит.'}</h2><p class="lead">${win?'Владыка углей пал. Вся добыча доставлена в лагерь. Жители ждут ваших историй — и выполненных поручений.':'Этот герой больше не вернётся в свод. Но лагерь выстоял: постройки, банк и боевой прогресс принятых заданий остались.'}</p><div class="ash-result-grid"><div><b>${s.floor}<small style="font-size:14px"> / 5</small></b><span>Глубина</span></div><div><b>${s.stats.kills||0}</b><span>Побеждено врагов</span></div><div><b>${s.player.level}</b><span>Уровень вылазки</span></div></div><div class="ash-summary-strip"><h3>${win?'Доставлено в лагерь':'Потеряно в подземелье'}</h3>${resourcesHTML(win?r.earned:r.lost)}<p>${win?'Можно сдать задания заказчикам.':'Доставка материалов не засчитана. Запас лагеря не затронут.'}</p></div><p class="ash-menu-note large">Следующая вылазка начнётся с уровня 1 и бонусами ваших построек.<br>Семя: ${escapeHTML(s.seed)}</p><div class="ash-dialog-actions"><button class="ash-primary" data-action="return" data-default-focus>Вернуться к жителям →</button><button class="ash-secondary" data-action="export">Выгрузить кампанию</button><button class="ash-secondary" data-action="fresh-campaign">Новая кампания</button></div><p class="ash-dialog-save" data-save-note></p></section>`);
}
function returnToCamp(){
  if(campaign.mode==='camp')return false;
  if(!campaign.returnToCamp()){toast(campaign.notice||campaign.canReturn().reason);return false;}
  sessionRevision++;engine=campaign.engine;renderer.reset();campRenderer.reset();showCamp();saveRun();renderHUD();sound.play('floor');
  toast(campaign.lastRun&&campaign.lastRun.outcome==='return'?'Добыча доставлена. Сдайте поручения и восстановите постройки.':'Вы снова у костра. Лагерь помнит ваши дела.');return true;
}
function confirmAbandon(){
  if(campaign.mode!=='run')return;returnScreen=screen;setScreen('confirm');
  mountDialog('<section class="ash-dialog"><p class="ash-kicker">Оставить вылазку</p><h2>Позвать следующего героя?</h2><p class="lead">Вся добыча в рюкзаке будет потеряна. Постройки, банк и боевой прогресс принятых поручений останутся. Чтобы вынести материалы, вернитесь у входа или лестницы в безопасном месте.</p><div class="ash-dialog-actions"><button class="ash-secondary ash-danger" data-action="abandon-confirmed">Оставить вылазку</button><button class="ash-primary" data-action="cancel-confirm" data-default-focus>Продолжить путь</button></div></section>');
}
function exportSave(){
  const blob=new Blob([campaign.serialize()],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');
  link.href=url;link.download='ashen-vault-campaign.json';document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Файл кампании выгружен: лагерь, задания и текущая вылазка.');
}
function processEvents(events){renderer.pushEvents(events||[]);let played=0;for(const e of events||[]){if(played>=4)break;if(e.type==='step'&&events.length>1)continue;sound.play(e.type);played++;}}
function perform(action,automatic=false){
  if(campaign.mode!=='run'||!engine||screen||engine.state.status!=='playing')return false;
  if(!automatic)moveQueue=[];sound.init();
  const beforeFloor=engine.state.floor,readyBefore=campaign.getQuestViews().filter(q=>q.status==='ready').length;
  const acted=campaign.act(action),s=engine.state;processEvents(s.events||[]);
  if(acted)sessionRevision++;
  if(s.floor!==beforeFloor){renderer.reset();selectedTarget=null;hoverTile=null;mapMode=false;moveQueue=[];toast(`${ASHEN_ROMAN[s.floor-1]}. ${ASHEN_FLOORS[s.floor-1]}`);}
  if(selectedTarget&&!s.enemies.some(e=>e.id===selectedTarget&&e.hp>0))selectedTarget=null;
  if(s.status==='choice'){moveQueue=[];showChoice();}
  else if(campaign.mode==='result'){moveQueue=[];endedAt=performance.now()+600;if(s.status==='won')sound.play('win');}
  else if(campaign.getQuestViews().filter(q=>q.status==='ready').length>readyBefore){toast('Поручение выполнено. Награда ждёт у заказчика в лагере.');sound.play('loot');}
  if(acted)saveRun();else if(campaign.notice)toast(campaign.notice);else if(s.log&&s.log.length)toast(s.log[s.log.length-1].text);
  renderHUD();return acted;
}
function clickWorld(event){
  if(screen)return;
  if(campaign.mode==='camp'){
    const hit=campRenderer.hitTest(event.clientX,event.clientY);if(!hit)return;
    sound.init();if(hit.type==='npc')showNpc(hit.id);else if(hit.type==='portal')showDepart();return;
  }
  if(campaign.mode!=='run'||!engine||engine.state.status!=='playing')return;
  const tile=renderer.hitTest(event.clientX,event.clientY);if(!tile)return;const s=engine.state,p=s.player;
  if(!s.seen[tile.y]||!s.seen[tile.y][tile.x]){toast('Эта часть свода ещё скрыта.');return;}
  const enemy=s.enemies.find(e=>e.hp>0&&e.x===tile.x&&e.y===tile.y&&s.visible[e.y][e.x]);
  if(enemy){selectedTarget=enemy.id;if(Math.abs(enemy.x-p.x)+Math.abs(enemy.y-p.y)===1)perform({type:'move',dx:enemy.x-p.x,dy:enemy.y-p.y});else toast(`${enemy.name}: цель выбрана. Q — Искра.`);updateHover(tile);return;}
  if(tile.x===p.x&&tile.y===p.y){perform({type:'interact'});return;}
  if(Math.abs(tile.x-p.x)+Math.abs(tile.y-p.y)===1){perform({type:'move',dx:tile.x-p.x,dy:tile.y-p.y});return;}
  if(visibleEnemies(s).length){toast('Враг рядом. Выбирайте соседние клетки или двигайтесь клавишами.');return;}
  const path=knownPath(s,tile);if(!path.length){toast('Нет исследованного пути к этой клетке.');return;}moveQueue=path;nextAutoStep=0;sound.init();
}
function onAction(action){
  if(action==='fresh-campaign'){setScreen('confirm');mountDialog('<section class="ash-dialog"><h2>Начать новую кампанию?</h2><p>Лагерь будет создан заново. Перед этим можно выгрузить нынешнее сохранение из меню.</p><div class="ash-dialog-actions"><button class="ash-primary" data-action="fresh-campaign-confirmed">Создать новый лагерь</button><button class="ash-secondary" data-action="resume">Назад</button></div></section>');return;}
  if(action==='fresh-campaign-confirmed')return uiFreshCampaign();
  if(action==='depart'){showDepart();return;}
  if(action==='new'||action==='start-confirmed')return startRun();
  if(action==='return')return returnToCamp();
  if(action==='quests'){showQuests();return;}
  if(action==='load')return loadRun();
  if(action==='sound'){toggleSound();return;}if(action==='music'){toggleMusic();return;}
  if(action==='help'){showHelp();return;}if(action==='close-help'){closeHelp();return;}
  if(action==='pause'){if(screen==='pause')resumeGame();else if(screen==='help')closeHelp();else showPause();return;}
  if(action==='resume'||action==='title'){resumeGame();return;}
  if(action==='motion'){preferences.reduceMotion=!preferences.reduceMotion;storage.set(ASHEN_PREF_KEY,JSON.stringify(preferences));root.classList.toggle('reduced-motion',preferences.reduceMotion);for(const b of root.querySelectorAll('[data-action="motion"]')){b.textContent=preferences.reduceMotion?'Включена':'Выключена';b.setAttribute('aria-pressed',String(preferences.reduceMotion));}return;}
  if(action==='export'){exportSave();return;}if(action==='import'){$('ash-import').click();return;}
  if(action==='abandon'){confirmAbandon();return;}
  if(action==='abandon-confirmed'){
    if(campaign.abandonRun()){sessionRevision++;if(campaign.mode==='result')campaign.returnToCamp();engine=campaign.engine;renderer.reset();campRenderer.reset();showCamp();saveRun();renderHUD();toast('Вылазка оставлена. Лагерь и выполненная часть боевых поручений сохранены.');}return;
  }
  if(action==='cancel-confirm'){if(returnScreen==='pause')showPause();else resumeGame();return;}
  if(action==='replace-save'){returnScreen='pause';setScreen('confirm');mountDialog('<section class="ash-dialog"><h2>Сохранить текущую кампанию?</h2><p class="lead">Она заменит общее сохранение в этом браузере. Все изменения текущей вкладки станут выбранной версией. При желании сначала выгрузите текущую кампанию в файл.</p><div class="ash-dialog-actions"><button class="ash-primary" data-action="replace-save-confirmed">Заменить сохранение</button><button class="ash-secondary" data-action="cancel-confirm" data-default-focus>Назад</button></div></section>');return;}
  if(action==='replace-save-confirmed'){resetSaveBaseline();persistenceBlocked=false;persistenceIssue='';lastSavedText=null;saveRun();showPause();return;}
  if(action==='fullscreen'){try{if(document.fullscreenElement){const req=document.exitFullscreen();if(req&&req.catch)req.catch(()=>{});}else if(root.requestFullscreen){const req=root.requestFullscreen();if(req&&req.catch)req.catch(()=>toast('Откройте игру в отдельном окне браузера.'));}else toast('Используйте полноэкранный режим браузера.');}catch(_){toast('Используйте полноэкранный режим браузера.');}return;}
  if(action==='map'){toggleMap();return;}if(screen||campaign.mode!=='run')return;
  if(action==='bolt')castBolt();else if(action==='nova')perform({type:'cast',skill:'nova'});else if(['wait','potion','interact'].includes(action))perform({type:action});
}
uiListen(root,'click',event=>{
  const button=event.target.closest('button');if(!button||!root.contains(button)||button.disabled)return;
  sound.init();
  if(button.dataset.npc){showNpc(button.dataset.npc);return;}
  if(button.dataset.class){const f=$('ash-seed-input');if(f)lastSeed=f.value;selectedClass=button.dataset.class;showDepart('class-'+selectedClass);return;}
  if(button.dataset.quest){
    if(campaign.mode!=='camp')return;const claim=button.dataset.questAction==='claim',id=button.dataset.quest;
    const ok=claim?campaign.claimQuest(id):campaign.acceptQuest(id);
    if(ok){sessionRevision++;saveRun();renderHUD();sound.play(claim?'level':'loot');showNpc(selectedNpc,'quest-'+id);}
    toast(campaign.notice||(ok?(claim?'Задание сдано. Открыт новый уровень постройки.':'Поручение принято. Его цель видна в журнале.'): 'Сейчас это действие недоступно.'));return;
  }
  if(button.dataset.building){
    const id=button.dataset.building,level=Number(button.dataset.buildingLevel);
    if(campaign.mode!=='camp'||Number(campaign.meta.buildings[id])!==level)return;
    const ok=campaign.upgradeBuilding(id);
    if(ok){sessionRevision++;saveRun();renderHUD();sound.play('level');showNpc(selectedNpc,'building-'+id);}
    toast(campaign.notice||(ok?'Постройка улучшена. Бонус действует в следующих вылазках.':'Не выполнены условия строительства.'));return;
  }
  if(button.dataset.choice){choosePerk(button.dataset.choice);return;}
  if(button.dataset.move){const [dx,dy]=button.dataset.move.split(',').map(Number);perform({type:'move',dx,dy});return;}
  if(button.dataset.action)onAction(button.dataset.action);
});
uiListen(root,'input',event=>{
  if(event.target.id!=='ash-music-volume')return;
  preferences.musicVolume=clampUI(Number(event.target.value)/100,0,1);const output=$('ash-music-volume-value');if(output)output.textContent=Math.round(preferences.musicVolume*100)+'%';sound.init();sound.updateMusic();
});
uiListen(root,'change',event=>{if(event.target.id==='ash-music-volume')storage.set(ASHEN_PREF_KEY,JSON.stringify(preferences));});
uiListen(canvas,'click',clickWorld);
uiListen(canvas,'pointermove',event=>{
  if(event.pointerType==='touch'||screen)return;
  if(campaign.mode==='camp'){campHover=campRenderer.hitTest(event.clientX,event.clientY);canvas.style.cursor=campHover?'pointer':'default';}
  else updateHover(renderer.hitTest(event.clientX,event.clientY));
});
uiListen(canvas,'pointerleave',()=>{campHover=null;canvas.style.cursor='default';updateHover(null);});
uiListen($('ash-minimap'),'click',toggleMap);
uiListen($('ash-import'),'change',async event=>{
  const input=event.target,file=input.files&&input.files[0];if(!file)return;
  const ticket=++importTicket,revision=sessionRevision,baseline=storage.read(ASHEN_SAVE_KEY);
  try{
    if(file.size>3*1024*1024){toast('Этот файл слишком велик для сохранения игры.');return;}
    const text=await file.text();
    if(ticket!==importTicket||revision!==sessionRevision){toast('Игра изменилась, пока читался файл. Выберите сохранение ещё раз.');return;}
    // An asynchronous read must retain the checkpoint from selection time;
    // storage events can arrive after this promise has already resolved.
    loadRun(text,baseline);
  }catch(_){toast('Не удалось прочитать файл. Текущая игра не изменена.');}finally{input.value='';}
});
uiListen(document,'keydown',event=>{
  if(event.ctrlKey||event.metaKey||event.altKey)return;
  const tag=event.target&&event.target.tagName;
  if(screen&&event.code==='Tab'){
    const items=Array.from(overlay.querySelectorAll('button:not([disabled]), input:not([disabled]), [tabindex="0"]')).filter(el=>!el.hidden);
    if(items.length){const first=items[0],last=items[items.length-1],active=document.activeElement;if(event.shiftKey&&(active===first||!overlay.contains(active))){event.preventDefault();last.focus();}else if(!event.shiftKey&&(active===last||!overlay.contains(active))){event.preventDefault();first.focus();}}
    return;
  }
  if(screen&&event.repeat&&['Enter','Space'].includes(event.code)){event.preventDefault();return;}
  if(event.code==='Escape'){
    if(event.repeat)return;event.preventDefault();sound.init();
    if(screen==='help')closeHelp();else if(screen==='confirm')onAction('cancel-confirm');else if(screen==='pause')resumeGame();else if(screen==='choice')showPause();else if(screen==='end')returnToCamp();else if(screen)resumeGame();else showPause();return;
  }
  if(['INPUT','TEXTAREA','SELECT'].includes(tag))return;
  if(tag==='BUTTON'&&['Enter','Space'].includes(event.code))return;
  if(screen==='choice'&&/^Digit[123]$/.test(event.code)){event.preventDefault();if(!event.repeat){const c=engine.state.choices[Number(event.code.slice(-1))-1];if(c)choosePerk(c.id);}return;}
  if(screen)return;
  sound.init();
  if(campaign.mode==='camp'){
    if(/^Digit[1-4]$/.test(event.code)){event.preventDefault();if(!event.repeat)showNpc(ASHEN_NPCS[Number(event.code.slice(-1))-1].id);}
    else if(event.code==='KeyE'||event.code==='Enter'){event.preventDefault();if(!event.repeat)showDepart();}
    else if(event.code==='KeyJ'){event.preventDefault();if(!event.repeat)showQuests();}
    else if(event.code==='KeyM'&&!event.repeat)toggleSound();return;
  }
  if(event.code==='Tab'){event.preventDefault();if(!event.repeat)toggleMap();return;}
  if(event.code==='Slash'||event.code==='F1'){event.preventDefault();showHelp();return;}
  const movement={ArrowUp:[0,-1],KeyW:[0,-1],ArrowDown:[0,1],KeyS:[0,1],ArrowLeft:[-1,0],KeyA:[-1,0],ArrowRight:[1,0],KeyD:[1,0]};
  if(movement[event.code]){event.preventDefault();if(event.repeat&&blockedMovementKeys.has(event.code))return;blockedMovementKeys.delete(event.code);const now=performance.now();if(event.repeat&&now-lastInputTime<120)return;lastInputTime=now;const[dx,dy]=movement[event.code];perform({type:'move',dx,dy});return;}
  const keys={Space:'wait',Period:'wait',KeyQ:'bolt',KeyF:'nova',KeyH:'potion',KeyE:'interact',KeyR:'return',KeyJ:'quests',KeyM:'sound'};
  if(keys[event.code]){event.preventDefault();if(!event.repeat)onAction(keys[event.code]);}
});
uiListen(document,'keyup',event=>blockedMovementKeys.delete(event.code));
uiListen(window,'storage',event=>{
  if(event.key!==ASHEN_SAVE_KEY&&event.key!==null)return;
  const current=storage.read(ASHEN_SAVE_KEY);
  // Read the latest durable bytes, not a potentially delayed event.newValue.
  if(!current.ok||hasSaveBaseline&&current.value===observedSaveText)return;
  if(!hasSaveBaseline&&current.value===null){hasSaveBaseline=true;return;}
  markSaveConflict();showPause();
});
uiListen(window,'pagehide',()=>{saveRun();sound.setPageActive(false);});
uiListen(window,'pageshow',()=>sound.setPageActive(true));
uiListen(document,'visibilitychange',()=>{moveQueue=[];if(document.hidden){saveRun();if(engine&&!screen&&campaign.mode==='run')showPause();}else if(sound.ctx)sound.init();sound.updateMusic();});
function frame(time){
  if(uiDisposed)return;
  if(!document.hidden&&time-lastFrame>=1000/60){
    lastFrame=time;
    if(campaign.mode==='camp'){campRenderer.draw(campView||{buildings:campaign.getBuildingViews(),quests:campaign.getQuestViews(),npcs:ASHEN_NPCS,classId:selectedClass},time,{reduceMotion:!!preferences.reduceMotion,selectedNpc,hoverTarget:campHover});}
    else if(engine){const s=engine.state,selected=selectedTarget&&s.enemies.find(e=>e.id===selectedTarget&&e.hp>0);renderer.draw(s,time,{mapMode,paused:!!screen,hover:selected?{x:selected.x,y:selected.y}:hoverTile,reduceMotion:!!preferences.reduceMotion});}
    if(endedAt&&time>=endedAt){endedAt=0;showEnd();}
    if(!uiManualMode&&moveQueue.length&&time>=nextAutoStep&&engine&&!screen&&campaign.mode==='run'&&engine.state.status==='playing'){
      const s=engine.state;if(visibleEnemies(s).length){moveQueue=[];toast('Обнаружен враг. Дальше — по одному ходу.');}else{const next=moveQueue.shift(),dx=next.x-s.player.x,dy=next.y-s.player.y;if(Math.abs(dx)+Math.abs(dy)===1){if(!perform({type:'move',dx,dy},true))moveQueue=[];}else moveQueue=[];nextAutoStep=time+160;}
    }
    if(toastUntil&&time>toastUntil){$('ash-toast').classList.remove('show');toastUntil=0;}
    sound.updateMusic();
  }
  uiRaf=requestAnimationFrame(frame);
}

initCampControls();
try{
  const current=resetSaveBaseline(),raw=current.value,legacy=current.ok&&raw===null?storage.get(ASHEN_LEGACY_SAVE_KEY):null;
  if(raw!==null||legacy!==null){
    const restored=GameEngine.fromSave(raw!==null?raw:legacy);if(!restored)throw new Error('Invalid stored save');
    installCampaign(restored);lastSavedText=raw;saveState=raw!==null?'saved':'unknown';
    if(legacy!==null){saveRun();toast('Старый поход продолжен. Лагерь появится после возвращения.');}
  }else{showCamp();saveState=storage.available?'unknown':'memory';}
}catch(_){persistenceBlocked=true;persistenceIssue='corrupt';saveState='blocked';showCamp();toast('Старое сохранение не удалось прочитать. Оно не перезаписано; подробности — в меню.');}
renderHUD();updateSoundButton();
$('ash-sound-button').setAttribute('data-testid','sound');
const uiStartButton=root.querySelector('[data-action="depart"]');if(uiStartButton)uiStartButton.setAttribute('data-testid','start');
uiRaf=requestAnimationFrame(frame);
if(window.__ASHEN_TEST_MODE__){window.__ASHEN_TEST__={startRun,perform,showPause,resumeGame,showHelp,closeHelp,showTitle,showCamp,showNpc,showDepart,showQuests,showEnd,choosePerk,loadRun,saveRun,renderHUD,castBolt,onAction,clickWorld,frame,knownPath,getEngine:()=>engine,getCampaign:()=>campaign,getScreen:()=>screen,getSaveState:()=>saveState,renderer,campRenderer,root,sound,getPreferences:()=>({...preferences}),getSaveKey:()=>ASHEN_SAVE_KEY};}

// Actual UI-owned campaign bridge. No parallel engine and no state injection.
function uiCampaignAction(action){
  if(uiDisposed||!action||typeof action!=='object')return false;
  if(action.type==='pause'){
    if(action.value)showPause();else resumeGame();return true;
  }
  if(action.type==='freshCampaign')return uiFreshCampaign(action);
  if(action.type==='start')return startRun({seed:action.seed??campaign._forgeSeed,classId:action.classId??campaign._forgeClass});
  if(action.type==='choose'){
    if(!engine||engine.state.status!=='choice')return false;
    const before=campaign.serialize();choosePerk(action.id);return before!==campaign.serialize();
  }
  if(action.type==='return')return returnToCamp();
  if(action.type==='abandon'){
    const before=campaign.serialize();onAction('abandon-confirmed');return before!==campaign.serialize();
  }
  if(['acceptQuest','claimQuest','upgradeBuilding'].includes(action.type)){
    if(campaign.mode!=='camp')return false;
    const ok=campaign[action.type](action.id);
    if(ok){sessionRevision++;saveRun();renderHUD();sound.play(action.type==='acceptQuest'?'loot':'level');}
    toast(campaign.notice);return ok;
  }
  return perform(action);
}
function uiFreshCampaign({seed='embers',classId='mage'}={}){
  // Same explicit new-campaign action exposed by the corpus UI menu.
  const replacement=new GameEngine({seed,classId});
  installCampaign(replacement);saveRun();renderHUD();return true;
}
function uiSnapshot(){
  const snapshot=campaign.snapshot();snapshot.paused=screen==='pause';
  snapshot.persistence={status:saveState};return snapshot;
}
const uiBridge={ready:true,snapshot:uiSnapshot,act:uiCampaignAction,
  reset:options=>{uiFreshCampaign(options||{});return uiSnapshot();},
  setManualMode:enabled=>{uiManualMode=!!enabled;moveQueue=[];nextAutoStep=0;lastFrame=0;},
  advance:()=>{throw new Error('This turn-based game has no simulation advance operation');},
  exportSave:()=>campaign.serialize(),
  importSave:text=>({ok:loadRun(text)})};
window.__GAME_TEST__=uiBridge;
const uiController={dispose(){
  if(uiDisposed)return;uiDisposed=true;importTicket++;sessionRevision++;moveQueue=[];
  cancelAnimationFrame(uiRaf);for(const off of uiListeners.splice(0))off();
  sound.pageActive=false;
  if(sound.music)sound.music.dispose();
  if(sound.ctx){const ctx=sound.ctx;sound.ctx=null;ctx.onstatechange=null;try{Promise.resolve(ctx.close()).catch(()=>{});}catch(_){}}
  if(window.__GAME_TEST__===uiBridge)delete window.__GAME_TEST__;
  if(window.__ASHEN_TEST__&&window.__ASHEN_TEST__.root===root)delete window.__ASHEN_TEST__;
  style.remove();root.remove();
}};
if(window.__ASHEN_TEST_MODE__&&window.__ASHEN_TEST__)window.__ASHEN_TEST__.dispose=uiController.dispose;
return uiController;
}
