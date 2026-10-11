/* Пепельный свод — интерфейс, управление и синтез звука. */
const ASHEN_SAVE_KEY = 'ashen-vault.run.v1';
const ASHEN_PREF_KEY = 'ashen-vault.preferences.v1';
const ASHEN_RECORD_KEY = 'ashen-vault.records.v1';
const ASHEN_FLOORS = ['Погасшие залы', 'Корни забвения', 'Костяная часовня', 'Печь без огня', 'Сердце свода'];
const ASHEN_ROMAN = ['I', 'II', 'III', 'IV', 'V'];
const escapeHTML = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clampUI = (v, a, b) => Math.max(a, Math.min(b, Number(v) || 0));
const storage = {
  available: true,
  get(key) { try { return localStorage.getItem(key); } catch (_) { this.available = false; return null; } },
  set(key, value) { try { localStorage.setItem(key, value); return true; } catch (_) { this.available = false; return false; } },
  remove(key) { try { localStorage.removeItem(key); } catch (_) { this.available = false; } }
};
let preferences = {sound:true, music:true, musicVolume:.55, reduceMotion:typeof matchMedia==='function'&&matchMedia('(prefers-reduced-motion: reduce)').matches};
try { preferences = {...preferences, ...JSON.parse(storage.get(ASHEN_PREF_KEY) || '{}')}; } catch (_) {}
preferences.sound=!!preferences.sound;preferences.music=!!preferences.music;
preferences.musicVolume=typeof preferences.musicVolume==='number'&&Number.isFinite(preferences.musicVolume)?clampUI(preferences.musicVolume,0,1):.55;
let records = {runs:0, wins:0, bestFloor:0, bestScore:0};
try { records = {...records, ...JSON.parse(storage.get(ASHEN_RECORD_KEY) || '{}')}; } catch (_) {}

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
document.title = 'Пепельный свод — roguelike';
const root = document.createElement('div');
root.id = 'ashen-root';
root.innerHTML = `
<header class="ash-top">
  <div class="ash-brand"><span class="ash-sigil" aria-hidden="true"></span><div><strong>Пепельный свод</strong><small>Последняя искра</small></div></div>
  <nav class="ash-top-actions" aria-label="Меню игры"><span class="ash-status">Время ждёт вашего хода</span><button data-action="help" data-short="?" title="Правила и управление (?)">Путеводитель</button><button data-action="sound" data-short="♫" id="ash-sound-button" title="Включить или выключить звук">Звук: вкл.</button><button data-action="fullscreen" class="optional" data-short="⛶" title="На весь экран">Весь экран</button><button data-action="pause" data-short="Ⅱ" title="Меню (Esc)">Меню <kbd>Esc</kbd></button></nav>
</header>
<main class="ash-layout">
  <section class="ash-main" aria-label="Подземелье">
    <div class="ash-world-frame" id="ash-world-frame">
      <canvas class="ash-world" id="ash-canvas" aria-label="Карта подземелья. Передвижение стрелками или WASD." tabindex="0"></canvas>
      <div class="ash-world-top"><div class="ash-depth"><div class="eyebrow" id="ash-depth-number">ГЛУБИНА I / V</div><strong id="ash-depth-name">Погасшие залы</strong></div><span class="ash-turn" id="ash-turn">ХОД 000</span></div>
      <div class="ash-hover" id="ash-hover" hidden></div>
      <div class="ash-world-bottom"><div class="ash-world-hint" id="ash-world-hint">Пять глубин отделяют вас от Сердца свода.</div><div class="ash-mini-wrap"><canvas class="ash-mini" id="ash-minimap" width="164" height="116" aria-label="Исследованная карта"></canvas><span class="ash-mini-label">КАРТА <kbd>Tab</kbd></span></div></div>
      <div class="ash-dpad" aria-label="Передвижение"><button class="up" data-move="0,-1" aria-label="Вверх">↑</button><button class="left" data-move="-1,0" aria-label="Влево">←</button><button class="wait" data-action="wait" aria-label="Пропустить ход">·</button><button class="right" data-move="1,0" aria-label="Вправо">→</button><button class="down" data-move="0,1" aria-label="Вниз">↓</button></div>
    </div>
    <div class="ash-commands">
      <button class="ash-command magic" data-action="bolt" id="ash-bolt" title="Q: магическая искра в выбранного или ближайшего видимого врага. 3 маны."><span class="cmd-icon">ϟ</span><span class="cmd-copy"><strong>Искра</strong><small>3 маны · цель</small></span><kbd>Q</kbd></button>
      <button class="ash-command magic" data-action="nova" id="ash-nova" title="F: Кольцо пепла — удар по окружающим врагам. 5 маны."><span class="cmd-icon">✧</span><span class="cmd-copy"><strong>Кольцо</strong><small>5 маны · вокруг</small></span><kbd>F</kbd></button>
      <button class="ash-command heal" data-action="potion" id="ash-potion" title="H: выпить лечебное зелье. Расходует ход."><span class="cmd-icon">♧</span><span class="cmd-copy"><strong>Зелье</strong><small id="ash-potion-count">2 в сумке</small></span><kbd>H</kbd></button>
      <button class="ash-command" data-action="interact" id="ash-interact" title="E: спуститься, стоя на лестнице; использовать ближайший объект."><span class="cmd-icon">⇣</span><span class="cmd-copy"><strong id="ash-interact-name">Действие</strong><small id="ash-interact-detail">лестница · объект</small></span><kbd>E</kbd></button>
      <button class="ash-command wait" data-action="wait" id="ash-wait" title="Пробел: пропустить один ход."><span class="cmd-icon">◷</span><span class="cmd-copy"><strong>Подождать</strong><small>пропустить ход</small></span><kbd>␣</kbd></button>
    </div>
  </section>
  <aside class="ash-sidebar" aria-label="Персонаж и события">
    <section class="ash-card"><div class="ash-hero-heading"><span class="ash-hero-mark" id="ash-hero-mark">♜</span><div><h2 id="ash-class-name">Страж</h2><p id="ash-level">Хранитель последней искры</p></div></div>
      <div class="ash-bar-head"><span>Жизнь</span><b id="ash-hp-text">—</b></div><div class="ash-bar"><div class="ash-bar-fill" id="ash-hp"></div></div>
      <div class="ash-bar-head"><span>Мана</span><b id="ash-mana-text">—</b></div><div class="ash-bar mana"><div class="ash-bar-fill" id="ash-mana"></div></div>
      <div class="ash-bar-head"><span id="ash-level-label">Уровень 1</span><b id="ash-xp-text">—</b></div><div class="ash-bar xp"><div class="ash-bar-fill" id="ash-xp"></div></div>
      <div class="ash-stats"><div class="ash-stat"><b id="ash-attack">—</b><span>Атака</span></div><div class="ash-stat"><b id="ash-armor">—</b><span>Защита</span></div><div class="ash-stat"><b id="ash-gold">—</b><span>Золото</span></div></div>
    </section>
    <section class="ash-card"><h3 class="ash-card-title">Снаряжение <span id="ash-kills">0 побед</span></h3><div class="ash-equipment"><div class="ash-equipment-row"><span class="equip-icon">†</span><div><strong id="ash-weapon">Старый клинок</strong><small>Оружие</small></div></div><div class="ash-equipment-row"><span class="equip-icon">◇</span><div><strong id="ash-armor-name">Походный плащ</strong><small>Доспех</small></div></div></div><div class="ash-relics" id="ash-relics"><span class="ash-relic empty">Реликвии ещё не найдены.</span></div></section>
    <section class="ash-card ash-log-card"><h3 class="ash-card-title">Шёпот свода <span aria-hidden="true">···</span></h3><div class="ash-log" id="ash-log" role="log" aria-live="polite" aria-relevant="additions"></div></section>
  </aside>
</main>
<footer class="ash-footer"><span><kbd>WASD</kbd> / <kbd>↑↓←→</kbd> движение и удар · <kbd>Q</kbd> / <kbd>F</kbd> магия</span><span id="ash-seed-footer">Свод помнит каждый шаг.</span></footer>
<div class="ash-overlay" id="ash-overlay" role="dialog" aria-modal="true" aria-label="Меню игры"></div>
<div class="ash-toast" id="ash-toast" role="status"></div>
<input type="file" id="ash-import" accept="application/json,.json" hidden>
`;
document.body.appendChild(root);
const $ = id => document.getElementById(id);
const canvas = $('ash-canvas');
const renderer = new AshenRenderer(canvas);
const overlay = $('ash-overlay');
let engine = null;
let demo = null;
let screen = 'title';
let returnScreen = 'title';
let selectedClass = 'warden';
let selectedTarget = null;
let lastSeed = '';
let mapMode = false;
let hoverTile = null;
let moveQueue = [];
let nextAutoStep = 0;
let lastInputTime = 0;
let finishedRecorded = false;
let toastUntil = 0;
let lastFrame = 0;
let endedAt = 0;
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
        this.music=new AshenMusic(this.ctx,this.ctx.destination);
        this.ctx.onstatechange=()=>{if(this.ctx.state==='running')this.updateMusic();};
      }
      if(this.ctx.state!=='running')this.ctx.resume().then(()=>this.updateMusic()).catch(()=>{});
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
    if(s&&screen!=='title'){
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

function renderHUD(){
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
  $('ash-world-hint').textContent=stairs?(s.floor===5?(s.bossDefeated?'Сердце ваше. Нажмите E, чтобы вернуться.':'Хранитель ещё жив. Сначала победите его.'):'Нажмите E, чтобы спуститься глубже. Обратного пути нет.'):danger?`${danger} враг${danger===1?'':danger<5?'а':'ов'} в поле зрения. Удар — шаг в противника. Q — искра.`:s.turn<8?'Исследуйте свод. Двигайтесь стрелками или WASD. Удар — шаг в противника.':'Ищите лестницу, сундуки и святилища. Карта запоминает исследованное.';
  $('ash-seed-footer').textContent=`Семя: ${s.seed}${!storage.available?' · автосохранение недоступно':''}`;
  drawMinimap(s);
}

function setScreen(value){
  screen=value;moveQueue=[];overlay.hidden=!value;root.classList.toggle('in-menu',value==='title');
  const layout=root.querySelector('.ash-layout');if(layout)layout.inert=!!value;
  if(!value){overlay.innerHTML='';canvas.focus({preventScroll:true});}renderHUD();sound.updateMusic();
}

function showTitle(){
  setScreen('title');
  const hasSave=!!storage.get(ASHEN_SAVE_KEY);
  overlay.innerHTML=`<section class="ash-modal" aria-labelledby="ash-title-heading">
    <p class="ash-kicker">Пошаговое путешествие в забытое подземелье</p>
    <h1 class="ash-title" id="ash-title-heading">Пепельный<br><span class="title-soft">свод</span></h1>
    <p class="ash-subtitle">Под камнем всё ещё теплится Сердце свода.<br>Пройдите пять глубин, победите Владыку углей<br>и вынесите последнюю искру на поверхность.</p>
    <div class="ash-title-rule" aria-hidden="true">✦</div>
    <div class="ash-class-label">Кто войдёт во тьму?</div>
    <div class="ash-classes">${Object.entries(classPresentation).map(([id,c])=>`<button class="ash-class ${id===selectedClass?'selected':''}" data-class="${id}" aria-pressed="${id===selectedClass}"><span class="ash-class-symbol" aria-hidden="true">${c.symbol}</span><h3>${c.name}</h3><p>${c.desc}</p><span class="ash-class-trait">${c.trait}</span></button>`).join('')}</div>
    <div class="ash-start-row">${hasSave?'<button class="ash-primary" data-action="load">Продолжить поход <span aria-hidden="true">→</span></button><button class="ash-secondary" data-action="new">Новый поход</button>':'<button class="ash-primary" data-action="new">Зажечь искру <span aria-hidden="true">→</span></button>'}</div>
    <label class="ash-seed">Семя подземелья <input id="ash-seed-input" maxlength="40" autocomplete="off" spellcheck="false" placeholder="случайное" value="${escapeHTML(lastSeed)}" aria-label="Семя подземелья; оставьте пустым для случайной карты"></label>
    <div class="ash-menu-bottom"><span>Случайные подземелья</span><span>Одна жизнь</span><span>Три пути героя</span></div>
    <p class="ash-menu-note">Стрелки / WASD — движение · шаг во врага — удар · мир ждёт вашего решения</p>
    <div style="text-align:center;margin-top:12px"><button class="ash-link" data-action="music" data-music-label="compact" aria-pressed="${preferences.music}">${preferences.music?'♫ Музыка: вкл.':'♫ Музыка: выкл.'}</button></div>
    <div style="text-align:center;margin-top:16px"><button class="ash-link" data-action="help">Как выжить в своде</button><span style="color:#485940;padding:0 13px">·</span><button class="ash-link" data-action="import">Загрузить сохранение</button></div>
    ${records.runs?`<p class="ash-menu-note">Походов завершено: ${records.runs} · Побед: ${records.wins} · Лучший счёт: ${records.bestScore}</p>`:''}
  </section>`;
}

function randomSeed(){
  try{const data=new Uint32Array(1);crypto.getRandomValues(data);return data[0].toString(36).toUpperCase();}catch(_){return(Date.now().toString(36)+Math.random().toString(36).slice(2,5)).toUpperCase();}
}

function requestNewRun(){
  const seedInput=$('ash-seed-input');if(seedInput)lastSeed=seedInput.value.trim();
  if((engine&&['playing','choice'].includes(engine.state.status))||storage.get(ASHEN_SAVE_KEY)){
    returnScreen=screen||'pause';setScreen('confirm');
    overlay.innerHTML=`<section class="ash-dialog"><p class="ash-kicker">Новая искра</p><h2>Начать новый поход?</h2><p class="lead">Текущий поход будет заменён. Если хотите сохранить его отдельно, сначала выгрузите сохранение из меню.</p><div class="ash-dialog-actions"><button class="ash-primary" data-action="start-confirmed">Начать заново</button><button class="ash-secondary" data-action="cancel-confirm">Вернуться</button></div></section>`;
  }else startRun();
}

function startRun(){
  engine=new AshenEngine({seed:lastSeed||randomSeed(),classId:selectedClass});
  finishedRecorded=false;endedAt=0;selectedTarget=null;hoverTile=null;mapMode=false;moveQueue=[];renderer.reset();setScreen('');sound.init();sound.play('floor');saveRun();renderHUD();
  toast('Каждое действие — один ход. Шагните во врага, чтобы ударить.');
}

function saveRun(){
  if(!engine)return;
  if(['dead','won'].includes(engine.state.status)){storage.remove(ASHEN_SAVE_KEY);return;}
  storage.set(ASHEN_SAVE_KEY,engine.serialize());
}

function loadRun(text=null){
  try{
    const candidate=text||storage.get(ASHEN_SAVE_KEY);if(!candidate){toast('Сохранённого похода пока нет.');return;}
    const restored=AshenEngine.fromSave(candidate);
    if(!restored||!['playing','choice'].includes(restored.state.status))throw new Error('Этот поход завершён.');
    engine=restored;selectedClass=engine.state.player.classId;selectedTarget=null;hoverTile=null;moveQueue=[];mapMode=false;finishedRecorded=false;endedAt=0;renderer.reset();sound.init();
    if(engine.state.status==='choice')showChoice();else setScreen('');saveRun();renderHUD();toast('Искра ещё жива. Поход продолжен.');
  }catch(err){toast('Не удалось открыть сохранение: файл повреждён или несовместим.');if(!text){storage.remove(ASHEN_SAVE_KEY);showTitle();}}
}

function showPause(){
  if(!engine){showTitle();return;}if(engine.state.status==='choice'){showChoice();return;}if(['dead','won'].includes(engine.state.status)){showEnd();return;}
  saveRun();setScreen('pause');
  overlay.innerHTML=`<section class="ash-dialog"><p class="ash-kicker">У костра</p><h2>Тьма подождёт.</h2><p class="lead">${storage.available?'Поход сохранён автоматически. Можно закрыть страницу и продолжить позже в этом же браузере.':'Браузер не разрешает автосохранение. Выгрузите сохранение, чтобы продолжить позже.'}</p>
    <div class="ash-toggle"><span>Все звуки</span><button data-action="sound" aria-pressed="${preferences.sound}">${preferences.sound?'Включены':'Выключены'}</button></div>
    <div class="ash-toggle"><span>Музыка<small>Поход последней искры</small></span><button data-action="music" aria-pressed="${preferences.music}">${preferences.music?'Включена':'Выключена'}</button></div>
    <div class="ash-music-volume"><label for="ash-music-volume">Громкость музыки</label><input type="range" id="ash-music-volume" min="0" max="100" step="5" value="${Math.round(preferences.musicVolume*100)}" aria-describedby="ash-music-volume-value"><output id="ash-music-volume-value" for="ash-music-volume">${Math.round(preferences.musicVolume*100)}%</output></div>
    <div class="ash-toggle"><span>Спокойная анимация</span><button data-action="motion">${preferences.reduceMotion?'Включена':'Выключена'}</button></div>
    <div class="ash-dialog-actions"><button class="ash-primary" data-action="resume">Продолжить <kbd>Esc</kbd></button><button class="ash-secondary" data-action="help">Управление</button></div>
    <div class="ash-divider"></div><div class="ash-dialog-actions"><button class="ash-secondary" data-action="export">Выгрузить сохранение</button><button class="ash-secondary" data-action="import">Загрузить</button><button class="ash-secondary ash-danger" data-action="title">К выбору героя</button></div>
    <p class="ash-menu-note">Семя: ${escapeHTML(engine.state.seed)} · Глубина ${engine.state.floor}/5 · Ход ${engine.state.turn}</p></section>`;
}

function resumeGame(){if(!engine){showTitle();return;}if(engine.state.status==='choice')showChoice();else if(['dead','won'].includes(engine.state.status))showEnd();else setScreen('');}

function showHelp(){
  if(screen!=='help')returnScreen=screen;setScreen('help');
  overlay.innerHTML=`<section class="ash-dialog wide"><p class="ash-kicker">Путеводитель странника</p><h2>Каждый шаг имеет вес.</h2><p class="lead">Это пошаговая игра: пока вы думаете, враги стоят. Нажатия меню и осмотр карты не расходуют ход. Смерть завершает поход.</p>
    <div class="ash-help-grid"><section><h3>Управление</h3><div class="ash-help-keys"><div><span>Двигаться / ударить соседнего врага</span><span><kbd>WASD</kbd> / <kbd>←↑↓→</kbd></span></div><div><span>Искра: выбранный / ближайший враг</span><kbd>Q</kbd></div><div><span>Кольцо пепла: удар вокруг себя</span><kbd>F</kbd></div><div><span>Выпить зелье</span><kbd>H</kbd></div><div><span>Лестница / соседний объект</span><kbd>E</kbd></div><div><span>Подождать ход</span><kbd>Пробел</kbd></div><div><span>Обзор исследованной карты</span><kbd>Tab</kbd></div><div><span>Пауза / меню</span><kbd>Esc</kbd></div></div></section>
    <section><h3>Как победить</h3><ul><li>Найдите лестницу на каждом из пяти этажей. Стоя на ней, нажмите E.</li><li>На пятой глубине победите Владыку углей. Затем доберитесь до лестницы и нажмите E, чтобы выйти.</li><li>За победы растёт опыт. При повышении уровня выберите один из трёх даров.</li><li>Сундуки, фонтаны и святилища работают при входе на клетку или на E рядом. Предметы подбираются автоматически; лучшее снаряжение надевается сразу.</li></ul></section>
    <section><h3>Магия, лечение и опасность</h3><p>Искра стоит 3 маны, Кольцо пепла — 5. Ожидание восстанавливает ману, но враги тоже получают ход. В безопасном месте отдых понемногу лечит. Красное предвестие вокруг врага предупреждает о взрыве: у порохового духа он через ход, у Владыки есть два хода подготовки. Выйдите из зоны. На лестнице перед следующим этажом часть здоровья и вся мана восстанавливаются.</p></section>
    <section><h3>Мышь и сенсорный экран</h3><p>Нажмите на исследованную клетку, чтобы пройти к ней. При появлении врага автоматическое движение остановится. Нажатие на врага выбирает его для Искры; соседнего врага герой атакует сразу. На узком экране появляется крестовина; заклинания и зелье доступны кнопками внизу.</p></section>
    <section class="full"><h3>Сохранение и повторный поход</h3><p>Игра сохраняет активный поход после действий, если браузер разрешает локальное хранилище. В меню можно выгрузить и загрузить сохранение файлом. После смерти автосохранение удаляется. Одинаковые семя, класс и действия воспроизводят одинаковый поход. Золото повышает итоговый счёт; это сокровища, торговца в своде нет.</p></section></div>
    <div class="ash-dialog-actions"><button class="ash-primary" data-action="close-help">Понятно <span aria-hidden="true">→</span></button></div></section>`;
}

function closeHelp(){const previous=returnScreen;returnScreen='';if(previous==='title')showTitle();else if(previous==='pause')showPause();else if(previous==='end')showEnd();else resumeGame();}

function showChoice(){
  if(!engine||engine.state.status!=='choice'){resumeGame();return;}
  setScreen('choice');const s=engine.state;
  const icons={vitality:'♡',strength:'†',armor:'◇',focus:'✧',sorcery:'ϟ',precision:'⌖',evasion:'⌁',vampire:'♧'};
  overlay.innerHTML=`<section class="ash-dialog wide"><p class="ash-kicker">Уровень ${s.player.level} · дар глубины</p><h2>Искра становится сильнее.</h2><p class="lead">Выберите один дар. Он останется с вами до конца похода.</p><div class="ash-choice-grid">${s.choices.map((c,i)=>`<button class="ash-choice" data-choice="${escapeHTML(c.id)}"><span aria-hidden="true">${icons[c.id]||'✦'}</span><kbd style="float:right">${i+1}</kbd><b>${escapeHTML(c.name)}</b><p>${escapeHTML(c.desc)}</p></button>`).join('')}</div></section>`;
}

function choosePerk(id){
  if(!engine||engine.state.status!=='choice')return;
  if(engine.choose(id)){renderer.pushEvents(engine.state.events||[]);sound.play('level');saveRun();if(engine.state.status==='choice')showChoice();else setScreen('');renderHUD();}
}

function runScore(s){return (s.stats.kills||0)*50+(s.player.gold||0)+(s.floor-1)*300+(s.player.level-1)*120+(s.status==='won'?2000:0);}
function recordEnd(){
  if(!engine||finishedRecorded)return;const s=engine.state;finishedRecorded=true;records.runs++;if(s.status==='won')records.wins++;records.bestFloor=Math.max(records.bestFloor,s.floor);records.bestScore=Math.max(records.bestScore,runScore(s));storage.set(ASHEN_RECORD_KEY,JSON.stringify(records));storage.remove(ASHEN_SAVE_KEY);
}

function showEnd(){
  if(!engine){showTitle();return;}const s=engine.state;if(!['dead','won'].includes(s.status)){resumeGame();return;}recordEnd();setScreen('end');const win=s.status==='won';
  overlay.innerHTML=`<section class="ash-dialog"><p class="ash-kicker">${win?'Свет возвращается':'Поход завершён'}</p><h2>${win?'Вы вынесли огонь.':'Искра погасла.'}</h2><p class="lead">${win?'Владыка углей пал. Под сводом впервые за сотню лет наступила тишина. Вы нашли дорогу на поверхность — и принесли с собой рассвет.':'Свод запомнил ваши шаги. Следующий герой найдёт другие проходы, другие дары и свой путь сквозь тьму.'}</p><div class="ash-result-grid"><div><b>${s.floor}<small style="font-size:15px;color:#7e916f"> / 5</small></b><span>Глубина</span></div><div><b>${s.stats.kills||0}</b><span>Врагов повержено</span></div><div><b>${runScore(s)}</b><span>Счёт похода</span></div></div><p class="lead" style="font-size:11px">${escapeHTML(s.player.name||currentClass().name)} · уровень ${s.player.level} · ${s.turn} ходов · ${s.player.gold} золота<br>Семя: ${escapeHTML(s.seed)}</p><div class="ash-dialog-actions"><button class="ash-primary" data-action="title">Новый странник <span aria-hidden="true">→</span></button><button class="ash-secondary" data-action="retry">Повторить то же семя</button></div></section>`;
}

function exportSave(){
  if(!engine||!['playing','choice'].includes(engine.state.status)){toast('Сначала начните поход.');return;}
  const blob=new Blob([engine.serialize()],{type:'application/json'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=`ashen-vault-${String(engine.state.seed).replace(/[^a-zA-Z0-9_-]/g,'_')}.json`;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Сохранение выгружено. Его можно открыть через меню игры.');
}

function processEvents(events){
  renderer.pushEvents(events||[]);let played=0;for(const e of events||[]){if(played>=4)break;if(e.type==='step'&&events.length>1)continue;sound.play(e.type);played++;}
}

function perform(action,automatic=false){
  if(!engine||screen||engine.state.status!=='playing')return false;
  if(!automatic)moveQueue=[];sound.init();
  const beforeFloor=engine.state.floor;const acted=engine.act(action);const s=engine.state;processEvents(s.events||[]);
  if(s.floor!==beforeFloor){renderer.reset();selectedTarget=null;hoverTile=null;mapMode=false;moveQueue=[];toast(`${ASHEN_ROMAN[s.floor-1]}. ${ASHEN_FLOORS[s.floor-1]}`);}
  if(selectedTarget&&!s.enemies.some(e=>e.id===selectedTarget&&e.hp>0))selectedTarget=null;
  if(s.status==='choice'){moveQueue=[];showChoice();}
  else if(s.status==='won'||s.status==='dead'){moveQueue=[];recordEnd();endedAt=performance.now()+600;if(s.status==='won')sound.play('win');}
  if(acted)saveRun();else if(s.log&&s.log.length)toast(s.log[s.log.length-1].text);
  renderHUD();return acted;
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

function clickWorld(event){
  if(!engine||screen||engine.state.status!=='playing')return;const tile=renderer.hitTest(event.clientX,event.clientY);if(!tile)return;const s=engine.state,p=s.player;
  if(!s.seen[tile.y]||!s.seen[tile.y][tile.x]){toast('Эта часть свода ещё скрыта.');return;}
  const enemy=s.enemies.find(e=>e.hp>0&&e.x===tile.x&&e.y===tile.y&&s.visible[e.y][e.x]);
  if(enemy){selectedTarget=enemy.id;if(Math.abs(enemy.x-p.x)+Math.abs(enemy.y-p.y)===1)perform({type:'move',dx:enemy.x-p.x,dy:enemy.y-p.y});else toast(`${enemy.name}: цель для Искры выбрана. Нажмите Q.`);updateHover(tile);return;}
  if(tile.x===p.x&&tile.y===p.y){perform({type:'interact'});return;}
  if(Math.abs(tile.x-p.x)+Math.abs(tile.y-p.y)===1){perform({type:'move',dx:tile.x-p.x,dy:tile.y-p.y});return;}
  if(visibleEnemies(s).length){toast('Враг рядом. Выбирайте соседние клетки или двигайтесь клавишами.');return;}
  const path=knownPath(s,tile);if(!path.length){toast('Нет исследованного пути к этой клетке.');return;}moveQueue=path;nextAutoStep=0;sound.init();
}

function updateHover(tile){
  hoverTile=tile;const box=$('ash-hover');if(!engine||screen||!tile){box.hidden=true;return;}const s=engine.state;if(!s.visible[tile.y]||!s.visible[tile.y][tile.x]){box.hidden=true;return;}
  const enemy=s.enemies.find(e=>e.x===tile.x&&e.y===tile.y&&e.hp>0);if(enemy){box.innerHTML=`<b>${escapeHTML(enemy.name)}</b><span>${enemy.hp}/${enemy.maxHp} жизни · атака ${enemy.atk} · броня ${enemy.armor||0}${enemy.intent?'<br>Готовит сильную атаку!':''}</span>`;box.className='ash-hover danger';box.hidden=false;return;}
  const f=s.features.find(f=>f.x===tile.x&&f.y===tile.y&&!f.used);if(f){const names={chest:'Древний сундук',fountain:'Последняя вода',shrine:'Святилище искры'};box.innerHTML=`<b>${names[f.type]||'Находка'}</b><span>Подойдите или нажмите E рядом.</span>`;box.className='ash-hover';box.hidden=false;return;}box.hidden=true;
}

function toggleMap(){if(!engine||screen)return;mapMode=!mapMode;moveQueue=[];toast(mapMode?'Исследованная карта. Tab — вернуться к герою.':'Следуем за искрой.');}

function onAction(action){
  if(action==='new'){requestNewRun();return;}if(action==='start-confirmed'){startRun();return;}if(action==='cancel-confirm'){if(returnScreen==='title')showTitle();else resumeGame();return;}
  if(action==='load'){loadRun();return;}if(action==='sound'){toggleSound();return;}if(action==='music'){toggleMusic();return;}if(action==='help'){showHelp();return;}if(action==='close-help'){closeHelp();return;}
  if(action==='pause'){if(screen==='pause')resumeGame();else if(screen==='help')closeHelp();else showPause();return;}if(action==='resume'){resumeGame();return;}
  if(action==='title'){if(engine&&['playing','choice'].includes(engine.state.status))saveRun();lastSeed='';showTitle();return;}
  if(action==='retry'){if(engine){lastSeed=engine.state.seed;selectedClass=engine.state.player.classId;}startRun();return;}
  if(action==='motion'){preferences.reduceMotion=!preferences.reduceMotion;storage.set(ASHEN_PREF_KEY,JSON.stringify(preferences));showPause();return;}
  if(action==='export'){exportSave();return;}if(action==='import'){$('ash-import').click();return;}
  if(action==='fullscreen'){try{if(document.fullscreenElement){const exit=document.exitFullscreen();if(exit&&exit.catch)exit.catch(()=>{});}else if(root.requestFullscreen){const req=root.requestFullscreen();if(req&&req.catch)req.catch(()=>toast('Откройте игру в отдельном окне браузера.'));}else toast('Используйте полноэкранный режим вашего браузера.');}catch(_){toast('Используйте полноэкранный режим вашего браузера.');}return;}
  if(action==='map'){toggleMap();return;}if(screen)return;
  if(action==='bolt')castBolt();else if(action==='nova')perform({type:'cast',skill:'nova'});else if(['wait','potion','interact'].includes(action))perform({type:action});
}

root.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button||!root.contains(button)||button.disabled)return;
  sound.init();
  if(button.dataset.class){const field=$('ash-seed-input');if(field)lastSeed=field.value;selectedClass=button.dataset.class;showTitle();return;}
  if(button.dataset.choice){choosePerk(button.dataset.choice);return;}
  if(button.dataset.move){const [dx,dy]=button.dataset.move.split(',').map(Number);perform({type:'move',dx,dy});return;}
  if(button.dataset.action)onAction(button.dataset.action);
});
root.addEventListener('input',event=>{
  if(event.target.id!=='ash-music-volume')return;
  preferences.musicVolume=clampUI(Number(event.target.value)/100,0,1);
  const output=$('ash-music-volume-value');if(output)output.textContent=Math.round(preferences.musicVolume*100)+'%';
  sound.init();sound.updateMusic();
});
root.addEventListener('change',event=>{if(event.target.id==='ash-music-volume')storage.set(ASHEN_PREF_KEY,JSON.stringify(preferences));});

canvas.addEventListener('click',clickWorld);
canvas.addEventListener('pointermove',event=>{if(event.pointerType==='touch')return;updateHover(renderer.hitTest(event.clientX,event.clientY));});
canvas.addEventListener('pointerleave',()=>updateHover(null));
$('ash-minimap').addEventListener('click',toggleMap);
$('ash-import').addEventListener('change',async event=>{const file=event.target.files&&event.target.files[0];if(!file)return;try{if(file.size>1024*1024){toast('Этот файл слишком велик для сохранения игры.');return;}loadRun(await file.text());}catch(_){toast('Не удалось прочитать файл.');}finally{event.target.value='';}});

document.addEventListener('keydown',event=>{
  const tag=event.target&&event.target.tagName;if(event.ctrlKey||event.metaKey||event.altKey)return;
  if(event.code==='Escape'){sound.init();event.preventDefault();if(screen==='help')closeHelp();else if(screen==='confirm'){if(returnScreen==='title')showTitle();else resumeGame();}else if(screen==='pause')resumeGame();else if(!screen)showPause();return;}
  if(tag==='INPUT'||tag==='TEXTAREA')return;
  sound.init();
  if(screen==='choice'&&/^Digit[123]$/.test(event.code)){event.preventDefault();const c=engine.state.choices[Number(event.code.slice(-1))-1];if(c)choosePerk(c.id);return;}
  if(screen==='title'&&event.code==='Enter'&&event.target===document.body){event.preventDefault();requestNewRun();return;}
  if(screen)return;
  if(event.code==='Tab'){event.preventDefault();if(!event.repeat)toggleMap();return;}
  if(event.code==='Slash'||event.code==='F1'){event.preventDefault();showHelp();return;}
  const movement={ArrowUp:[0,-1],KeyW:[0,-1],ArrowDown:[0,1],KeyS:[0,1],ArrowLeft:[-1,0],KeyA:[-1,0],ArrowRight:[1,0],KeyD:[1,0]};
  if(movement[event.code]){event.preventDefault();const now=performance.now();if(event.repeat&&now-lastInputTime<120)return;lastInputTime=now;const[dx,dy]=movement[event.code];perform({type:'move',dx,dy});return;}
  const keys={Space:'wait',Period:'wait',KeyQ:'bolt',KeyF:'nova',KeyH:'potion',KeyE:'interact',KeyM:'sound'};
  if(keys[event.code]){event.preventDefault();if(event.repeat)return;onAction(keys[event.code]);}
});
window.addEventListener('pagehide',()=>{saveRun();sound.setPageActive(false);});
window.addEventListener('pageshow',()=>sound.setPageActive(true));
document.addEventListener('visibilitychange',()=>{moveQueue=[];if(document.hidden){saveRun();if(engine&&!screen&&engine.state.status==='playing')showPause();}else if(sound.ctx)sound.init();sound.updateMusic();});

function frame(time){
  if(!document.hidden&&time-lastFrame>=1000/60){
    lastFrame=time;const s=engine?engine.state:demo&&demo.state;
    if(s){const selected=selectedTarget&&s.enemies.find(e=>e.id===selectedTarget&&e.hp>0);renderer.draw(s,time,{mapMode:screen==='title'&&!engine?true:mapMode,paused:!!screen,hover:selected?{x:selected.x,y:selected.y}:hoverTile,reduceMotion:!!preferences.reduceMotion});}
    if(endedAt&&time>=endedAt){endedAt=0;showEnd();}
    if(moveQueue.length&&time>=nextAutoStep&&engine&&!screen&&engine.state.status==='playing'){
      const s=engine.state;if(visibleEnemies(s).length){moveQueue=[];toast('Обнаружен враг. Дальше — по одному ходу.');}else{const next=moveQueue.shift(),dx=next.x-s.player.x,dy=next.y-s.player.y;if(Math.abs(dx)+Math.abs(dy)===1){if(!perform({type:'move',dx,dy},true))moveQueue=[];}else moveQueue=[];nextAutoStep=time+160;}
    }
    if(toastUntil&&time>toastUntil){$('ash-toast').classList.remove('show');toastUntil=0;}
    sound.updateMusic();
  }
  requestAnimationFrame(frame);
}

try{
  demo=new AshenEngine({seed:'THE-LAST-EMBER',classId:'warden'});
  for(let y=0;y<demo.state.h;y++)for(let x=0;x<demo.state.w;x++){demo.state.seen[y][x]=true;demo.state.visible[y][x]=true;}
}catch(err){console.error('Не удалось создать демонстрационное подземелье.',err);}
updateSoundButton();showTitle();renderHUD();requestAnimationFrame(frame);
if(window.__ASHEN_TEST_MODE__){window.__ASHEN_TEST__={startRun,perform,showPause,resumeGame,showHelp,closeHelp,showTitle,choosePerk,loadRun,castBolt,onAction,clickWorld,frame,getEngine:()=>engine,getScreen:()=>screen,renderer,root,sound,getPreferences:()=>({...preferences})};}
