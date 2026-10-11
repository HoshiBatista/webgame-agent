/* Emberwatch UI: browser input, lifecycle, persistence and integration only. */
function mountGame(root) {
  // Corpus adapter: include the original owned styles in the four-module artifact.
  const ownedStyle=document.createElement("style");
  ownedStyle.textContent="\n:root{color-scheme:dark;--bg:#0b1c1b;--panel:#132b27;--ink:#eee9d5;--muted:#a1b4a8;--line:#c7d5b01c;--gold:#e6bc74;--mint:#b6d4aa;--danger:#ed9881;--radius:17px;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif;font-synthesis:none}*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 70% -20%,#26463a 0,transparent 56%),var(--bg);color:var(--ink);min-height:100dvh}button,input,select{font:inherit}button{color:inherit;cursor:pointer}button:disabled{cursor:not-allowed;opacity:.45}button:focus-visible,a:focus-visible,input:focus-visible,summary:focus-visible,select:focus-visible{outline:2px solid var(--gold);outline-offset:4px}button{touch-action:manipulation;-webkit-tap-highlight-color:transparent}button,.tower-card{transition:background .16s,transform .16s,border-color .16s}button:hover:enabled{filter:brightness(1.1)}button:active:enabled{transform:translateY(1px)}[hidden]{display:none!important}svg{display:block;flex-shrink:0;pointer-events:none}h1,h2,h3,p{margin:0}a{color:var(--gold)}.app{max-width:1460px;margin:auto;padding:24px 34px 28px}.topbar{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:25px}.brand{display:flex;align-items:center;gap:11px}.brand-seal{color:var(--gold);width:42px;height:46px;display:grid;place-items:center}.brand-word{font:600 27px/1.1 Georgia,\"Times New Roman\",serif;letter-spacing:2.8px}.brand-sub{font-size:9px;letter-spacing:3px;color:var(--muted);margin-top:5px;text-transform:uppercase}.top-actions{display:flex;gap:7px;align-items:center}.quiet-button{display:flex;align-items:center;justify-content:center;gap:8px;border:1px solid var(--line);background:#ffffff04;border-radius:9px;padding:10px 12px;font-size:12px;color:var(--muted);min-height:40px}.icon-button{width:39px;height:39px;padding:0;border:1px solid var(--line);background:#ffffff04;border-radius:10px;display:inline-grid;place-items:center;color:var(--muted)}.icon-button.is-on{background:#e9c78016;border-color:#e9c78060;color:var(--gold)}.campaign-line{display:flex;justify-content:space-between;gap:18px;align-items:end;margin-bottom:18px}.eyebrow{font-size:10px;letter-spacing:2.2px;text-transform:uppercase;font-weight:700;color:var(--mint)}.campaign-line h1{font:400 32px/1.2 Georgia,\"Times New Roman\",serif;margin-top:6px;letter-spacing:-.3px}.campaign-status{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:7px;padding-bottom:4px}.status-light{width:6px;height:6px;border-radius:100%;background:var(--mint);box-shadow:0 0 12px #bdddb04a}.game-grid{display:grid;grid-template-columns:minmax(0,1fr) 294px;gap:18px;align-items:start}.field-column{min-width:0}.field-hud{height:63px;border:1px solid var(--line);border-radius:var(--radius) var(--radius) 0 0;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 20px;background:linear-gradient(110deg,#213b31,#19332c)}.resource-group{display:flex;align-items:center;gap:26px}.resource{display:flex;align-items:center;gap:9px}.resource svg{color:var(--gold)}.resource[data-resource=\"lives\"] svg{color:#df927b}.resource-value{font:600 22px/1 Georgia,\"Times New Roman\",serif;font-variant-numeric:tabular-nums}.resource-label{font-size:9px;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-top:4px}.wave-resource{display:flex;align-items:center;gap:10px;text-align:right}.wave-resource .resource-value{font-size:19px}.wave-track{display:flex;gap:3px;margin-top:7px}.wave-track i{width:7px;height:3px;border-radius:2px;background:#ffffff18}.wave-track i.done{background:var(--gold)}.wave-track i.now{background:var(--mint)}.board-wrap{position:relative;isolation:isolate;overflow:hidden;background:#2c4838;aspect-ratio:1000/640;border-left:1px solid var(--line);border-right:1px solid var(--line)}canvas{width:100%;height:100%;display:block;touch-action:none;outline-offset:-4px!important}.board-tag{position:absolute;top:16px;left:17px;pointer-events:none;display:flex;align-items:center;gap:7px;padding:7px 10px;background:#0c211bd4;backdrop-filter:blur(4px);border:1px solid #e2d8a721;border-radius:6px;font-size:10px;letter-spacing:1.3px;text-transform:uppercase;color:#e8dcc0}.board-hint{position:absolute;bottom:15px;left:50%;transform:translateX(-50%);max-width:calc(100% - 36px);white-space:normal;text-align:center;pointer-events:none;padding:8px 14px;border-radius:24px;background:#081e19dc;box-shadow:0 4px 18px #061c1640;font-size:11px;color:#eee2c6;border:1px solid #f9dda325;line-height:1.35}.board-toolbar{position:absolute;right:12px;top:12px;display:flex;gap:6px}.board-toolbar .icon-button{background:#09231bd9;border-color:#dcebd130;color:#ede8d3;width:32px;height:32px;border-radius:8px}.wave-announcement{position:absolute;left:50%;top:43%;transform:translate(-50%,-50%);width:82%;max-width:510px;text-align:center;pointer-events:none;padding:20px;background:linear-gradient(90deg,#06170a00,#081f17eb 25%,#081f17eb 75%,#06170a00);animation:announce 2.9s both}.wave-announcement strong{display:block;font:400 32px Georgia,serif;color:#f3dfb4}.wave-announcement span{display:block;font-size:10px;letter-spacing:3px;color:var(--mint);margin-bottom:6px;text-transform:uppercase}@keyframes announce{0%{opacity:0;translate:0 5px}12%,70%{opacity:1;translate:0 0}100%{opacity:0;translate:0 -5px}}.board-overlay{position:absolute;inset:0;z-index:5;display:flex;align-items:center;background:linear-gradient(90deg,#081e18f2,#081e18db 38%,#081e1840 75%)}.start-copy{width:62%;max-width:520px;padding:34px 36px}.start-copy h2{font:400 clamp(31px,3.7vw,56px)/1.02 Georgia,serif;letter-spacing:-1.6px;margin:14px 0;color:#fff0d3;text-wrap:balance}.start-copy h2 em{font-style:italic;color:#e6bc74}.start-copy>p{font-size:12px;line-height:1.75;color:#bfcdbe;max-width:290px}.start-copy .eyebrow{font-size:9px}.difficulty-picker{display:flex;gap:5px;margin:22px 0 7px}.difficulty-picker button{border:1px solid #cbd7b324;color:#bbcbbb;background:#ffffff05;padding:8px 11px;border-radius:6px;font-size:10px}.difficulty-picker button[aria-pressed=\"true\"]{background:#d6b17423;border-color:#d6b1747a;color:#f3dbb0}.difficulty-note{min-height:30px;font-size:10px!important;line-height:1.5!important;margin-bottom:17px}.primary-button{width:100%;display:flex;justify-content:center;align-items:center;gap:9px;background:linear-gradient(110deg,#eed094,#d8ac69);border:1px solid #edd29b;border-radius:10px;padding:13px 16px;color:#283429;font-weight:750;font-size:12px;min-height:44px;box-shadow:0 3px 12px #0002}.start-copy .primary-button{max-width:284px}.continue-button{margin-top:9px;background:#142f27;border-color:#aabb944d;color:#d6e1c7;box-shadow:none}.start-features{margin-top:18px;display:flex;flex-wrap:wrap;gap:12px;color:#a9bda7;font-size:9px;letter-spacing:.3px}.pause-overlay{align-items:center;justify-content:center;background:#061b17bd;backdrop-filter:blur(3px)}.pause-card{text-align:center;max-width:330px;padding:24px}.pause-card h2{font:38px Georgia,serif;margin:10px 0}.pause-card p{font-size:12px;line-height:1.7;color:var(--muted);margin-bottom:20px}.pause-card .eyebrow{color:var(--gold)}.end-overlay{justify-content:center;background:#061b17de;backdrop-filter:blur(4px)}.end-card{max-width:455px;text-align:center;padding:25px;max-height:100%;overflow:auto}.end-emblem{margin:0 auto;color:var(--gold);width:48px}.end-card h2{font:38px Georgia,serif;margin:12px 0 9px}.end-card>p{font-size:12px;line-height:1.7;color:var(--muted)}.end-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:23px 0}.end-stats strong{display:block;font:25px Georgia,serif;color:var(--gold)}.end-stats span{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.8px}.end-card .quiet-button{margin-top:9px;width:100%}.field-controls{display:flex;gap:8px;align-items:center;justify-content:space-between;padding:12px 14px;background:#18332b;border:1px solid var(--line);border-radius:0 0 var(--radius) var(--radius)}.left-controls{display:flex;align-items:center;gap:7px}.speed-group{display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}.speed-group button{padding:8px 10px;background:transparent;border:0;font-size:11px;color:var(--muted);min-height:36px}.speed-group button[aria-pressed=\"true\"]{color:#1b3427;background:var(--mint)}.control-divider{height:22px;width:1px;background:var(--line);margin:0 5px}.spell-button{display:flex;align-items:center;gap:9px;border:1px solid #dca77750;color:#eed4a4;background:#d4995910;border-radius:9px;padding:8px 11px;position:relative;min-height:37px;font-size:11px}.spell-button svg{color:#f3ba77}.spell-button small{color:#b7b897;font-size:10px}.spell-button.is-on{border-color:#efcb81;box-shadow:0 0 0 2px #efcb8120;background:#efcb8120}.keyboard-hint{color:#728e7a;font-size:10px}.keyboard-hint kbd{font:10px system-ui;background:#ffffff0b;padding:2px 4px;border-radius:3px;color:#aabea5}.below-board{display:flex;align-items:start;justify-content:space-between;gap:15px;margin:13px 3px}.field-tip{font-size:11px;line-height:1.7;color:var(--muted);max-width:540px}.field-tip strong{font-weight:500;color:#d9d5ba}.checkpoint-note{font-size:9px;color:#758e7a;white-space:nowrap;padding-top:3px}.arsenal{border:1px solid var(--line);border-radius:var(--radius);background:linear-gradient(135deg,#1e352b,#162e26);padding:18px}.panel-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.panel-heading h2{font:22px Georgia,serif}.panel-heading span{color:#91a68e;font-size:9px;letter-spacing:1px}.tower-list{display:grid;gap:7px}.tower-card{display:grid;grid-template-columns:45px 1fr auto;align-items:center;gap:10px;width:100%;background:#0d241c5e;border:1px solid #aabb8f1f;border-radius:11px;text-align:left;padding:10px;min-height:67px;position:relative}.tower-card .tower-icon{width:44px;height:44px;border-radius:9px;background:#a8b7820b;display:grid;place-items:center}.tower-card strong{font-size:12px;font-weight:630;display:block;letter-spacing:.1px}.tower-card .tower-role{display:block;font-size:9px;color:#9db198;margin-top:5px}.tower-card .tower-cost{align-self:center;color:#e7cd92;font-size:12px;display:flex;align-items:center;gap:4px;white-space:nowrap}.tower-card .hotkey{position:absolute;left:5px;top:4px;font-size:8px;color:#b8c9a645;line-height:1}.tower-card[aria-pressed=\"true\"]{border-color:#d9bf79;background:#d2b97813;box-shadow:0 0 0 1px #d9bf7920}.tower-card.is-unaffordable .tower-cost{color:#bc917b}.section-rule{height:1px;background:var(--line);margin:17px 0}.inspector-empty{padding:3px 2px 0;color:#98ad95;font-size:11px;line-height:1.65}.inspector-empty strong{font:16px Georgia,serif;display:block;color:#dfddbd;margin-bottom:6px}.selection-heading{display:flex;align-items:center;justify-content:space-between;gap:8px}.selection-heading h3{font:18px Georgia,serif}.tower-level{font-size:9px;color:var(--gold);white-space:nowrap}.inspector-desc{font-size:10px;line-height:1.7;color:#9db096;margin-top:9px}.stat-row{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;margin:14px 0}.stat-row div{padding:8px 3px;border:1px solid #aabe9118;border-radius:7px;text-align:center}.stat-row strong{font-size:12px;font-weight:650;color:#ddd9ba;display:block}.stat-row span{font-size:8px;color:#9cae8f;display:block;margin-top:4px}.build-selected{margin-top:12px}.secondary-actions{display:grid;grid-template-columns:1fr auto;gap:7px;margin-top:10px}.secondary-actions .primary-button{font-size:11px;padding:10px}.sell-button{border:1px solid #d9b49826;background:#c3a78609;border-radius:9px;padding:8px 10px;color:#c4b7a0;font-size:10px;min-width:65px}.target-control{display:flex;gap:6px;align-items:center;margin-top:13px;justify-content:space-between;font-size:10px;color:#a6b59a}.target-control select{border:1px solid var(--line);background:#142b23;color:#d6d9bb;border-radius:6px;padding:6px;max-width:160px;font-size:10px}.pad-select-label{display:flex;justify-content:space-between;align-items:center;margin-top:13px;font-size:9px;color:#8ca186;gap:7px}.pad-select-label select{min-width:105px;max-width:160px;font-size:10px;color:#cbd2b6;background:#152d25;border:1px solid var(--line);border-radius:6px;padding:5px}.next-wave{margin-top:15px;border:1px solid var(--line);border-radius:var(--radius);padding:17px;background:linear-gradient(130deg,#20352a,#1b3027)}.next-wave .eyebrow{font-size:9px;letter-spacing:1.3px;color:#a7b393}.next-wave h3{font:19px Georgia,serif;margin-top:8px}.next-description{font-size:10px;line-height:1.65;color:#99ab91;margin-top:7px;min-height:30px}.enemy-pills{display:flex;gap:5px;flex-wrap:wrap;margin:12px 0}.enemy-pill{display:flex;gap:5px;align-items:center;padding:5px 7px;border:1px solid #c7d5b01b;border-radius:6px;font-size:9px;color:#c8ceb2;background:#101e1430}.enemy-dot{width:5px;height:5px;border-radius:50%;background:var(--enemy-color)}.wave-action .primary-button{margin-top:12px}.wave-action .wave-reward{font-size:9px;text-align:center;color:#839b7f;margin-top:9px}.wave-progress{height:4px;background:#ffffff0b;border-radius:4px;margin:14px 0 5px;overflow:hidden}.wave-progress>span{display:block;background:var(--mint);height:100%;transition:width .2s}.battle-note{font-size:10px;text-align:center;color:#b0c1a4;margin-top:10px}.footer{display:flex;justify-content:space-between;gap:15px;margin-top:22px;font-size:9px;letter-spacing:1.1px;text-transform:uppercase;color:#657f6e}.footer-right{color:#9cac86}.toasts{position:fixed;z-index:60;bottom:25px;left:50%;transform:translateX(-50%);display:grid;gap:7px;pointer-events:none;width:max-content;max-width:calc(100% - 30px)}.toast{font-size:12px;line-height:1.5;border:1px solid #d3c69b42;border-radius:10px;padding:12px 19px;color:#f3e7c9;background:#172c24f7;box-shadow:0 12px 40px #0004}.toast.error{border-color:#d79c8060;color:#eec1a9}.modal-backdrop{position:fixed;inset:0;z-index:50;display:grid;place-items:center;background:#041512db;backdrop-filter:blur(6px);padding:24px}.modal{width:100%;max-width:665px;max-height:calc(100dvh - 48px);overflow:auto;background:linear-gradient(135deg,#263d30,#142c23);border:1px solid #d2cc9e40;border-radius:19px;padding:27px;box-shadow:0 35px 90px #0005}.modal-head{display:flex;justify-content:space-between;align-items:start;gap:20px}.modal h2{font:31px Georgia,serif;margin-top:6px}.help-lead{font-size:12px;line-height:1.8;color:#bac9ae;margin-top:15px}.help-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:22px 0}.help-grid>div{background:#081e1545;border:1px solid var(--line);border-radius:11px;padding:14px}.help-grid h3{font-size:12px;color:var(--gold);margin-bottom:7px}.help-grid p{font-size:11px;line-height:1.8;color:#a5b89e}.controls-table{font-size:11px;line-height:2;color:#aebda1}.controls-table kbd{font:10px monospace;border:1px solid #cbd5b135;border-bottom-width:2px;background:#0c241955;color:#e7dcb5;border-radius:4px;padding:3px 5px;min-width:23px;display:inline-block;text-align:center}.settings-list{display:grid;gap:16px;margin-top:22px}.setting-row{display:flex;align-items:center;justify-content:space-between;gap:15px;font-size:12px;color:#c8d1b6}.setting-row input[type=\"range\"]{accent-color:var(--gold);width:130px}.setting-row input[type=\"checkbox\"]{accent-color:var(--gold);width:18px;height:18px;cursor:pointer}.settings-caption{font-size:10px;line-height:1.7;color:#8aa182;margin-top:5px;max-width:380px}.modal-actions{display:flex;gap:9px;justify-content:flex-end;margin-top:25px}.modal-actions .primary-button{width:auto}.modal-actions .quiet-button{font-size:11px}.confirmation-copy{color:#a8ba9f;font-size:12px;line-height:1.8;margin-top:20px}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.fatal{padding:30px;max-width:720px;margin:10vh auto;background:#26392d;border:1px solid #e6bc7460;border-radius:18px;line-height:1.8}.fatal h1{font:28px Georgia,serif;color:#e6bc74}.fatal p{color:#b9c9ab;font-size:14px;margin-top:14px}#game-root:fullscreen .app{max-width:none;width:100%;height:100%;overflow:auto;background:var(--bg);padding:18px 30px}#game-root:fullscreen .app .topbar{margin-bottom:12px}#game-root:fullscreen .app .campaign-line{margin-bottom:10px}#game-root:fullscreen .app .game-grid{max-width:1600px;margin:auto}.is-reduced *{animation-duration:.001s!important;transition-duration:.001s!important;scroll-behavior:auto!important}\n@media(min-width:1550px){.app{padding-top:32px}.campaign-line{margin-bottom:23px}.topbar{margin-bottom:30px}.game-grid{grid-template-columns:minmax(0,1fr) 307px;gap:23px}}\n@media(max-width:1120px){.app{padding:20px}.game-grid{grid-template-columns:minmax(0,1fr) 258px;gap:13px}.arsenal{padding:14px}.tower-card{padding:8px;gap:6px;grid-template-columns:38px 1fr auto}.tower-card .tower-icon{width:36px;height:36px}.tower-card strong{font-size:11px}.tower-card .tower-role{font-size:8px}.keyboard-hint{display:none}.start-copy{padding:24px;width:70%}.start-copy h2{font-size:40px}.start-copy>p{font-size:11px;max-width:250px}.difficulty-picker{margin-top:15px}.start-features{display:none}.resource-group{gap:18px}.field-hud{padding:11px 15px}.next-wave{padding:14px}.checkpoint-note{display:none}.campaign-line h1{font-size:29px}}\n@media(max-width:880px){.app{max-width:790px}.game-grid{grid-template-columns:1fr}.sidebar{display:grid;grid-template-columns:1fr .8fr;gap:13px;align-items:start}.arsenal{padding:15px}.tower-list{grid-template-columns:1fr 1fr;gap:7px}.tower-card{grid-template-columns:31px 1fr;padding:9px 7px}.tower-card .tower-icon{width:31px;height:35px}.tower-card .tower-icon svg{width:30px;height:30px}.tower-card .tower-cost{grid-column:2;position:absolute;right:7px;top:10px;font-size:10px}.tower-card strong{font-size:10px;padding-right:22px}.tower-card .tower-role{font-size:8px;line-height:1.4;margin-top:6px}.tower-card[data-type=\"arcane\"] strong{font-size:9px}.next-wave{margin-top:0}.panel-heading h2{font-size:19px}.start-copy{width:61%;padding:32px}.start-copy h2{font-size:46px}.start-copy>p{font-size:12px}.difficulty-picker{margin-top:22px}.footer{margin-top:18px}.campaign-status{font-size:10px}.below-board{margin-bottom:16px}.campaign-line h1{font-size:31px}.topbar{margin-bottom:22px}}\n@media(max-width:560px){.app{padding:16px 10px 20px}.topbar{margin-bottom:21px;gap:5px}.brand-word{font-size:22px;letter-spacing:2px}.brand-sub{font-size:8px;letter-spacing:2px}.brand-seal{width:30px}.brand-seal svg{width:29px}.top-actions{gap:5px}.top-actions .quiet-button{padding:9px;min-width:35px;min-height:35px}.top-actions .button-label{display:none}.top-actions .icon-button{width:35px;height:35px;border-radius:8px}.campaign-line{margin:0 5px 14px}.campaign-line h1{font-size:27px}.campaign-line .eyebrow{font-size:8px;letter-spacing:1.5px}.campaign-status{display:none}.field-hud{height:56px;padding:9px 12px;border-radius:13px 13px 0 0;gap:9px}.resource-group{gap:19px}.resource{gap:6px}.resource svg{width:16px;height:16px}.resource-value{font-size:20px}.resource-label{font-size:8px;letter-spacing:.6px}.wave-resource .resource-value{font-size:17px}.wave-track{gap:2px;margin-top:6px}.wave-track i{width:5px}.board-wrap{aspect-ratio:1000/690}.board-tag{font-size:7px;top:8px;left:8px;padding:5px 6px;gap:4px;letter-spacing:.8px}.board-tag svg{width:10px;height:10px}.board-toolbar{top:7px;right:7px;gap:4px}.board-toolbar .icon-button{width:28px;height:28px}.board-toolbar .icon-button svg{width:13px;height:13px}.board-hint{font-size:9px;padding:5px 10px;bottom:8px;width:max-content;max-width:calc(100% - 16px)}.start-copy{padding:15px 20px;width:78%;max-width:350px}.start-copy h2{font-size:34px;margin:7px 0 9px;letter-spacing:-.8px}.start-copy>p{font-size:9px;line-height:1.55;max-width:230px}.start-copy .eyebrow{font-size:7px}.difficulty-picker{margin:10px 0 5px;gap:4px}.difficulty-picker button{padding:6px 8px;font-size:8px;min-height:27px}.difficulty-note{font-size:8px!important;min-height:13px;margin-bottom:9px}.start-copy .primary-button{font-size:10px;min-height:35px;padding:9px;max-width:230px}.continue-button{margin-top:6px}.board-overlay{background:linear-gradient(90deg,#071c17f5,#071c17dc 44%,#071c1760 88%)}.field-controls{padding:9px;gap:6px;border-radius:0 0 13px 13px}.left-controls{gap:5px}.left-controls>.icon-button{height:34px;width:34px;border-radius:8px}.speed-group button{font-size:10px;padding:7px 8px;min-height:32px}.spell-button{padding:6px 9px;gap:6px;font-size:10px;min-height:34px}.spell-button svg{width:17px;height:17px}.spell-button small{font-size:9px}.control-divider{margin:0 2px}.below-board{margin:10px 5px 14px}.field-tip{font-size:10px;line-height:1.65}.sidebar{grid-template-columns:1fr;gap:10px}.arsenal{padding:14px;border-radius:13px}.tower-list{grid-template-columns:repeat(4,1fr);gap:6px}.tower-card{min-height:96px;display:flex;flex-direction:column;gap:6px;padding:8px 3px 7px;text-align:center}.tower-card .tower-icon{width:36px;height:34px}.tower-card strong{font-size:9px!important;padding:0}.tower-card .tower-role{display:none}.tower-card .tower-cost{position:static;font-size:10px;display:flex;gap:3px}.tower-card .tower-cost svg{width:9px;height:9px}.panel-heading{margin-bottom:10px}.panel-heading h2{font-size:21px}.section-rule{margin:13px 0}.inspector-empty{font-size:10px}.inspector-empty strong{font-size:15px;display:inline;margin-right:3px}.inspector-desc{font-size:10px}.stat-row{margin:10px 0}.next-wave{border-radius:13px;padding:14px;display:grid;grid-template-columns:1fr 135px;gap:0 12px;align-items:start}.next-wave .eyebrow,.next-wave h3,.next-description,.enemy-pills{grid-column:1}.next-wave h3{font-size:18px}.next-description{font-size:10px;min-height:0}.enemy-pills{margin:9px 0 0}.wave-action{grid-column:2;grid-row:1/5;align-self:center}.wave-action .primary-button{font-size:10px;padding:12px 8px;margin-top:0}.wave-action .wave-reward{font-size:8px;line-height:1.5}.wave-progress{margin-top:7px}.battle-note{font-size:9px}.footer{font-size:7px;letter-spacing:.6px;margin:18px 5px 0}.footer-right{display:none}.modal-backdrop{padding:13px}.modal{max-height:calc(100dvh - 26px);padding:21px 18px;border-radius:15px}.modal h2{font-size:28px}.help-grid{gap:8px;margin:17px 0}.help-grid>div{padding:11px}.help-grid h3{font-size:11px}.help-grid p{font-size:10px}.modal-actions{margin-top:19px}.end-card{padding:16px}.end-card h2{font-size:29px;margin:6px 0}.end-emblem{display:none}.end-card>p{font-size:10px;max-width:290px}.end-stats{margin:12px 0;gap:15px}.end-stats strong{font-size:21px}.end-stats span{font-size:7px}.end-card .primary-button{font-size:10px;min-height:33px;padding:8px}.end-card .quiet-button{min-height:30px;padding:7px;font-size:9px}.pause-card{padding:18px}.pause-card h2{font-size:32px;margin:7px}.pause-card p{font-size:11px;margin-bottom:13px}.pause-card .primary-button{padding:10px;min-height:35px}.wave-announcement strong{font-size:24px}.wave-announcement span{font-size:8px;letter-spacing:2px}.wave-announcement{padding:15px}#game-root:fullscreen .app{padding:10px}#game-root:fullscreen .app .topbar,#game-root:fullscreen .app .campaign-line,#game-root:fullscreen .app .footer{display:none}#game-root:fullscreen .app .game-grid{max-width:1100px}}\n@media(max-width:560px){.board-wrap.is-menu{aspect-ratio:auto;height:330px}.start-copy{width:80%;max-width:370px}.icon-button,.quiet-button{min-height:40px}.tower-card{min-height:99px}}\n@media(max-width:365px){.brand-word{font-size:19px}.brand-sub{font-size:7px}.top-actions .quiet-button{min-width:31px;padding:7px}.top-actions .icon-button{width:31px}.start-copy{padding:13px;width:80%}.start-copy h2{font-size:29px}.start-copy>p{font-size:8px}.difficulty-picker{margin-top:8px}.start-copy .eyebrow{display:none}.resource-group{gap:12px}.resource-label{font-size:7px}.tower-card strong{font-size:8px!important}.spell-button{font-size:9px;padding:7px;gap:4px}.speed-group button{padding:7px}.control-divider{display:none}.next-wave{grid-template-columns:1fr 120px}}\n.checkpoint-note[data-save-state=\"memory\"],.checkpoint-note[data-save-state=\"stale\"]{color:var(--danger);white-space:normal}#battlefield:focus-visible{outline:2px solid var(--gold);outline-offset:-3px}\n@media(max-width:1120px){.below-board{flex-wrap:wrap;gap:5px}.checkpoint-note[data-save-state]{display:block;white-space:normal;padding-top:0}}\n@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}button,.tower-card,.wave-progress>span{transition:none}.wave-announcement{animation:none}}\n";document.head.appendChild(ownedStyle);
  let manualMode=false;
  const ICONS = {
    crest:'<path d="M16 2 27 7v12c0 6-11 12-11 12S5 25 5 19V7Z"/><path d="m16 6 3 7-3 6-3-6Z"/><path d="M10 22h12M16 19v7"/>',
    heart:'<path d="M16 27S4 19 4 11a6 6 0 0 1 12-1 6 6 0 0 1 12 1c0 8-12 16-12 16Z"/>',
    coin:'<circle cx="16" cy="16" r="11"/><circle cx="16" cy="16" r="7"/><path d="M16 11v10m-3-8h6m-6 6h6"/>',
    flag:'<path d="M8 28V4m0 1c7-6 10 6 18 0v14c-8 6-11-6-18 0"/>',
    play:'<path d="m11 6 16 10-16 10Z"/>',
    pause:'<path d="M10 7h3v18h-3zm9 0h3v18h-3Z"/>',
    sound:'<path d="m5 12 6 0 7-7v22l-7-7H5Zm18-2c4 3 4 9 0 12m3-16c7 5 7 15 0 20"/>',
    mute:'<path d="m5 12 6 0 7-7v22l-7-7H5Zm18 0 6 8m0-8-6 8"/>',
    book:'<path d="M16 7v21M4 5c5-2 8-1 12 2 4-3 7-4 12-2v20c-6-2-8-1-12 3-4-4-7-5-12-3Z"/>',
    settings:'<circle cx="16" cy="16" r="5"/><path d="m13 3 1-1h4l1 6 5 2 5-2 2 4-4 5-1 5 2 5-4 2-5-3-5 1-5 2-3-4 3-5-1-5-3-4 3-4 5 2Z" transform="translate(0 1) scale(.94)"/>',
    full:'<path d="M12 4H4v8m16-8h8v8M4 20v8h8m16-8v8h-8"/>',
    close:'<path d="m8 8 16 16M24 8 8 24"/>',
    meteor:'<path d="m29 3-14 8M28 8l-9 7M25 16l-8 8"/><circle cx="11" cy="22" r="7"/><path d="m8 19 5 6m-6-2 3 2"/>',
    arrow:'<path d="M5 16h21m-8-8 8 8-8 8"/>',
    refresh:'<path d="M26 13a11 11 0 1 0 0 9M26 4v9h-9"/>',
    leaf:'<path d="M27 4C4 0 0 20 11 25S29 20 27 4ZM5 29 23 9m-9 10-2-7m7 2 7-1"/>',
    download:'<path d="M16 4v17m-7-7 7 7 7-7M5 23v5h22v-5"/>',
    archer:'<path d="m9 7 7-4 7 4v19H9Zm-2 19h18M11 7v7m5-7v7m5-7v7M13 26v-7h6v7"/><path d="M5 12Q-1 20 5 28V12M5 20h7"/>',
    cannon:'<path d="M6 26h21v-7H6ZM7 19l3-6 10-2 4 8M18 14 24 3l6 3-6 13"/><circle cx="11" cy="25" r="4"/><circle cx="24" cy="25" r="4"/>',
    frost:'<path d="m16 2 7 9-7 14-7-14Zm0 0v23M5 28h22M9 28v-5h14v5M4 6l3 3m18 0 3-3M1 17h5m20 0h5"/>',
    arcane:'<path d="m8 27 3-13h10l3 13ZM5 28h22"/><circle cx="16" cy="8" r="6"/><path d="m16 3-2 5h5l-3 5M8 17h16M5 4 3 2m24 2 2-2"/>'
  };
  function icon(name, size = 20) {return `<svg width="${size}" height="${size}" viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ICONS.crest}</svg>`;}
  const prefKey = 'emberwatch.settings.v1', saveKey = 'emberwatch.checkpoint.v1';
  const defaults = {sound:true,music:true,volume:.35,sfxVolume:.55,reducedMotion:!!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches,difficulty:'normal'};
  function readStored(key) {try {const s = localStorage.getItem(key); return s && s.length < 100000 ? JSON.parse(s) : null;} catch {return null;}}
  function writeStored(key, value) {try {if(value === null) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(value)); return true;} catch {return false;}}
  const stored = readStored(prefKey);
  const prefs = {...defaults};
  if (stored && typeof stored === 'object') {
    for (const k of ['sound','music','reducedMotion']) if(typeof stored[k] === 'boolean') prefs[k] = stored[k];
    for (const k of ['volume','sfxVolume']) if(Number.isFinite(stored[k]) && stored[k] >= 0 && stored[k] <= 1) prefs[k] = stored[k];
    if(['story','normal','veteran'].includes(stored.difficulty)) prefs.difficulty = stored.difficulty;
  }
  let engine = new GameEngine({difficulty:prefs.difficulty,seed:20261011});
  let audio = new GameAudio();
  let renderer, raf = 0, disposed = false, previousFrame = 0, accumulator = 0, uiElapsed = 0;
  let speed = 1, buildType = null, hoverPadId = null, meteorArmed = false, meteorAim = null, pointerOrigin = null;
  let difficulty = prefs.difficulty, modal = null, modalWasPaused = true, modalFocus = null;
  let announcementTimer = null, lastWaveSignature = '', lastInspectorSignature = '', storedCheckpoint = null;
  let lastPhase = 'menu', displayEvents = [], lastStorageWarning = -Infinity;
  const listeners = [], timers = new Set(), downloadUrls = new Set();
  const fmt = new Intl.NumberFormat('ru-RU');
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const towerLabels = {archer:'Лучники',cannon:'Мортира',frost:'Ледяной обелиск',arcane:'Арканная башня'};
  const roles = {archer:'Быстрая одиночная цель',cannon:'Взрыв по площади',frost:'Контроль и замедление',arcane:'Цепь сквозь броню'};
  const difficultyText = {story:'Больше золота и здоровья. Время освоить оборону.',normal:'Сбалансированная осада. Каждый выбор имеет вес.',veteran:'Враги сильнее, ошибок прощается меньше.'};
  root.innerHTML = `<main class="app" id="app">
<header class="topbar"><div class="brand"><span class="brand-seal">${icon('crest',40)}</span><div><div class="brand-word">EMBERWATCH</div><div class="brand-sub">Стражи янтаря</div></div></div><nav class="top-actions" aria-label="Справка и настройки"><button class="quiet-button" data-action="help" title="Полевой справочник">${icon('book',16)}<span class="button-label">Справочник</span></button><button class="icon-button" data-action="sound" data-testid="sound" aria-label="Выключить звук" title="Звук">${icon('sound',18)}</button><button class="icon-button" data-action="settings" aria-label="Настройки" title="Настройки">${icon('settings',19)}</button></nav></header>
<section class="campaign-line"><div><div class="eyebrow">Кампания I · Двенадцать волн до рассвета</div><h1>Пепельный перевал</h1></div><div class="campaign-status"><span class="status-light"></span><span id="campaign-status">Последний свет ещё горит</span></div></section>
<div class="game-grid"><section class="field-column" aria-label="Поле боя"><div class="field-hud"><div class="resource-group"><div class="resource" data-resource="lives">${icon('heart',22)}<div><div class="resource-value" id="lives-value">20<span></span></div><div class="resource-label">Прочность</div></div></div><div class="resource" data-resource="gold">${icon('coin',22)}<div><div class="resource-value" id="gold-value">260</div><div class="resource-label">Золото</div></div></div></div><div class="wave-resource"><div><div class="resource-value" id="wave-value">00 <span>/ 12</span></div><div class="wave-track" id="wave-track" aria-hidden="true">${Array.from({length:12},()=>'<i></i>').join('')}</div></div>${icon('flag',23)}</div></div>
<div class="board-wrap" id="board-wrap"><canvas id="battlefield" data-testid="canvas" width="1000" height="640" tabindex="0" aria-label="Карта обороны. Выберите площадку мышью или используйте список площадок в арсенале."></canvas><div class="board-tag">${icon('leaf',13)}<span id="board-tag-text">Долина янтарного маяка</span></div><div class="board-toolbar"><button class="icon-button" data-action="fullscreen" aria-label="На весь экран" title="На весь экран">${icon('full',16)}</button></div><div class="board-hint" id="board-hint" hidden></div><div class="wave-announcement" id="wave-announcement" hidden><span id="announce-label"></span><strong id="announce-title"></strong></div>
<div class="board-overlay" id="start-overlay"><div class="start-copy"><div class="eyebrow">Одна долина. Последний рубеж.</div><h2>Удержите<br>последний <em>свет.</em></h2><p>Тьма идёт по древней дороге. Возведите башни, соедините их силы и сохраните маяк до рассвета.</p><div class="difficulty-picker" role="group" aria-label="Сложность"><button type="button" data-difficulty="story" aria-pressed="false">История</button><button type="button" data-difficulty="normal" aria-pressed="true">Страж</button><button type="button" data-difficulty="veteran" aria-pressed="false">Ветеран</button></div><p class="difficulty-note" id="difficulty-note"></p><button class="primary-button" data-action="start" data-testid="start">Встать на защиту ${icon('arrow',16)}</button><button class="primary-button continue-button" data-action="continue" id="continue-button" hidden></button><div class="start-features"><span>4 типа башен</span><span>12 волн</span><span>Магия и улучшения</span></div></div></div>
<div class="board-overlay pause-overlay" id="pause-overlay" hidden><div class="pause-card"><div class="eyebrow">Можно выдохнуть</div><h2>Затишье</h2><p id="pause-note">Бой приостановлен. Ваша оборона ждёт.</p><button class="primary-button" data-action="resume">${icon('play',16)} Продолжить</button></div></div>
<div class="board-overlay end-overlay" id="end-overlay" hidden><div class="end-card"><div class="end-emblem">${icon('crest',48)}</div><div class="eyebrow" id="end-eyebrow"></div><h2 id="end-title"></h2><p id="end-description"></p><div class="end-stats"><div><strong id="end-wave"></strong><span>Волны</span></div><div><strong id="end-kills"></strong><span>Побеждено</span></div><div><strong id="end-score"></strong><span>Счёт</span></div></div><button class="primary-button" data-action="retry" id="retry-button">${icon('refresh',16)} Повторить волну</button><button class="quiet-button" data-action="new">Новая оборона</button></div></div></div>
<div class="field-controls"><div class="left-controls"><button class="icon-button" data-action="pause" id="pause-button" aria-label="Пауза" title="Пауза · Пробел">${icon('pause',16)}</button><div class="speed-group" role="group" aria-label="Скорость игры"><button data-speed="1" aria-pressed="true">1×</button><button data-speed="2" aria-pressed="false">2×</button><button data-speed="3" aria-pressed="false">3×</button></div><span class="control-divider"></span><button class="spell-button" data-action="meteor" id="meteor-button" title="Метеор · M">${icon('meteor',21)}<span>Метеор</span><small id="meteor-status">M</small></button></div><div class="keyboard-hint"><kbd>Пробел</kbd> пауза · <kbd>1</kbd>–<kbd>4</kbd> башни</div></div><div class="below-board"><p class="field-tip" id="field-tip"><strong>Мудрость стражей.</strong> Одна сильная башня уступает умелому сочетанию четырёх.</p><span class="checkpoint-note" id="checkpoint-note" role="status" aria-live="polite">Автосохранение между волнами</span></div></section>
<aside class="sidebar"><section class="arsenal" aria-labelledby="arsenal-heading"><div class="panel-heading"><h2 id="arsenal-heading">Арсенал</h2><span>ПОСТРОЙТЕ ОБОРОНУ</span></div><div class="tower-list">${Object.keys(towerLabels).map((type,i)=>`<button class="tower-card" data-type="${type}" aria-pressed="false" title="${roles[type]} · ${i+1}"><span class="hotkey">${i+1}</span><span class="tower-icon" style="color:${GameEngine.TOWERS[type].color}">${icon(type,35)}</span><span><strong>${towerLabels[type]}</strong><span class="tower-role">${roles[type]}</span></span><span class="tower-cost">${icon('coin',12)}${GameEngine.TOWERS[type].cost}</span></button>`).join('')}</div><div class="section-rule"></div><div id="inspector"><div class="inspector-empty"><strong>Выберите площадку</strong>Нажмите на каменный круг у дороги, затем выберите башню. Дальность будет подсвечена.</div></div><label class="pad-select-label">Площадка на карте<select id="pad-picker" aria-label="Выбрать площадку"><option value="">Не выбрана</option>${engine.getState().pads.map(p=>`<option value="${p.id}">${p.id.replace('P','№ ')}</option>`).join('')}</select></label></section><section class="next-wave" aria-labelledby="next-wave-title"><div class="eyebrow" id="next-eyebrow">Разведка · Волна 01</div><h3 id="next-wave-title">Шаги в тумане</h3><p class="next-description" id="next-description"></p><div class="enemy-pills" id="enemy-pills"></div><div class="wave-action"><button class="primary-button" data-action="wave" id="wave-button">Начать волну ${icon('arrow',15)}</button><div class="wave-progress" id="wave-progress" hidden><span id="wave-progress-fill"></span></div><div class="battle-note" id="battle-note" hidden></div><p class="wave-reward" id="wave-reward"></p></div></section></aside></div>
<footer class="footer"><span>Emberwatch · Tower Defence</span><span class="footer-right">Золото — ресурс. Время — оружие.</span></footer></main><div class="toasts" id="toasts" role="status" aria-live="polite" aria-atomic="false"></div><div id="modal-root"></div><p id="game-live" class="sr-only" aria-live="polite"></p>`;
  const $ = id => root.querySelector('#'+id);
  const app = $('app'), canvas = $('battlefield');
  renderer = new GameRenderer(canvas, engine);
  const on = (el,type,fn,options) => {el.addEventListener(type,fn,options);listeners.push(()=>el.removeEventListener(type,fn,options));};
  function later(fn,delay) {const timer=setTimeout(()=>{timers.delete(timer);fn();},delay);timers.add(timer);return timer;}
  function notify(text,error=false) {
    if(disposed) return;
    const el=document.createElement('div');el.className='toast'+(error?' error':'');el.textContent=text;
    const parent=$('toasts');parent.appendChild(el);while(parent.children.length>3)parent.firstChild.remove();
    later(()=>el.remove(),3300);
  }
  function persistPreferences() {writeStored(prefKey,prefs);}
  function validatedStoredCheckpoint() {
    const data=readStored(saveKey);if(!data)return null;
    try {const probe=new GameEngine();const result=probe.loadSave(data);return result.ok?data:null;}catch{return null;}
  }
  function checkpointStatus(state,data=null) {
    const note=$('checkpoint-note');note.dataset.saveState=state;
    note.textContent=state==='saved'?`Сохранено: начало волны ${Math.min(12,(data?.wave||0)+1)}`:state==='memory'?'Прогресс — только в этой вкладке':state==='stale'?'Не удалось удалить сохранение':state==='completed'?'Кампания завершена':'Автосохранение между волнами';
    note.title=state==='saved'?'После перезагрузки восстановится эта оборона. Покупки во время незавершённого боя не сохраняются.':state==='memory'?'Повтор волны работает до закрытия вкладки. После перезагрузки может восстановиться более раннее сохранение.':state==='stale'?'После перезагрузки прежнее сохранение может снова появиться.':'';
  }
  function clearCheckpoint(completed=false) {
    storedCheckpoint=null;
    const removed=writeStored(saveKey,null);checkpointStatus(removed?(completed?'completed':'empty'):'stale');
    if(!removed)notify('Браузер не удалил прежнее сохранение. После перезагрузки оно может снова появиться.');
  }
  function saveCheckpoint() {
    const data=engine.exportSave();if(!data)return;
    storedCheckpoint=data;
    if(writeStored(saveKey,data))checkpointStatus('saved',data);
    else {checkpointStatus('memory',data);if(Date.now()-lastStorageWarning>30000){lastStorageWarning=Date.now();notify('Браузер не сохранил прогресс. Игра доступна до закрытия вкладки.');}}
  }
  storedCheckpoint=validatedStoredCheckpoint();
  if(storedCheckpoint)checkpointStatus('saved',storedCheckpoint);
  function refreshContinue() {
    const b=$('continue-button');b.hidden=!storedCheckpoint;
    if(storedCheckpoint){const probe=new GameEngine();const valid=probe.loadSave(storedCheckpoint);if(valid.ok)b.textContent=`Продолжить · волна ${Math.min(12,probe.getState().wave+1)}`;else{storedCheckpoint=null;b.hidden=true;}}
  }
  function syncAudio() {
    const s=engine.getState();let mode=s.phase;
    if(s.paused||document.hidden)mode='paused';
    else if(s.phase==='wave' && engine.getWaveInfo(s.wave)?.boss)mode='boss';
    audio.setState({enabled:prefs.sound,musicEnabled:prefs.music,volume:prefs.volume,sfxVolume:prefs.sfxVolume,mode});
    const button=root.querySelector('[data-action="sound"]');
    button.innerHTML=icon(prefs.sound?'sound':'mute',18);button.classList.toggle('is-on',prefs.sound);button.setAttribute('aria-pressed',String(prefs.sound));button.setAttribute('aria-label',prefs.sound?'Выключить звук':'Включить звук');
  }
  async function unlockAudio() {
    if(!prefs.sound)return;
    const requestedAudio=audio;
    try {const unlocked=await requestedAudio.unlock();if(!disposed&&audio===requestedAudio){syncAudio();if(unlocked===false)notify('Звук пока недоступен. Нажмите на динамик, чтобы повторить.');}}catch{if(!disposed&&audio===requestedAudio)notify('Звук пока недоступен. Попробуйте включить его кнопкой динамика.');}
  }
  function showAnnouncement(wave) {
    const info=engine.getWaveInfo(wave);if(!info)return;
    const el=$('wave-announcement');if(announcementTimer){clearTimeout(announcementTimer);timers.delete(announcementTimer);}
    $('announce-label').textContent=`Волна ${wave} из 12`;
    $('announce-title').textContent=info.name;
    el.hidden=false;el.style.animation='none';void el.offsetWidth;el.style.animation='';
    announcementTimer=later(()=>{el.hidden=true;announcementTimer=null;},prefs.reducedMotion?1700:3000);
  }
  function drainEvents() {
    const events=engine.drainEvents();if(!events.length)return;
    displayEvents.push(...events.map(e=>({id:e.id,type:e.type,time:engine.getState().time})));if(displayEvents.length>300)displayEvents.splice(0,displayEvents.length-300);
    syncAudio();
    audio.handleEvents(events);
    for(const e of events) {
      if(e.type==='wave-start'){showAnnouncement(engine.getState().wave);$('game-live').textContent=`Началась волна ${engine.getState().wave}`;}
      if(e.type==='wave-complete'){saveCheckpoint();notify(`Волна отражена. +${engine.getWaveInfo(engine.getState().wave).reward} золота.`);}
      if(e.type==='win'){clearCheckpoint(true);$('game-live').textContent='Победа. Маяк сохранён.';}
      if(e.type==='lose'){$('game-live').textContent='Маяк пал. Можно повторить волну.';}
    }
    syncAudio();
  }
  function cancelAim() {buildType=null;meteorArmed=false;meteorAim=null;hoverPadId=null;pointerOrigin=null;canvas.style.cursor='default';}
  function action(data, quiet=false) {
    const s=engine.getState();
    if(data.type==='wave' && s.phase==='build')saveCheckpoint();
    const result=engine.act(data);
    if(!result?.ok){if(!quiet)notify(result?.reason||'Сейчас это действие недоступно.',true);return result;}
    if(data.type==='build'||data.type==='upgrade'||data.type==='sell'){if(s.phase==='build')saveCheckpoint();if(data.type==='build')buildType=null;}
    if(data.type==='target'&&s.phase==='build')saveCheckpoint();
    if(data.type==='start')saveCheckpoint();
    if(data.type==='meteor'){meteorArmed=false;meteorAim=null;canvas.style.cursor='default';}
    if(data.type==='pause'){cancelAim();syncAudio();}
    drainEvents();updateUI(true);return result;
  }
  function resetSystems(newEngine) {
    audio.dispose();renderer.dispose();engine=newEngine;audio=new GameAudio();renderer=new GameRenderer(canvas,engine);
    accumulator=0;previousFrame=0;displayEvents=[];lastPhase=engine.getState().phase;lastWaveSignature='';lastInspectorSignature='';cancelAim();
    if(announcementTimer){clearTimeout(announcementTimer);timers.delete(announcementTimer);announcementTimer=null;}$('wave-announcement').hidden=true;
    resize();syncAudio();
  }
  function startNew() {
    resetSystems(new GameEngine({difficulty,seed:20261011}));
    prefs.difficulty=difficulty;persistPreferences();action({type:'start'});void unlockAudio();canvas.focus({preventScroll:true});
  }
  function continueGame() {
    const saved=storedCheckpoint;if(!saved){notify('Сохранение не найдено.',true);return;}
    const next=new GameEngine();const result=next.loadSave(saved);if(!result.ok){storedCheckpoint=null;refreshContinue();notify('Сохранение не удалось восстановить.',true);return;}
    resetSystems(next);difficulty=engine.getState().difficulty;drainEvents();updateUI(true);void unlockAudio();canvas.focus({preventScroll:true});notify(`Оборона восстановлена. Следующая волна — ${engine.getState().wave+1}.`);
  }
  function selectTower(type) {
    if(!GameEngine.TOWERS[type])return;
    const s=engine.getState();if(s.paused||['won','lost'].includes(s.phase))return;
    if(s.phase==='menu'){notify('Сначала встаньте на защиту маяка.');return;}
    meteorArmed=false;meteorAim=null;
    buildType=buildType===type?null:type;canvas.style.cursor=buildType?'crosshair':'default';
    if(s.selectedPad && s.towers.some(t=>t.padId===s.selectedPad))action({type:'select',padId:null},true);
    updateUI(true);
  }
  function selectPad(padId) {
    const s=engine.getState();if(s.phase==='menu'||s.phase==='won'||s.phase==='lost')return;
    const tower=s.towers.find(t=>t.padId===padId);
    action({type:'select',padId});
    if(tower){buildType=null;meteorArmed=false;meteorAim=null;canvas.style.cursor='default';}
    else if(buildType&&!s.paused)action({type:'build',padId,towerType:buildType});
    updateUI(true);
  }
  function toggleMeteor(focusAim=false) {
    const s=engine.getState();if(s.phase!=='wave'||s.paused)return;
    if(s.meteor.cooldown>0){notify(`Метеор будет готов через ${Math.ceil(s.meteor.cooldown)} с.`);return;}
    meteorArmed=!meteorArmed;buildType=null;meteorAim=meteorArmed?{x:500,y:320}:null;canvas.style.cursor=meteorArmed?'crosshair':'default';if(meteorArmed&&focusAim)canvas.focus({preventScroll:true});updateUI(true);
  }
  function togglePause() {
    const s=engine.getState();if(!['build','wave'].includes(s.phase))return;
    action({type:'pause',value:!s.paused});if(!engine.getState().paused)void unlockAudio();
  }
  function updateInspector() {
    const s=engine.getState(),pad=s.pads.find(p=>p.id===s.selectedPad),tower=s.towers.find(t=>t.padId===s.selectedPad);
    const signature=JSON.stringify([s.selectedPad,tower?.type,tower?.level,tower?.spent,buildType,s.phase,s.paused]);
    if(signature===lastInspectorSignature){updateInspectorControls();return;}lastInspectorSignature=signature;
    const el=$('inspector');$('pad-picker').value=s.selectedPad||'';
    if(!pad){
      const type=buildType;
      el.innerHTML=`<div class="inspector-empty"><strong>${type?esc(towerLabels[type]):'Выберите площадку'}</strong>${type?'Теперь нажмите на свободный каменный круг у дороги. Подсветка покажет дальность.':'Нажмите на каменный круг у дороги, затем выберите башню. Дальность будет подсвечена.'}</div>`;return;
    }
    if(!tower){
      const type=buildType||'archer',cfg=GameEngine.TOWERS[type],st=engine.getTowerStats(type,1),can= ['build','wave'].includes(s.phase)&&!s.paused&&s.gold>=cfg.cost;
      el.innerHTML=`<div class="selection-heading"><h3>Площадка ${esc(pad.id.replace('P','№ '))}</h3><span class="tower-level">СВОБОДНА</span></div><p class="inspector-desc">${esc(cfg.description||roles[type])}</p><div class="stat-row"><div><strong>${Math.round(st.damage)}</strong><span>УРОН</span></div><div><strong>${Math.round(st.range)}</strong><span>ДАЛЬНОСТЬ</span></div><div><strong>${Number(st.interval).toFixed(1)} с</strong><span>ПЕРЕЗАРЯДКА</span></div></div><button class="primary-button build-selected" data-action="build" data-build="${type}" ${can?'':'disabled'}>Построить: ${esc(towerLabels[type])} · ${cfg.cost}</button>`;
      return;
    }
    const cfg=GameEngine.TOWERS[tower.type],st=engine.getTowerStats(tower.type,tower.level),refund=Math.floor(tower.spent*70/100),can=['build','wave'].includes(s.phase)&&!s.paused,max=tower.level>=cfg.maxLevel;
    const upgrade=st.upgradeCost;
    el.innerHTML=`<div class="selection-heading"><h3>${esc(towerLabels[tower.type])}</h3><span class="tower-level">${'◆'.repeat(tower.level)}${'◇'.repeat(Math.max(0,3-tower.level))}</span></div><p class="inspector-desc">${esc(cfg.description||roles[tower.type])}</p><div class="stat-row"><div><strong>${Math.round(st.damage)}</strong><span>УРОН</span></div><div><strong>${Math.round(st.range)}</strong><span>ДАЛЬНОСТЬ</span></div><div><strong>${Number(st.interval).toFixed(1)} с</strong><span>ПЕРЕЗАРЯДКА</span></div></div><label class="target-control">Приоритет<select id="target-mode" ${can?'':'disabled'} aria-label="Приоритет цели">${[['first','Ближе к маяку'],['strong','Самый сильный'],['last','Дальше от маяка']].map(([v,t])=>`<option value="${v}" ${v===tower.targetMode?'selected':''}>${t}</option>`).join('')}</select></label><div class="secondary-actions"><button class="primary-button" data-action="upgrade" ${can&&!max&&s.gold>=upgrade?'':'disabled'}>${max?'Максимальный уровень':`Улучшить · ${upgrade} ${'↗'}`}</button><button class="sell-button" data-action="sell" ${can?'':'disabled'} title="Продать за 70% вложенного золота">Продать<br>+${refund}</button></div>`;
  }
  function updateInspectorControls() {
    const s=engine.getState(),tower=s.towers.find(t=>t.padId===s.selectedPad),active=['build','wave'].includes(s.phase)&&!s.paused;
    const buildButton=$('inspector').querySelector('[data-action="build"]');
    if(buildButton)buildButton.disabled=!active||s.gold<GameEngine.TOWERS[buildButton.dataset.build].cost;
    const upgradeButton=$('inspector').querySelector('[data-action="upgrade"]');
    if(upgradeButton&&tower){const price=engine.getTowerStats(tower.type,tower.level).upgradeCost;upgradeButton.disabled=!active||price===null||s.gold<price;}
    const target=$('target-mode');if(target&&tower){target.disabled=!active;if(target.value!==tower.targetMode)target.value=tower.targetMode;}
  }
  function updateWavePanel(force) {
    const s=engine.getState();const waveNum=s.phase==='wave'?s.wave:Math.min(s.wave+1,12),info=engine.getWaveInfo(waveNum);
    const signature=[waveNum,s.phase,s.paused].join('|');
    if(force||signature!==lastWaveSignature){lastWaveSignature=signature;
      $('next-eyebrow').textContent=s.phase==='wave'?`В бою · Волна ${String(waveNum).padStart(2,'0')}`:s.phase==='won'?'Маяк встречает рассвет':`Разведка · Волна ${String(waveNum).padStart(2,'0')}`;
      $('next-wave-title').textContent=s.phase==='won'?'Долина спасена':info.name;
      $('next-description').textContent=s.phase==='won'?'Двенадцать волн позади. Свет маяка снова укажет путь.':info.description;
      $('enemy-pills').innerHTML=s.phase==='won'?'':info.groups.map(g=>`<span class="enemy-pill" title="${esc(GameEngine.ENEMIES[g.type]?.name||g.type)}"><i class="enemy-dot" style="--enemy-color:${esc(GameEngine.ENEMIES[g.type]?.color||'#d6b778')}"></i>${esc(GameEngine.ENEMIES[g.type]?.name||g.type)} ×${g.count}</span>`).join('');
      const b=$('wave-button');b.hidden=s.phase==='wave';b.disabled=s.phase!=='build'||s.paused;
      b.innerHTML=s.phase==='won'?'Рассвет наступил':s.phase==='lost'?'Маяк пал':`Начать волну ${icon('arrow',15)}`;
      $('wave-reward').textContent=s.phase==='wave'?'Укрепляйте башни прямо во время боя.':s.phase==='won'?'Свет оказался сильнее.':`За отражение: +${info.reward} золота`;
      $('wave-progress').hidden=s.phase!=='wave';$('battle-note').hidden=s.phase!=='wave';
    }
    if(s.phase==='wave'){$('wave-progress-fill').style.width=`${Math.max(0,Math.min(100,100*(1-(s.waveRemaining||0)/Math.max(1,info.total))))}%`;$('battle-note').textContent=`Осталось врагов: ${s.waveRemaining}`;}
  }
  function updateUI(force=false) {
    if(disposed)return;const s=engine.getState();
    $('gold-value').textContent=fmt.format(Math.floor(s.gold));$('lives-value').textContent=String(s.lives);
    $('wave-value').innerHTML=`${String(s.wave).padStart(2,'0')} <span style="color:#92a789;font-size:12px">/ 12</span>`;
    [...$('wave-track').children].forEach((e,i)=>e.className=i<s.wave-(s.phase==='wave'?1:0)?'done':s.phase==='wave'&&i===s.wave-1?'now':'');
    $('start-overlay').hidden=s.phase!=='menu';$('pause-overlay').hidden=!s.paused||modal!==null||!['build','wave'].includes(s.phase);$('end-overlay').hidden=!['won','lost'].includes(s.phase);
    const pa=$('pause-button');pa.disabled=!['build','wave'].includes(s.phase);pa.innerHTML=icon(s.paused?'play':'pause',16);pa.setAttribute('aria-label',s.paused?'Продолжить':'Пауза');pa.setAttribute('aria-pressed',String(s.paused));
    const mb=$('meteor-button');mb.disabled=s.phase!=='wave'||s.paused||s.meteor.cooldown>0;mb.classList.toggle('is-on',meteorArmed);mb.setAttribute('aria-pressed',String(meteorArmed));$('meteor-status').textContent=s.meteor.cooldown>0?`${Math.ceil(s.meteor.cooldown)} с`:meteorArmed?'Куда?':'M';
    $('board-wrap').classList.toggle('is-menu',s.phase==='menu');
    const hint=$('board-hint');hint.hidden=s.phase==='menu'||s.phase==='won'||s.phase==='lost'||s.paused;
    hint.textContent=meteorArmed?'Укажите цель · стрелки — прицел · Enter — удар · Esc — отмена':buildType?`${towerLabels[buildType]}: выберите свободную площадку`:s.selectedPad?'Выберите улучшение в арсенале':s.phase==='build'?'Выберите площадку и возведите башню':'Улучшайте оборону и используйте метеор';
    $('board-tag-text').textContent=s.phase==='wave'?`Осада · ${engine.getWaveInfo(s.wave)?.name||''}`:s.phase==='won'?'Первый свет рассвета':'Долина янтарного маяка';
    $('campaign-status').textContent=s.paused?'Осада приостановлена':s.phase==='wave'?'Враг на подступах':s.phase==='won'?'Маяк сохранён':s.phase==='lost'?'Последний свет погас':'Последний свет ещё горит';
    for(const b of root.querySelectorAll('[data-type]')){b.setAttribute('aria-pressed',String(buildType===b.dataset.type));b.classList.toggle('is-unaffordable',s.gold<GameEngine.TOWERS[b.dataset.type].cost);b.disabled=['won','lost'].includes(s.phase)||s.paused;}
    for(const b of root.querySelectorAll('[data-speed]'))b.setAttribute('aria-pressed',String(Number(b.dataset.speed)===speed));
    for(const b of root.querySelectorAll('[data-difficulty]'))b.setAttribute('aria-pressed',String(b.dataset.difficulty===difficulty));
    $('difficulty-note').textContent=difficultyText[difficulty];
    app.classList.toggle('is-reduced',prefs.reducedMotion);
    if(s.phase==='won'||s.phase==='lost'){
      const won=s.phase==='won';$('end-eyebrow').textContent=won?'Рассвет над перевалом':'Свет ещё можно вернуть';$('end-title').textContent=won?'Маяк устоял.':'Маяк погас.';
      $('end-description').textContent=won?'Янтарный огонь встретил рассвет. Ваши башни стали последним рубежом между долиной и тьмой.':'Враг прорвался к маяку. Измените сочетание башен и повторите последнюю волну с сохранённой обороной.';
      $('end-wave').textContent=`${won?12:Math.max(0,s.wave-1)}/12`;$('end-kills').textContent=fmt.format(s.kills);$('end-score').textContent=fmt.format(Math.floor(s.score));$('retry-button').hidden=won||!storedCheckpoint;
    }
    updateInspector();updateWavePanel(force);
    if(lastPhase!==s.phase){lastPhase=s.phase;syncAudio();if(s.phase==='won'||s.phase==='lost'){cancelAim();later(()=>{const b=root.querySelector('#end-overlay button:not([hidden])');b?.focus({preventScroll:true});},60);}}
  }
  function resize() {if(!disposed)renderer.resize();}
  let resizeObserver=null;
  if(typeof ResizeObserver==='function'){resizeObserver=new ResizeObserver(resize);resizeObserver.observe($('board-wrap'));}else on(window,'resize',resize);
  function renderLoop(now) {
    if(disposed)return;
    let dt=previousFrame?Math.max(0,Math.min(.1,(now-previousFrame)/1000)):0;previousFrame=now;
    const s=engine.getState();
    if(!manualMode&&!document.hidden&&!s.paused&&['build','wave'].includes(s.phase)){
      accumulator+=dt*speed;let iterations=0;
      while(accumulator>=1/60&&iterations<12){engine.act({type:'tick'});accumulator-=1/60;iterations++;}
      if(iterations>=12)accumulator=0;
      drainEvents();
    }else accumulator=0;
    renderer.render(document.hidden?0:dt,{hoverPadId,buildType:buildType||(engine.getState().selectedPad?'archer':null),meteorAim:meteorArmed?meteorAim:null,reducedMotion:prefs.reducedMotion,selectedPadId:engine.getState().selectedPad});
    uiElapsed+=dt;if(uiElapsed>=.12){uiElapsed=0;updateUI();}
    raf=requestAnimationFrame(renderLoop);
  }
  function openModal(kind) {
    if(modal)return;modal=kind;modalFocus=document.activeElement;
    const s=engine.getState();modalWasPaused=s.paused;
    if(['build','wave'].includes(s.phase)&&!s.paused)action({type:'pause',value:true},true);
    app.inert=true;
    let content='';
    if(kind==='help')content=`<div class="modal-head"><div><div class="eyebrow">Для тех, кто держит рубеж</div><h2 id="modal-heading">Полевой справочник</h2></div><button class="icon-button" data-action="close-modal" aria-label="Закрыть справочник">${icon('close',18)}</button></div><p class="help-lead">Сохраните маяк до конца двенадцатой волны. Враги следуют по дороге. Каждый прорвавшийся отнимает прочность; тяжёлые противники наносят больше урона.</p><div class="help-grid"><div><h3>01 · Стройте у изгибов</h3><p>Выберите башню, затем свободный круг. Или сначала выберите площадку и нажмите «Построить». Изгибы дороги дольше держат врагов в зоне огня.</p></div><div><h3>02 · Соединяйте силы</h3><p>Лучники быстро стреляют. Мортира бьёт по площади. Лёд замедляет толпу. Арканная башня игнорирует броню и задевает несколько целей.</p></div><div><h3>03 · Улучшайте осмысленно</h3><p>У каждой башни три уровня. Нажмите на построенную башню: можно улучшить, сменить приоритет цели или продать за 70% вложенного золота.</p></div><div><h3>04 · Ловите момент</h3><p>Метеор наносит урон по площади. Выберите заклинание, затем точку на карте. Перезарядка — ${engine.getState().meteor.maxCooldown} секунд игрового времени.</p></div></div><div class="controls-table"><kbd>1</kbd>–<kbd>4</kbd> башня &nbsp; <kbd>Пробел</kbd> начать волну / пауза<br><kbd>U</kbd> улучшить &nbsp; <kbd>M</kbd> метеор &nbsp; <kbd>Esc</kbd> отмена / пауза<br>Прицел метеора: <kbd>←</kbd><kbd>↑</kbd><kbd>↓</kbd><kbd>→</kbd> &nbsp; <kbd>Shift</kbd> точнее &nbsp; <kbd>Enter</kbd> удар</div><p class="help-lead">На телефоне используйте кнопки под картой. Для выбора площадки доступен и список в арсенале. После закрытия вкладки можно продолжить с начала текущей волны; покупки во время незавершённого боя в это сохранение не входят.</p><div class="modal-actions"><button class="quiet-button" data-action="download">${icon('download',16)} Скачать игру</button><button class="primary-button" data-action="close-modal">К обороне ${icon('arrow',15)}</button></div>`;
    else if(kind==='settings')content=`<div class="modal-head"><div><div class="eyebrow">Всё под вашим контролем</div><h2 id="modal-heading">Настройки</h2></div><button class="icon-button" data-action="close-modal" aria-label="Закрыть настройки">${icon('close',18)}</button></div><div class="settings-list"><label class="setting-row"><span>Звук</span><input type="checkbox" data-setting="sound" ${prefs.sound?'checked':''}></label><label class="setting-row"><span>Музыка</span><input type="checkbox" data-setting="music" ${prefs.music?'checked':''}></label><label class="setting-row"><span>Громкость музыки</span><input aria-label="Громкость музыки" type="range" min="0" max="100" data-setting="volume" value="${Math.round(prefs.volume*100)}"></label><label class="setting-row"><span>Громкость эффектов</span><input aria-label="Громкость эффектов" type="range" min="0" max="100" data-setting="sfxVolume" value="${Math.round(prefs.sfxVolume*100)}"></label><label class="setting-row"><span>Меньше декоративного движения</span><input type="checkbox" data-testid="reduced-motion" data-setting="reducedMotion" ${prefs.reducedMotion?'checked':''}></label></div><p class="settings-caption">Игровая информация остаётся видимой. Декоративные движения и вспышки становятся спокойнее.</p><div class="section-rule"></div><button class="quiet-button" data-action="ask-new">${icon('refresh',16)} Начать новую оборону</button><div class="modal-actions"><button class="primary-button" data-action="close-modal">Готово</button></div>`;
    else if(kind==='confirm-new'||kind==='confirm-start')content=`<div class="modal-head"><div><div class="eyebrow">Новая история</div><h2 id="modal-heading">Начать сначала?</h2></div><button class="icon-button" data-action="close-modal" aria-label="Отмена">${icon('close',18)}</button></div><p class="confirmation-copy">${kind==='confirm-start'?'Новая оборона заменит сохранённый прогресс. Чтобы сохранить прежний рубеж, нажмите «Отмена» и выберите «Продолжить».':'Текущая оборона будет заменена новой. Вы вернётесь к выбору сложности.'}</p><div class="modal-actions"><button class="quiet-button" data-action="close-modal">Отмена</button><button class="primary-button" data-action="${kind==='confirm-start'?'confirm-start':'confirm-new'}">Начать сначала</button></div>`;
    $('modal-root').innerHTML=`<div class="modal-backdrop" data-backdrop="true"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-heading" tabindex="-1">${content}</section></div>`;
    updateUI(true);later(()=>{$('modal-root').querySelector('button,input')?.focus({preventScroll:true});},0);
  }
  function closeModal(restorePause=true) {
    if(!modal)return;modal=null;$('modal-root').innerHTML='';app.inert=false;
    if(restorePause&&!modalWasPaused&&!document.hidden&&['build','wave'].includes(engine.getState().phase))action({type:'pause',value:false},true);
    updateUI(true);if(modalFocus?.isConnected)modalFocus.focus({preventScroll:true});modalFocus=null;
  }
  function goMenu() {
    closeModal(false);clearCheckpoint();resetSystems(new GameEngine({difficulty,seed:20261011}));refreshContinue();updateUI(true);root.querySelector('[data-testid="start"]')?.focus({preventScroll:true});
  }
  async function fullscreen() {
    try {if(document.fullscreenElement)await document.exitFullscreen();else if(root.requestFullscreen)await root.requestFullscreen();else notify('В этом браузере удобнее играть в горизонтальном положении.');resize();}catch{notify('Полноэкранный режим недоступен. Игра продолжится в текущем окне.');}
  }
  function downloadGame() {
    const source=window.__EMBERWATCH_SOURCE__;
    if(typeof source!=='string'){notify('Для автономной версии скачайте Emberwatch.html из сообщения с игрой.');return;}
    const blob=new Blob([source],{type:'text/html;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');downloadUrls.add(url);a.href=url;a.download='Emberwatch.html';document.body.appendChild(a);a.click();a.remove();later(()=>{URL.revokeObjectURL(url);downloadUrls.delete(url);},1000);notify('Автономная игра сохранена. Откройте HTML-файл в браузере.');
  }
  on(root,'click',e=>{
    const b=e.target.closest('button');if(!b||b.disabled)return;
    if(b.dataset.type){selectTower(b.dataset.type);return;}
    if(b.dataset.difficulty){difficulty=b.dataset.difficulty;updateUI(true);return;}
    if(b.dataset.speed){speed=Number(b.dataset.speed);updateUI(true);return;}
    switch(b.dataset.action){
      case'start':if(storedCheckpoint)openModal('confirm-start');else startNew();break;
      case'continue':case'retry':continueGame();break;
      case'new':goMenu();break;
      case'pause':togglePause();break;
      case'resume':if(engine.getState().paused)togglePause();break;
      case'wave':if(!engine.getState().towers.length){notify('Сначала постройте хотя бы одну башню.',true);break;}action({type:'wave'});void unlockAudio();break;
      case'build':if(engine.getState().selectedPad)action({type:'build',padId:engine.getState().selectedPad,towerType:b.dataset.build});break;
      case'upgrade':if(engine.getState().selectedPad)action({type:'upgrade',padId:engine.getState().selectedPad});break;
      case'sell':if(engine.getState().selectedPad)action({type:'sell',padId:engine.getState().selectedPad});break;
      case'meteor':toggleMeteor();break;
      case'sound':prefs.sound=!prefs.sound;persistPreferences();syncAudio();if(prefs.sound)void unlockAudio();break;
      case'help':openModal('help');break;
      case'settings':openModal('settings');break;
      case'close-modal':closeModal();break;
      case'ask-new':{const was=modalWasPaused;closeModal(false);openModal('confirm-new');modalWasPaused=was;break;}
      case'confirm-new':goMenu();break;
      case'confirm-start':closeModal(false);startNew();break;
      case'fullscreen':void fullscreen();break;
      case'download':downloadGame();break;
    }
  });
  on(root,'change',e=>{
    if(e.target.id==='pad-picker'){const id=e.target.value||null;if(id)selectPad(id);else action({type:'select',padId:null},true);return;}
    if(e.target.id==='target-mode'){action({type:'target',padId:engine.getState().selectedPad,mode:e.target.value});return;}
    const k=e.target.dataset.setting;if(!k)return;
    if(['sound','music','reducedMotion'].includes(k))prefs[k]=e.target.checked;
    else if(['volume','sfxVolume'].includes(k))prefs[k]=Math.max(0,Math.min(1,Number(e.target.value)/100));
    persistPreferences();syncAudio();updateUI(true);if(prefs.sound)void unlockAudio();
  });
  on(root,'input',e=>{const k=e.target.dataset.setting;if(['volume','sfxVolume'].includes(k)){prefs[k]=Math.max(0,Math.min(1,Number(e.target.value)/100));syncAudio();}});
  on(root,'pointerdown',e=>{if(e.target.dataset.backdrop==='true')closeModal();});
  on(canvas,'pointerdown',e=>{if((pointerOrigin&&pointerOrigin.id!==e.pointerId)||e.isPrimary===false||(e.button!==undefined&&e.button!==0))return;pointerOrigin={x:e.clientX,y:e.clientY,id:e.pointerId};canvas.focus({preventScroll:true});try{canvas.setPointerCapture(e.pointerId);}catch{}});
  on(canvas,'pointerup',e=>{
    if(!pointerOrigin||pointerOrigin.id!==e.pointerId)return;const p=pointerOrigin;pointerOrigin=null;
    if(Math.hypot(e.clientX-p.x,e.clientY-p.y)>24)return;
    const s=engine.getState();if(s.paused||!['build','wave'].includes(s.phase)||modal)return;
    if(meteorArmed){const q=renderer.worldPoint(e.clientX,e.clientY);if(q.x>=0&&q.x<=1000&&q.y>=0&&q.y<=640)action({type:'meteor',x:q.x,y:q.y});return;}
    const pad=renderer.pickPad(e.clientX,e.clientY);if(pad)selectPad(pad);else{buildType=null;action({type:'select',padId:null},true);}
  });
  const cancelPointer=e=>{if(e.pointerId===undefined||pointerOrigin?.id===e.pointerId)pointerOrigin=null;};
  on(canvas,'pointercancel',cancelPointer);on(canvas,'lostpointercapture',cancelPointer);
  on(canvas,'pointermove',e=>{if(e.isPrimary===false||(pointerOrigin&&pointerOrigin.id!==e.pointerId))return;if(meteorArmed)meteorAim=renderer.worldPoint(e.clientX,e.clientY);else hoverPadId=renderer.pickPad(e.clientX,e.clientY);});
  on(canvas,'pointerleave',()=>{hoverPadId=null;if(meteorArmed)meteorAim=null;});
  on(window,'keydown',e=>{
    if(modal){
      if(e.key==='Escape'){e.preventDefault();closeModal();return;}
      if(e.key==='Tab'){const nodes=[...$('modal-root').querySelectorAll('button:not(:disabled),input,select,[tabindex="0"]')];if(!nodes.length){e.preventDefault();return;}const first=nodes[0],last=nodes.at(-1);if(e.shiftKey&&(document.activeElement===first||!nodes.includes(document.activeElement))){e.preventDefault();last.focus();}else if(!e.shiftKey&&(document.activeElement===last||!nodes.includes(document.activeElement))){e.preventDefault();first.focus();}}
      return;
    }
    if(e.ctrlKey||e.metaKey||e.altKey||/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName)||document.activeElement?.isContentEditable)return;
    if(e.repeat&&!(meteorArmed&&['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)))return;
    if(document.activeElement?.tagName==='BUTTON'&&[' ','Enter'].includes(e.key))return;
    const key=e.key.toLowerCase(),s=engine.getState();
    if(meteorArmed&&s.phase==='wave'&&!s.paused&&['arrowleft','arrowright','arrowup','arrowdown','enter'].includes(key)){
      e.preventDefault();
      const aim=meteorAim||{x:500,y:320};
      if(key==='enter')action({type:'meteor',x:Math.max(0,Math.min(1000,aim.x)),y:Math.max(0,Math.min(640,aim.y))});
      else {const step=e.shiftKey?10:25;meteorAim={x:Math.max(0,Math.min(1000,aim.x+(key==='arrowright'?step:key==='arrowleft'?-step:0))),y:Math.max(0,Math.min(640,aim.y+(key==='arrowdown'?step:key==='arrowup'?-step:0)))};canvas.focus({preventScroll:true});}
      return;
    }
    if(key==='escape'){e.preventDefault();if(buildType||meteorArmed||s.selectedPad){cancelAim();action({type:'select',padId:null},true);}else togglePause();}
    else if(key===' '){e.preventDefault();if(s.phase==='build'&&!s.paused){if(s.towers.length){action({type:'wave'});void unlockAudio();}else notify('Постройте башню перед началом волны.');}else togglePause();}
    else if(['1','2','3','4'].includes(key)){e.preventDefault();selectTower(['archer','cannon','frost','arcane'][Number(key)-1]);}
    else if(key==='m'||key==='ь'){e.preventDefault();toggleMeteor(true);}
    else if(key==='u'||key==='г'){e.preventDefault();if(s.selectedPad)action({type:'upgrade',padId:s.selectedPad});}
  });
  on(document,'visibilitychange',()=>{if(document.hidden){saveCheckpoint();const s=engine.getState();if(['build','wave'].includes(s.phase)&&!s.paused)action({type:'pause',value:true},true);$('pause-note').textContent='Вы переключились на другую вкладку. Продолжите, когда будете готовы.';}previousFrame=0;accumulator=0;syncAudio();});
  on(document,'fullscreenchange',resize);
  function dispose() {
    if(disposed)return;disposed=true;ownedStyle.remove();cancelAnimationFrame(raf);resizeObserver?.disconnect();for(const off of listeners)off();for(const timer of timers)clearTimeout(timer);timers.clear();for(const url of downloadUrls)URL.revokeObjectURL(url);downloadUrls.clear();audio.dispose();renderer.dispose();
    if(window.__GAME_TEST__?.owner===root)delete window.__GAME_TEST__;
  }
  on(window,'pagehide',e=>{saveCheckpoint();if(e.persisted){if(['build','wave'].includes(engine.getState().phase))action({type:'pause',value:true},true);audio.setState({mode:'paused'});}else dispose();});
  on(window,'pageshow',e=>{if(e.persisted){previousFrame=0;accumulator=0;resize();updateUI(true);syncAudio();}});
  window.__GAME_TEST__={ready:true,owner:root,snapshot:()=>engine.snapshot(),act:data=>action(data,true),reset:({seed='20261011'}={})=>{resetSystems(new GameEngine({difficulty:'normal',seed:Number(seed)}));updateUI(true);return engine.snapshot();},setManualMode:value=>{manualMode=!!value;previousFrame=0;accumulator=0;},advance:frames=>{if(!manualMode||!Number.isInteger(frames)||frames<1||frames>3600)throw new Error('Invalid manual advancement');for(let i=0;i<frames;i++){engine.act({type:'tick'});drainEvents();}updateUI(true);renderer.render(0,{reducedMotion:prefs.reducedMotion});return engine.snapshot();},events:()=>displayEvents.slice(),dispose};
  refreshContinue();syncAudio();updateUI(true);resize();raf=requestAnimationFrame(renderLoop);
  return {dispose};
}
