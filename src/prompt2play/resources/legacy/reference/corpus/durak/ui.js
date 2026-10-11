function mountGame(host) {
  const root=window;
  if(root.__DURAK_CORPUS_MOUNT__)root.__DURAK_CORPUS_MOUNT__.dispose();
  let forgeManualMode=false,forgeDisposed=false,forgePendingSeed=null;

  const renderer = new GameRenderer(host).bind(()=>renderOriginal());
  const E = root.DurakEngine;
  const B = root.DurakBots;
  const doc = root.document;
  host.innerHTML="<style>:root{color-scheme:dark;--bg:#102923;--felt:#174c3d;--ink:#f0eee2;--muted:#9aafa3;--gold:#e7c788;--gold-bright:#f3dab0;--card:#fbf7e9;--red:#b54342;--line:rgba(218,235,216,.12);font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif;font-synthesis:none}\n*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 50% -20%,#284d3d 0,transparent 65%),var(--bg);color:var(--ink);font-size:14px;line-height:1.45;overflow-x:hidden}button,input{font:inherit}button{color:inherit;cursor:pointer}button:disabled{cursor:default}button:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--gold-bright);outline-offset:5px}button{-webkit-tap-highlight-color:transparent}button svg{width:19px;height:19px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}button[hidden],[hidden]{display:none!important}body.modal-open{overflow:hidden}.ambient{position:fixed;pointer-events:none;border-radius:50%;filter:blur(90px);opacity:.12;z-index:-1}.ambient-one{width:35vw;height:35vw;background:#84a775;top:5%;left:-20%}.ambient-two{width:30vw;height:30vw;background:#ad8d48;bottom:-25%;right:-15%}.app-shell{max-width:1440px;margin:0 auto;padding:0 42px 22px}.topbar{height:100px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);gap:18px}.brand{display:flex;align-items:center;gap:13px;flex-shrink:0}.brand-mark{width:44px;height:49px;border:1px solid rgba(231,199,136,.45);border-radius:10px;display:grid;place-items:center;font-size:35px;color:var(--gold);transform:rotate(-7deg);box-shadow:3px 3px 0 rgba(231,199,136,.08)}.brand-name{display:block;font:29px/1.05 Georgia,\"Times New Roman\",serif;letter-spacing:-.8px}.brand-caption{display:block;font-size:8px;letter-spacing:2.5px;color:var(--gold);margin-top:8px}.toolbar{display:flex;align-items:center;gap:7px}.tool-button{display:flex;align-items:center;justify-content:center;gap:8px;min-height:39px;padding:8px 11px;background:transparent;border:0;border-radius:8px;color:#b6c6ba;font-size:12px;white-space:nowrap;transition:background .18s,color .18s}.tool-button:hover{background:rgba(255,255,255,.055);color:var(--ink)}.tool-button[aria-pressed=true]{color:var(--gold)}.tool-button .sound-waves{display:none}.tool-button[aria-pressed=true] .sound-waves{display:block}.tool-button[aria-pressed=true] .sound-cross{display:none}.help-icon{width:18px;height:18px;border:1.5px solid currentColor;border-radius:50%;font-size:12px;display:grid;place-items:center;line-height:1}.toolbar-separator{width:1px;height:21px;background:var(--line);margin:0 8px}.new-button{border:1px solid rgba(231,199,136,.22);color:var(--gold);padding-right:14px;padding-left:13px}.match-meta{display:flex;justify-content:space-between;align-items:center;padding:22px 2px 15px;gap:12px}.match-badge{display:flex;align-items:center;gap:8px;font-size:9px;letter-spacing:1.6px;font-weight:650;color:#c3d0c3}.status-dot{width:6px;height:6px;border-radius:50%;background:#a4c48f;box-shadow:0 0 10px rgba(153,193,125,.2)}.save-status{color:#839e8e;font-size:10px;max-width:55%;text-align:right}.save-status.warning{color:var(--gold)}.game-table{position:relative;background:radial-gradient(ellipse at 50% 40%,rgba(80,131,85,.15),transparent 70%),repeating-linear-gradient(110deg,rgba(255,255,255,.009) 0px,rgba(255,255,255,.009) 1px,transparent 1px,transparent 3px),#194b3e;border:1px solid rgba(201,222,174,.17);border-radius:30px;min-height:379px;box-shadow:inset 0 0 0 7px rgba(8,27,22,.18),inset 0 0 0 8px rgba(220,211,166,.06),0 15px 38px rgba(3,18,13,.16);overflow:hidden}.table-watermark{position:absolute;top:50%;left:50%;transform:translate(-50%,-25%);display:flex;align-items:center;flex-direction:column;color:rgba(215,230,194,.045);pointer-events:none}.table-watermark span{font-size:115px;line-height:.9}.table-watermark small{font-size:9px;letter-spacing:5px;white-space:nowrap;margin-top:8px}.opponents{display:flex;align-items:flex-start;justify-content:center;gap:clamp(24px,7vw,100px);position:relative;z-index:1;min-height:133px;padding:22px 100px 5px}.seat{min-width:116px;text-align:center;position:relative}.seat-heading{display:flex;align-items:center;justify-content:center;gap:8px}.seat-avatar{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;background:#315348;color:#d2d8bf;font:15px Georgia,serif;border:1px solid rgba(226,226,173,.2);transition:box-shadow .2s,border .2s}.seat[data-seat=\"2\"] .seat-avatar{background:#4a5140;color:#ece0c7}.seat[data-seat=\"3\"] .seat-avatar{background:#324d52;color:#bfd8d3}.seat.active .seat-avatar{box-shadow:0 0 0 3px rgba(231,199,136,.14);border-color:var(--gold)}.seat.out .seat-avatar{background:rgba(158,187,117,.17);border-color:#859f69;color:#cbe1aa}.seat-info{text-align:left;min-width:70px}.seat-name{display:block;font-size:12px;font-weight:650;color:#e8ebdb}.seat-role{display:block;font-size:9px;color:#8cae98;margin-top:1px}.seat.active .seat-role{color:var(--gold)}.seat-hand{height:51px;position:relative;margin:10px auto 0;width:106px;display:flex;justify-content:center}.seat-hand .mini-back{position:absolute;width:30px;height:43px;border-radius:4px;border:1px solid #becaae;background:repeating-linear-gradient(45deg,rgba(180,197,162,.2) 0,rgba(180,197,162,.2) 1px,transparent 1px,transparent 5px),#1d3f37;box-shadow:0 1px 4px #0e3028;transform:translateX(var(--x)) rotate(var(--r));top:2px}.seat-hand .mini-back:after{content:'◆';position:absolute;inset:4px;display:grid;place-items:center;border:1px solid rgba(207,216,187,.35);font-size:12px;color:#b7c4a2}.seat-card-count{position:absolute;right:-3px;bottom:0;min-width:24px;height:24px;border-radius:50%;padding:3px 6px;background:#e8e5d1;color:#294638;font-size:11px;font-weight:750;border:2px solid #194b3e;z-index:8}.seat-out-mark{font-size:10px;letter-spacing:1px;color:#adc990;padding-top:12px}.thinking{display:inline-flex;gap:3px;vertical-align:middle;margin-left:5px}.thinking i{display:block;width:3px;height:3px;background:currentColor;border-radius:50%;animation:thinking 1.15s infinite}.thinking i:nth-child(2){animation-delay:.16s}.thinking i:nth-child(3){animation-delay:.32s}@keyframes thinking{0%,65%,100%{opacity:.25;transform:translateY(0)}35%{opacity:1;transform:translateY(-2px)}}.table-middle{position:relative;display:grid;grid-template-columns:130px minmax(0,1fr) 114px;gap:10px;align-items:center;padding:3px 27px 25px;min-height:227px}.deck-zone{padding:4px 0 0;align-self:center;text-align:center}.deck-stack{position:relative;width:115px;height:96px;isolation:isolate;margin:0 auto 9px;display:flex;align-items:center;justify-content:center}.deck-back{position:absolute;width:57px;height:81px;border-radius:6px;border:2px solid #e9e5ce;background:repeating-linear-gradient(45deg,rgba(213,222,187,.16) 0,rgba(213,222,187,.16) 1px,transparent 1px,transparent 6px),#264e42;box-shadow:2px 2px 0 #6b8165,4px 4px 0 #c8d0b6,5px 6px 5px rgba(5,22,15,.3);z-index:2;left:17px;top:3px;transform:rotate(-8deg)}.deck-back:before{content:'';position:absolute;inset:5px;border:1px solid #98af83;border-radius:2px}.deck-back:after{content:'♠';position:absolute;inset:12px;display:grid;place-items:center;font-size:30px;color:#c5cfaa}.trump-card{position:absolute;width:57px;height:81px;right:4px;top:12px;transform:rotate(82deg);z-index:1;box-shadow:1px 2px 6px #0c2c21;border-radius:5px}.deck-stack.empty{border:1px dashed rgba(195,215,178,.2);border-radius:8px;width:65px;height:89px;color:rgba(202,220,180,.28);font-size:32px;box-shadow:none}.deck-stack.last .trump-card{right:29px;top:5px;transform:rotate(-5deg)}.deck-caption{display:flex;align-items:baseline;justify-content:center;gap:5px;font-size:10px;color:#9db5a2}.deck-caption strong{font-size:17px;font-weight:600;color:#e7eddb}.trump-label{font-size:9px;color:#c9d5bd;margin-top:4px}.trump-symbol{font-size:16px;vertical-align:-1px;margin-left:4px;color:#e7d2ae}.trump-symbol.red{color:#eb9b8f}.battlefield-wrap{min-width:0;position:relative;align-self:stretch;display:flex;align-items:center;justify-content:center;padding:10px 0 20px}.battlefield{display:grid;grid-template-columns:repeat(3,minmax(0,95px));gap:18px 17px;justify-content:center;align-items:center;min-height:173px;width:100%;position:relative;z-index:1}.battlefield[data-pairs=\"0\"]{display:flex}.battlefield[data-pairs=\"1\"]{grid-template-columns:95px}.battlefield[data-pairs=\"2\"]{grid-template-columns:repeat(2,95px)}.battlefield[data-pairs=\"4\"],.battlefield[data-pairs=\"5\"],.battlefield[data-pairs=\"6\"]{grid-template-columns:repeat(3,minmax(0,95px));row-gap:16px}.empty-table{text-align:center;color:#93b29a;padding:10px;max-width:300px}.empty-table .empty-suit{display:block;font-size:30px;color:#c6cc9e;opacity:.45;margin-bottom:7px}.empty-table strong{display:block;color:#c1d0b5;font:21px/1.2 Georgia,serif;margin-bottom:7px}.empty-table p{font-size:11px;line-height:1.6;margin:0;color:#8eb096}.card-pair{position:relative;width:95px;height:124px;justify-self:center;transition:transform .2s}.card-pair.uncovered:after{content:'';position:absolute;inset:-6px 12px -1px -7px;border:1px dashed rgba(231,199,136,.25);border-radius:10px;pointer-events:none;z-index:-1}.card-pair.targeted:after{border:1px solid rgba(242,212,152,.65);box-shadow:0 0 20px rgba(241,199,113,.08)}.table-card{position:absolute;width:76px;height:108px;border-radius:7px;box-shadow:1px 4px 8px rgba(1,23,16,.28);transform:rotate(-6deg);padding:0;border:0;background:var(--card);overflow:hidden}.table-card.defense-card{left:21px;top:15px;transform:rotate(8deg);z-index:2}.table-card.target-card{cursor:pointer}.table-card.target-card:hover{transform:rotate(-6deg) translateY(-3px)}.table-card:focus-visible{outline-offset:5px}.card-art{width:100%;height:100%;display:block;border-radius:inherit}.card-pair .target-label{position:absolute;top:112px;left:-4px;font-size:8px;text-align:center;right:15px;color:var(--gold);letter-spacing:.1px}.card-arrive{animation:card-arrive .32s cubic-bezier(.22,.61,.36,1) both}@keyframes card-arrive{from{opacity:0;translate:0 22px;scale:.88}to{opacity:1;translate:0 0;scale:1}}.battlefield.settling .card-pair{animation:round-clear .65s .12s ease-in both}.battlefield.settling.taken .card-pair{animation-name:round-take}@keyframes round-clear{0%,35%{opacity:1;translate:0 0}100%{opacity:0;translate:110px -14px;scale:.7}}@keyframes round-take{0%,35%{opacity:1;translate:0 0}100%{opacity:0;translate:0 35px;scale:.8}}.round-toast{position:absolute;bottom:-5px;left:50%;transform:translateX(-50%);max-width:100%;white-space:nowrap;color:#e3d1a3;font-size:11px;font-weight:600;letter-spacing:.4px;background:rgba(12,42,30,.76);padding:7px 14px;border-radius:30px;border:1px solid rgba(232,218,167,.15);opacity:0;transition:opacity .2s;z-index:3;pointer-events:none}.round-toast.visible{opacity:1}.round-zone{align-self:center;text-align:center;color:#a6b79c}.round-number{display:flex;flex-direction:column;gap:1px;margin-bottom:20px}.round-number span{font-size:8px;letter-spacing:2px}.round-number strong{font:36px/1.1 Georgia,serif;color:#d6dbb8;font-weight:400}.discard-counter{display:flex;align-items:center;justify-content:center;gap:5px;font-size:9px}.discard-counter strong{font-size:13px;color:#c6d0b6;font-weight:550}.discard-icon{font-size:22px;line-height:1;color:#a9be9b;transform:rotate(-10deg)}.round-limit{font-size:9px;color:#8ea788;margin:10px auto 0;max-width:110px;line-height:1.45}.hand-panel{position:relative;padding:22px 5px 0}.hand-caption{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:6px}.human-heading{display:flex;align-items:center;gap:9px}.human-avatar{height:32px;width:32px;border-radius:50%;background:#bfb084;color:#263c2e;display:grid;place-items:center;font-size:12px;font-weight:700;box-shadow:0 0 0 3px rgba(226,209,155,.06)}.human-heading strong{display:block;font-size:12px;font-weight:650}.human-heading #human-role{display:block;font-size:9px;color:#9eb19b;margin-top:1px}.hand-count{font-size:9px;padding:3px 7px;border:1px solid rgba(225,235,212,.11);border-radius:5px;color:#bdcbb8;margin-left:6px}.hand-hint{color:#869c89;font-size:10px;text-align:right}.hand-scroll{overflow-x:auto;overflow-y:hidden;padding:18px 8px 12px;scrollbar-width:thin;scrollbar-color:#576a4e transparent;scroll-padding-inline:15px;min-height:178px;overscroll-behavior-x:contain}.hand-scroll::-webkit-scrollbar{height:5px}.hand-scroll::-webkit-scrollbar-thumb{background:#576a4e;border-radius:10px}.hand{display:flex;align-items:center;justify-content:center;gap:10px;min-width:100%;width:max-content;margin:0 auto;padding:0 6px}.hand-card{position:relative;width:88px;height:125px;flex:0 0 88px;padding:0;border:0;border-radius:8px;background:var(--card);box-shadow:0 5px 11px rgba(1,17,10,.18),0 0 0 1px rgba(8,31,20,.2);transition:transform .2s ease,box-shadow .2s,filter .2s;transform-origin:50% 90%}.hand-card:after{position:absolute;inset:0;border-radius:inherit;border:2px solid transparent;content:'';pointer-events:none}.hand-card:not(:disabled):hover{transform:translateY(-9px);box-shadow:0 10px 19px rgba(1,17,10,.22)}.hand-card:disabled{filter:brightness(.79) saturate(.65)}.hand-card.selectable{box-shadow:0 5px 11px rgba(1,17,10,.2),0 0 0 1px rgba(235,201,140,.75)}.hand-card.selected,.hand-card.selected:not(:disabled):hover{transform:translateY(-13px);box-shadow:0 9px 20px rgba(1,17,10,.24),0 0 0 3px var(--gold)}.hand-card .selected-check{position:absolute;right:-6px;top:-7px;width:20px;height:20px;display:grid;place-items:center;background:var(--gold);border-radius:50%;color:#244033;box-shadow:0 1px 3px #173127;font-size:11px;font-weight:800}.hand-card .trump-badge{position:absolute;left:50%;bottom:-6px;transform:translateX(-50%);border-radius:9px;background:#bf9e56;border:1px solid #f0d99d;color:#183c2f;font-size:7px;font-weight:800;letter-spacing:.6px;padding:1px 5px;box-shadow:0 1px 4px #26412a}.deal-in{animation:deal-in .42s both}@keyframes deal-in{from{opacity:0;translate:30px -30px;rotate:10deg;scale:.85}to{opacity:1;translate:0 0;rotate:0;scale:1}}.no-hand{min-height:125px;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:8px;color:#93ac92}.no-hand strong{font:23px Georgia,serif;color:#d1dac0}.no-hand p{font-size:11px;margin:0}.no-hand .spectator-mark{font-size:25px;color:var(--gold)}.action-bar{display:flex;align-items:center;justify-content:space-between;gap:18px;min-height:77px;border-top:1px solid var(--line);padding:17px 0 16px}.turn-copy{min-width:0;flex:1}.turn-label{font-size:8px;letter-spacing:1.9px;font-weight:750;color:#a8bb97}.turn-copy p{font-size:12px;line-height:1.45;margin:5px 0 0;color:#c8d4c0}.human-turn .turn-label{color:var(--gold)}.action-buttons{display:flex;align-items:center;justify-content:flex-end;gap:9px;flex-shrink:0}.button{border:1px solid transparent;min-height:44px;padding:11px 19px;border-radius:9px;font-size:11px;font-weight:650;letter-spacing:.1px;display:inline-flex;align-items:center;justify-content:center;gap:15px;transition:background .18s,transform .18s,border-color .18s,opacity .18s}.button:not(:disabled):active{transform:translateY(1px)}.button-gold{background:var(--gold);color:#24392c;box-shadow:0 3px 13px rgba(0,0,0,.07)}.button-gold:not(:disabled):hover{background:var(--gold-bright)}.button-gold:disabled{background:#345143;color:#90a086;box-shadow:none;border-color:rgba(187,206,162,.07)}.button-outline{background:transparent;border-color:rgba(205,220,185,.25);color:#d6dec7}.button-outline:not(:disabled):hover{background:rgba(220,232,203,.055);border-color:rgba(225,224,176,.5)}.button-subtle{color:#e0c3a5;background:rgba(183,109,77,.09);border-color:rgba(196,149,103,.24)}.button-subtle:hover{background:rgba(183,109,77,.17)}.play-button{min-width:169px}.play-button span{font-size:16px;line-height:1}.game-footer{border-top:1px solid rgba(218,235,216,.055);display:flex;align-items:center;justify-content:space-between;gap:15px;padding:14px 5px 0;font-size:9px;color:#708c79}.last-move{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.history-button{display:flex;align-items:center;gap:10px;color:#9aa98d;background:none;border:0;padding:4px 0;font-size:10px;white-space:nowrap}.history-button:hover{color:var(--gold)}.history-panel{margin:17px 5px 0;padding:18px 23px;border:1px solid var(--line);background:rgba(4,25,17,.22);border-radius:12px}.history-heading{display:flex;align-items:center;justify-content:space-between;gap:10px}.history-heading h2{font:22px Georgia,serif;font-weight:400;margin:0}.history-panel ol{padding-left:20px;margin:15px 0 0;display:flex;flex-direction:column;gap:6px;max-height:225px;overflow-y:auto;color:#a5ba9e;font-size:11px}.history-panel li::marker{color:#667e63}.notice{font-size:11px;color:#e8cba6;background:rgba(120,64,25,.14);padding:10px 14px;border:1px solid rgba(232,185,128,.19);border-radius:7px;margin:8px 0}.modal-overlay{position:fixed;inset:0;z-index:30;display:flex;align-items:center;justify-content:center;overflow-y:auto;padding:28px 20px;background:rgba(5,18,13,.73);backdrop-filter:blur(9px);-webkit-backdrop-filter:blur(9px)}.modal-card{position:relative;width:100%;max-width:465px;border:1px solid rgba(205,208,161,.24);border-radius:25px;padding:35px;background:radial-gradient(ellipse at 50% 0%,rgba(138,158,96,.09),transparent 70%),#183b2f;box-shadow:0 30px 110px rgba(0,0,0,.3);flex-shrink:0}.modal-close{position:absolute;top:15px;right:17px;z-index:5;border:1px solid rgba(218,226,193,.12);background:rgba(220,226,193,.04);width:31px;height:31px;line-height:25px;border-radius:50%;font-size:23px;color:#bcc8ac;font-weight:300;display:grid;place-items:center}.modal-close:hover{background:rgba(220,226,193,.1);color:var(--gold)}.welcome-card{text-align:center;padding-top:22px}.welcome-art{height:142px;position:relative;width:205px;margin:0 auto 19px}.welcome-playing-card{position:absolute;width:81px;height:115px;border-radius:7px;box-shadow:0 6px 19px rgba(0,0,0,.22);overflow:hidden}.welcome-playing-card.queen{left:43px;top:9px;transform:rotate(-15deg)}.welcome-playing-card.ace{left:97px;top:20px;transform:rotate(13deg)}.welcome-card-back{position:absolute;width:81px;height:115px;border:2px solid #e0d6b0;border-radius:7px;left:9px;top:24px;transform:rotate(-28deg);background:repeating-linear-gradient(45deg,rgba(188,199,157,.3) 0,rgba(188,199,157,.3) 1px,transparent 1px,transparent 6px),#284c3e;box-shadow:0 5px 16px rgba(0,0,0,.2)}.welcome-card-back:after{content:'◆';position:absolute;inset:7px;border:1px solid #bfc59a;display:grid;place-items:center;font-size:30px;color:#c6ceaa;border-radius:3px}.art-star{position:absolute;font-size:26px;color:#c9b475;font-weight:300}.star-one{left:-16px;top:12px;transform:rotate(15deg)}.star-two{right:-14px;bottom:8px;font-size:20px}.eyebrow{display:block;color:#b7b98c;font-size:8px;font-weight:650;letter-spacing:2.1px}.welcome-card h1{font:69px/.98 Georgia,\"Times New Roman\",serif;font-weight:400;letter-spacing:-4px;margin:12px 0 18px;color:#f1e8d4}.welcome-copy{font-size:12px;color:#aabd9e;line-height:1.7;margin:0 0 26px}.player-picker{border:0;padding:0;margin:0 0 22px;min-width:0}.player-picker legend{width:100%;font-size:11px;color:#d4dcc2;margin-bottom:12px}.player-options{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.player-option{background:rgba(9,32,21,.24);border:1px solid rgba(200,215,175,.16);border-radius:10px;display:flex;flex-direction:column;align-items:center;padding:11px 3px 10px;gap:3px;transition:background .2s,border-color .2s}.player-option:hover{border-color:rgba(231,199,136,.55)}.player-option strong{font:29px/1.1 Georgia,serif;font-weight:400;color:#d1dcc0}.player-option span{font-size:8px;color:#8fa687;white-space:nowrap}.player-option.selected{background:rgba(231,199,136,.11);border-color:var(--gold)}.player-option.selected strong{color:var(--gold)}.player-option.selected span{color:#d6caa5}.welcome-start{width:100%;font-size:12px;min-height:48px;justify-content:space-between;padding-left:20px;padding-right:20px}.welcome-start span{font-size:22px;line-height:1;font-weight:400}.welcome-resume{width:100%;margin-top:9px;min-height:42px}.welcome-foot{margin-top:22px;display:flex;align-items:center;justify-content:space-between;gap:8px;color:#779477;font-size:9px}.text-button{padding:4px 0;background:transparent;border:0;color:#c3c398;font-size:10px}.text-button:hover{color:var(--gold)}.text-button span{margin-left:4px}.rules-card{max-width:600px;padding:36px 38px;max-height:min(90vh,900px);overflow-y:auto;scrollbar-width:thin;scrollbar-color:#667751 #183b2f}.rules-card h2,.result-card h2{font:36px/1.12 Georgia,serif;font-weight:400;letter-spacing:-1px;margin:13px 0 16px;color:#f1e8d4}.rules-intro{color:#b0c09f;font-size:12px;line-height:1.65;margin-bottom:23px}.rules-list{display:flex;flex-direction:column;gap:19px}.rules-list section{display:grid;grid-template-columns:24px 1fr;gap:14px}.rule-number{font:18px/1.2 Georgia,serif;color:#bdae77;margin-top:2px}.rules-list h3{font-size:12px;color:#dbe2c8;font-weight:650;margin:0 0 5px}.rules-list p{font-size:11px;color:#a4b898;line-height:1.7;margin:0}.rules-list p+p{margin-top:6px}.rules-controls{font-size:9px;line-height:2;color:#869f7e;border-top:1px solid var(--line);padding-top:16px;margin-top:24px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}.keyboard-key{border:1px solid #68805f;border-radius:4px;font-size:8px;padding:0 5px;color:#b6c59d}.keyboard-key+span{margin-left:10px}.rules-done{width:100%;margin-top:20px}.result-card{text-align:center;padding-top:37px}.result-emblem{color:var(--gold);font-size:66px;line-height:1.15;margin:0 auto 22px;position:relative;width:100px}.result-emblem:before,.result-emblem:after{content:'✧';position:absolute;font-size:19px;top:3px;left:-3px}.result-emblem:after{left:auto;right:0;top:45px;font-size:14px}.result-card h2{font-size:42px}.result-copy{font-size:13px;line-height:1.65;color:#aebf9d;margin:0 0 23px}.result-summary{display:flex;justify-content:center;gap:28px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:15px 0;margin-bottom:23px}.result-summary div{display:flex;flex-direction:column;gap:4px}.result-summary strong{font:25px Georgia,serif;font-weight:400;color:#d7d9b8}.result-summary span{font-size:9px;color:#8ea27d}.result-card>.text-button{margin-top:15px}.noscript-notice{position:fixed;inset:0;z-index:100;display:grid;place-items:center;padding:30px;text-align:center;background:#183b2f;color:#e7c788;font-size:20px}\n@media(min-width:1250px){.game-table{min-height:398px}.table-middle{grid-template-columns:160px minmax(0,1fr) 145px;min-height:246px;padding-left:37px;padding-right:37px}.battlefield{grid-template-columns:repeat(3,110px);gap:17px 22px}.battlefield[data-pairs=\"1\"]{grid-template-columns:110px}.battlefield[data-pairs=\"2\"]{grid-template-columns:repeat(2,110px)}.battlefield[data-pairs=\"4\"],.battlefield[data-pairs=\"5\"],.battlefield[data-pairs=\"6\"]{grid-template-columns:repeat(3,110px)}.hand-card{width:94px;height:134px;flex-basis:94px}.hand-scroll{min-height:187px}.opponents{padding-top:25px;min-height:141px}.game-footer{padding-top:17px}.topbar{height:107px}}\n@media(max-width:1000px){.app-shell{padding:0 24px 20px}.toolbar{gap:3px}.tool-button{padding:8px;font-size:11px;gap:6px}.toolbar-separator{margin:0 4px}.topbar{height:91px}.table-middle{grid-template-columns:105px minmax(0,1fr) 86px;padding:0 15px 22px;gap:4px}.battlefield{gap:17px 13px}.opponents{padding-left:70px;padding-right:70px;gap:42px}.deck-stack{transform:scale(.9);transform-origin:center;margin-bottom:2px}.deck-zone{margin-left:-5px}.action-buttons{gap:6px}.button{padding-left:14px;padding-right:14px}.play-button{min-width:145px}.turn-copy p{font-size:11px}.hand{gap:8px}.hand-card{width:81px;height:115px;flex-basis:81px}.hand-scroll{min-height:167px}.round-limit{font-size:8px}}\n@media(max-width:760px){.app-shell{padding:0 16px 18px}.topbar{height:84px;gap:12px}.brand-mark{width:36px;height:42px;font-size:29px;border-radius:8px}.brand{gap:10px}.brand-name{font-size:26px}.brand-caption{font-size:6px;letter-spacing:1.8px;margin-top:6px}.tool-button>span:not(.help-icon){display:none}.toolbar{gap:5px}.tool-button{width:34px;height:36px;padding:7px;min-height:36px}.tool-button svg{width:18px;height:18px}.toolbar-separator{display:none}.new-button{margin-left:4px}.match-meta{padding-top:17px;padding-bottom:11px}.match-badge{font-size:8px;letter-spacing:1.1px}.save-status{font-size:8px}.game-table{border-radius:24px;min-height:342px}.opponents{padding:19px 24px 4px;min-height:125px;gap:22px}.seat{min-width:94px}.seat-avatar{width:28px;height:28px;font-size:13px}.seat-heading{gap:6px}.seat-info{min-width:58px}.seat-name{font-size:10px}.seat-role{font-size:8px}.seat-hand{width:84px;height:45px;margin-top:10px}.seat-hand .mini-back{width:26px;height:37px}.seat-card-count{min-width:22px;height:22px;font-size:9px;bottom:0;right:-1px}.table-middle{grid-template-columns:85px minmax(0,1fr) 63px;min-height:208px;padding:0 10px 21px;gap:2px}.deck-stack{transform:scale(.73);width:110px;height:86px;margin-left:-8px;margin-bottom:-6px;transform-origin:50% 50%}.deck-stack.empty{margin:0 auto 9px;width:53px;height:73px;transform:none;font-size:27px}.deck-stack.last .trump-card{right:24px}.deck-caption strong{font-size:15px}.deck-caption span{font-size:8px}.trump-label{font-size:8px}.trump-symbol{font-size:13px}.round-number strong{font-size:30px}.round-number span{font-size:7px;letter-spacing:1.5px}.discard-counter{gap:3px;font-size:7px;flex-wrap:wrap}.discard-counter strong{font-size:12px}.discard-icon{font-size:18px}.round-limit{font-size:7px;max-width:62px}.round-number{margin-bottom:17px}.card-pair{width:81px;height:107px}.table-card{width:65px;height:93px;border-radius:5px}.table-card.defense-card{left:17px;top:13px}.card-pair .target-label{top:96px;font-size:7px;right:11px}.battlefield{grid-template-columns:repeat(3,81px);gap:12px 10px;min-height:152px}.battlefield[data-pairs=\"1\"]{grid-template-columns:81px}.battlefield[data-pairs=\"2\"]{grid-template-columns:repeat(2,81px)}.battlefield[data-pairs=\"4\"],.battlefield[data-pairs=\"5\"],.battlefield[data-pairs=\"6\"]{grid-template-columns:repeat(3,81px)}.hand-panel{padding:17px 1px 0}.human-avatar{width:28px;height:28px;font-size:11px}.human-heading{gap:7px}.human-heading strong{font-size:11px}.human-heading #human-role{font-size:8px}.hand-count{font-size:8px;margin-left:3px}.hand-hint{font-size:9px;max-width:48%}.hand-scroll{padding:18px 5px 10px;min-height:158px}.hand{gap:7px;padding:0 3px}.hand-card{width:76px;height:108px;flex-basis:76px;border-radius:6px}.hand-card .trump-badge{font-size:6px;bottom:-5px}.hand-card .selected-check{width:18px;height:18px;font-size:10px;right:-4px;top:-5px}.action-bar{gap:12px;align-items:stretch;flex-direction:column;padding-top:14px}.turn-label{font-size:8px}.turn-copy p{margin-top:4px;font-size:11px;min-height:16px}.action-buttons{width:100%;gap:8px}.action-buttons .button{min-height:43px;flex:1;padding:9px 10px;font-size:10px}.play-button{min-width:136px;max-width:none}.hand-panel .action-buttons:has(>button:not([hidden]):only-of-type){justify-content:flex-end}.game-footer{padding-top:11px;font-size:8px}.history-button{font-size:9px}.round-toast{font-size:9px;padding:6px 10px;bottom:-7px}.empty-table strong{font-size:18px}.empty-table p{font-size:10px}.empty-table .empty-suit{font-size:26px}.history-panel{margin-left:0;margin-right:0;padding:17px}.history-panel li{font-size:10px}}\n@media(max-width:540px){.app-shell{padding-left:12px;padding-right:12px}.topbar{height:76px}.brand-caption{letter-spacing:1.5px;font-size:5.5px}.brand-mark{width:31px;height:36px;font-size:25px}.brand-name{font-size:23px}.brand{gap:8px}.toolbar{gap:2px}.tool-button{width:30px;height:33px;min-height:33px;padding:6px}.tool-button svg{width:17px;height:17px}.new-button{margin-left:2px}.match-meta{padding-top:15px;padding-bottom:10px;gap:9px}.match-badge{font-size:7px;letter-spacing:1px;gap:6px}.status-dot{width:5px;height:5px}.save-status{font-size:7px;max-width:52%}.game-table{min-height:340px;border-radius:21px}.opponents{padding:17px 12px 0;min-height:118px;gap:8px;justify-content:space-evenly}.seat{min-width:85px;max-width:100px}.seat-heading{gap:5px}.seat-avatar{width:25px;height:25px;font-size:12px}.seat-info{min-width:52px}.seat-name{font-size:9px}.seat-role{font-size:7px}.seat-hand{width:70px;margin-top:10px;transform:scale(.94);transform-origin:50% 0}.seat-card-count{right:-5px}.table-middle{grid-template-columns:55px minmax(0,1fr) 43px;gap:4px;padding:0 9px 24px;min-height:203px}.deck-zone{margin-left:-5px}.deck-stack{transform:scale(.54);transform-origin:left center;width:112px;margin-left:0;margin-bottom:-11px;height:82px}.deck-stack.empty{width:40px;height:58px;font-size:22px;margin-left:9px;margin-bottom:8px}.deck-caption{gap:3px;flex-direction:column;align-items:center;line-height:1.15}.deck-caption strong{font-size:15px}.deck-caption span{font-size:7px}.trump-label{font-size:0;margin-top:5px}.trump-symbol{font-size:18px;margin:0}.round-zone{align-self:center}.round-number{margin-bottom:16px}.round-number span{font-size:6px;letter-spacing:1px}.round-number strong{font-size:25px}.discard-counter{flex-wrap:wrap;gap:1px;font-size:7px;line-height:1.4}.discard-counter>span:last-child{flex:0 0 100%}.discard-icon{font-size:17px}.discard-counter strong{font-size:11px}.round-limit{font-size:6px;line-height:1.5;margin-top:10px;max-width:43px}.battlefield-wrap{padding-top:7px;padding-bottom:17px}.battlefield{grid-template-columns:repeat(2,78px);gap:14px 15px;min-height:145px}.battlefield[data-pairs=\"1\"]{grid-template-columns:78px}.battlefield[data-pairs=\"2\"]{grid-template-columns:repeat(2,78px)}.battlefield[data-pairs=\"3\"],.battlefield[data-pairs=\"4\"],.battlefield[data-pairs=\"5\"],.battlefield[data-pairs=\"6\"]{grid-template-columns:repeat(2,minmax(0,78px));row-gap:12px}.card-pair{width:76px;height:103px}.table-card{width:61px;height:87px}.table-card.defense-card{left:16px;top:12px}.card-pair .target-label{top:92px;left:-4px;font-size:6px}.card-pair.uncovered:after{inset:-5px 10px 1px -5px;border-radius:8px}.empty-table{padding:6px;max-width:190px}.empty-table strong{font-size:19px;line-height:1.15;margin-bottom:8px}.empty-table p{font-size:9px;line-height:1.6}.empty-table .empty-suit{font-size:29px;margin-bottom:8px}.round-toast{font-size:8px;max-width:calc(100% + 35px);white-space:normal;text-align:center;line-height:1.45;width:max-content;padding:5px 10px;bottom:-12px}.hand-panel{padding-top:15px}.hand-caption{align-items:flex-start;margin-bottom:2px}.hand-hint{max-width:43%;font-size:8px;padding-top:3px}.human-heading{gap:6px}.human-avatar{width:26px;height:26px;font-size:10px}.human-heading strong{font-size:10px}.human-heading #human-role{font-size:7px}.hand-count{font-size:7px;padding:2px 5px;margin-left:2px;white-space:nowrap}.hand-scroll{min-height:151px;padding-left:1px;padding-right:1px}.hand{gap:6px;padding-left:5px;padding-right:6px}.hand-card{width:72px;height:103px;flex-basis:72px}.hand-card.selected,.hand-card.selected:not(:disabled):hover{transform:translateY(-11px)}.hand-card:disabled{filter:brightness(.85) saturate(.7)}.action-bar{padding-top:12px;padding-bottom:12px;gap:12px}.turn-copy p{font-size:10px;line-height:1.55}.turn-label{font-size:7px;letter-spacing:1.4px}.action-buttons .button{font-size:9px;gap:7px;min-height:42px;padding-left:10px;padding-right:10px}.play-button{min-width:134px}.action-buttons #btn-pass{max-width:180px}.game-footer{gap:11px;font-size:7px;padding-left:0;padding-right:0}.history-button{font-size:8px;gap:5px}.last-move{max-width:73%}.modal-overlay{padding:18px 13px;align-items:center}.modal-card{padding:28px 24px;border-radius:22px}.welcome-card{padding-top:20px;max-width:390px}.welcome-art{height:128px;transform:scale(.92);transform-origin:50% 0;margin-bottom:4px}.eyebrow{font-size:7px;letter-spacing:1.8px}.welcome-card h1{font-size:61px;margin-top:12px;margin-bottom:16px}.welcome-copy{font-size:11px;margin-bottom:21px}.player-picker legend{font-size:10px;margin-bottom:11px}.player-option strong{font-size:28px}.player-option span{font-size:7px}.player-options{gap:7px}.player-option{padding:10px 2px}.welcome-start{font-size:11px;min-height:47px}.welcome-foot{font-size:8px;margin-top:18px}.text-button{font-size:9px}.welcome-resume{font-size:10px}.rules-card{padding:31px 24px;max-height:90vh}.rules-card h2{font-size:29px;margin-top:14px}.rules-intro{font-size:11px}.rules-list section{grid-template-columns:22px 1fr;gap:9px}.rules-list h3{font-size:11px}.rules-list p{font-size:10px}.rule-number{font-size:17px}.rules-controls{font-size:8px;gap:5px}.result-card h2{font-size:36px}.result-copy{font-size:12px}.result-emblem{font-size:59px;margin-bottom:21px}.no-hand{min-height:104px}.no-hand strong{font-size:20px}.no-hand p{font-size:9px;text-align:center}.table-watermark span{font-size:90px}.table-watermark small{font-size:7px;letter-spacing:3px}}\n@media(max-width:359px){.brand-caption{display:none}.brand-name{font-size:22px}.brand{gap:7px}.toolbar{gap:1px}.tool-button{width:28px}.table-middle{grid-template-columns:42px minmax(0,1fr) 34px;padding-left:7px;padding-right:7px;gap:4px}.deck-zone{margin-left:-8px}.deck-stack{transform:scale(.46);margin-left:3px}.deck-caption{margin-left:5px}.deck-stack.empty{margin-left:11px;width:33px;height:49px}.round-number span{font-size:5px}.round-limit{font-size:5.5px}.opponents{padding-left:5px;padding-right:5px;gap:1px}.seat{min-width:79px}.seat-avatar{width:22px;height:22px}.seat-info{min-width:47px}.seat-name{font-size:8px}.seat-role{font-size:6px}.battlefield[data-pairs=\"3\"],.battlefield[data-pairs=\"4\"],.battlefield[data-pairs=\"5\"],.battlefield[data-pairs=\"6\"]{column-gap:8px}.save-status{font-size:6px}.match-badge{font-size:6px}.player-option span{font-size:6px}.modal-card{padding-left:19px;padding-right:19px}}\n@media(max-height:760px) and (min-width:761px){.topbar{height:81px}.match-meta{padding-top:15px;padding-bottom:11px}.opponents{padding-top:18px;min-height:117px}.game-table{min-height:324px}.table-middle{min-height:208px;padding-bottom:21px}.hand-panel{padding-top:15px}.hand-card{width:77px;height:110px;flex-basis:77px}.hand-scroll{min-height:158px}.action-bar{padding:13px 0;min-height:68px}.game-footer{padding-top:11px}}\n@media(max-height:740px){.modal-overlay{align-items:flex-start}.welcome-card{margin:auto 0}.welcome-art{height:111px;transform:scale(.81);transform-origin:50% 0;margin-bottom:2px}.welcome-card h1{font-size:56px;margin-top:10px;margin-bottom:13px}.welcome-copy{font-size:11px;margin-bottom:18px}.player-picker{margin-bottom:17px}.welcome-foot{margin-top:17px}}\n.quick-tempo .battlefield.settling .card-pair{animation-duration:.26s;animation-delay:.02s}.quick-tempo .deal-in{animation-duration:.18s;animation-delay:0ms!important}.modal-open .app-shell *{animation-play-state:paused!important}\n@media(max-width:760px){.turn-copy p{font-size:12px;line-height:1.55}.action-buttons .button{font-size:12px;min-height:46px}.human-heading strong{font-size:12px}.hand-hint{font-size:10px}.seat-name{font-size:11px}.play-button{min-width:150px}.action-buttons #btn-pass{max-width:none}.game-footer,.history-button{font-size:9px}}\n@media(max-width:540px){.turn-copy p{font-size:12px}.action-buttons .button{font-size:12px;padding-left:12px;padding-right:12px}.turn-label{font-size:8px}.hand-hint{font-size:9px}.human-heading #human-role{font-size:8px}.hand-count{font-size:8px}.seat-name{font-size:10px}.seat-role{font-size:8px}.play-button{min-width:148px}.player-option span{font-size:8px}.welcome-copy{font-size:12px}.welcome-start{font-size:13px}.player-picker legend{font-size:12px}.rules-list p{font-size:12px}.rules-list h3{font-size:13px}.rules-intro{font-size:12px}.rules-controls{font-size:10px}.welcome-foot{font-size:9px}.text-button{font-size:11px}.rules-done{font-size:12px}.hand-caption{min-height:31px}}\n@media(max-width:359px){.action-buttons .button{font-size:11px;padding-left:8px;padding-right:8px}.play-button{min-width:131px}.player-option span{font-size:7px}.seat-name{font-size:9px}.seat-role{font-size:7px}}\n@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation-duration:.001ms!important;animation-delay:0ms!important;transition-duration:.001ms!important;scroll-behavior:auto!important}.battlefield.settling .card-pair{animation:none!important;opacity:.7}.thinking i{opacity:.6}}\n</style>\n  <div class=\"ambient ambient-one\" aria-hidden=\"true\"></div>\n  <div class=\"ambient ambient-two\" aria-hidden=\"true\"></div>\n  <div id=\"app\" class=\"app-shell\">\n    <header class=\"topbar\">\n      <div class=\"brand\" aria-label=\"Дурак. Карточный клуб\">\n        <span class=\"brand-mark\" aria-hidden=\"true\">♠</span>\n        <div><span class=\"brand-name\">Дурак</span><span class=\"brand-caption\">КАРТОЧНЫЙ КЛУБ</span></div>\n      </div>\n      <nav class=\"toolbar\" aria-label=\"Настройки игры\">\n        <button id=\"btn-sound\" data-testid=\"sound\" class=\"tool-button\" type=\"button\" aria-pressed=\"false\" aria-label=\"Включить звуки\" title=\"Включить звуки\">\n          <svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M11 5 6 9H3v6h3l5 4V5Z\"/><path class=\"sound-waves\" d=\"M15 8c2 2 2 6 0 8m3-11c4 4 4 10 0 14\"/><path class=\"sound-cross\" d=\"m16 9 5 6m0-6-5 6\"/></svg>\n          <span id=\"sound-label\">Звук выкл.</span>\n        </button>\n        <button id=\"btn-speed\" class=\"tool-button\" type=\"button\" aria-pressed=\"false\" aria-label=\"Быстрый темп соперников\" title=\"Переключить скорость соперников\">\n          <svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"m13 3-8 11h6l-1 7 9-12h-6l1-6Z\"/></svg><span id=\"speed-label\">Обычный темп</span>\n        </button>\n        <button id=\"btn-rules\" class=\"tool-button\" type=\"button\" aria-label=\"Правила игры\"><span class=\"help-icon\" aria-hidden=\"true\">?</span><span>Правила</span></button>\n        <span class=\"toolbar-separator\" aria-hidden=\"true\"></span>\n        <button id=\"btn-new\" class=\"tool-button new-button\" type=\"button\" aria-label=\"Новая игра\"><svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M4 10a8 8 0 1 1 1 8M4 4v6h6\"/></svg><span>Новая игра</span></button>\n      </nav>\n    </header>\n\n    <main class=\"game-layout\">\n      <div class=\"match-meta\">\n        <div class=\"match-badge\"><span class=\"status-dot\" aria-hidden=\"true\"></span><span id=\"match-label\">ВАШ СТОЛ ГОТОВ</span></div>\n        <div id=\"save-status\" class=\"save-status\" role=\"status\" aria-live=\"polite\">Без регистрации · работает без сети</div>\n      </div>\n\n      <section id=\"game-table\" data-testid=\"game-surface\" class=\"game-table\" aria-label=\"Игровой стол\">\n        <div class=\"table-watermark\" aria-hidden=\"true\"><span>♠</span><small>КАРТОЧНЫЙ КЛУБ</small></div>\n        <div id=\"opponents\" class=\"opponents\" aria-label=\"Соперники\"></div>\n        <div class=\"table-middle\">\n          <aside class=\"deck-zone\" aria-label=\"Колода и козырь\">\n            <div id=\"deck-stack\" class=\"deck-stack\"></div>\n            <div class=\"deck-caption\"><strong id=\"deck-count\">36</strong><span>в колоде</span></div>\n            <div id=\"trump-label\" class=\"trump-label\">Козырь после раздачи</div>\n          </aside>\n          <div class=\"battlefield-wrap\">\n            <div id=\"battlefield\" class=\"battlefield\" aria-label=\"Карты на столе\"></div>\n            <div id=\"round-toast\" class=\"round-toast\" role=\"status\" aria-live=\"polite\"></div>\n          </div>\n          <aside class=\"round-zone\" aria-label=\"Состояние партии\">\n            <div class=\"round-number\"><span>РАУНД</span><strong id=\"round-number\">01</strong></div>\n            <div class=\"discard-counter\"><span class=\"discard-icon\" aria-hidden=\"true\">▱</span><strong id=\"discard-count\">0</strong><span>в отбое</span></div>\n            <div id=\"round-limit\" class=\"round-limit\">Колода 36 карт</div>\n          </aside>\n        </div>\n      </section>\n\n      <section id=\"hand-panel\" class=\"hand-panel\" aria-label=\"Ваши карты и действия\">\n        <div class=\"hand-caption\">\n          <div class=\"human-heading\"><span class=\"human-avatar\" aria-hidden=\"true\">В</span><div><strong>Вы</strong><span id=\"human-role\">Участник клуба</span></div><span id=\"hand-count\" class=\"hand-count\">0 карт</span></div>\n          <div id=\"hand-hint\" class=\"hand-hint\">Устраивайтесь поудобнее. Сейчас раздадим.</div>\n        </div>\n        <div id=\"hand-scroll\" class=\"hand-scroll\"><div id=\"hand\" class=\"hand\" aria-label=\"Ваша рука\"></div></div>\n        <div class=\"action-bar\">\n          <div class=\"turn-copy\"><span id=\"turn-label\" class=\"turn-label\">ГОТОВЫ К ПАРТИИ?</span><p id=\"turn-message\" aria-live=\"polite\" aria-atomic=\"true\">Выберите число игроков и раздайте карты.</p></div>\n          <div class=\"action-buttons\">\n            <button id=\"btn-take\" class=\"button button-subtle\" type=\"button\" hidden>Беру</button>\n            <button id=\"btn-pass\" class=\"button button-outline\" type=\"button\" hidden>Больше не подкидываю</button>\n            <button id=\"btn-play\" class=\"button button-gold play-button\" type=\"button\" disabled>Выберите карту <span aria-hidden=\"true\">↗</span></button>\n          </div>\n        </div>\n      </section>\n      <div id=\"notice\" class=\"notice\" role=\"alert\" hidden></div>\n    </main>\n\n    <footer class=\"game-footer\"><div id=\"last-move\" class=\"last-move\">36 карт. Никакой спешки.</div><button id=\"btn-history\" class=\"history-button\" type=\"button\" aria-expanded=\"false\">История ходов <span aria-hidden=\"true\">↗</span></button></footer>\n    <section id=\"history-panel\" class=\"history-panel\" aria-label=\"История текущей партии\" hidden><div class=\"history-heading\"><h2>За этим столом</h2><button id=\"btn-close-history\" class=\"text-button\" type=\"button\">Свернуть</button></div><ol id=\"history-list\"></ol></section>\n  </div>\n\n  <div id=\"modal-start\" class=\"modal-overlay\" role=\"dialog\" aria-modal=\"true\" aria-labelledby=\"welcome-title\" tabindex=\"-1\" hidden>\n    <section class=\"modal-card welcome-card\">\n      <button id=\"btn-close-start\" class=\"modal-close\" type=\"button\" aria-label=\"Вернуться к партии\" hidden>×</button>\n      <div class=\"welcome-art\" aria-hidden=\"true\"><div class=\"welcome-card-back\"></div><div id=\"welcome-queen\" class=\"welcome-playing-card queen\"></div><div id=\"welcome-ace\" class=\"welcome-playing-card ace\"></div><span class=\"art-star star-one\">✧</span><span class=\"art-star star-two\">✧</span></div>\n      <span class=\"eyebrow\">НЕБОЛЬШОЙ ПЕРЕРЫВ НА ПАРТИЮ</span>\n      <h1 id=\"welcome-title\">Дурак.</h1>\n      <p id=\"welcome-copy\" class=\"welcome-copy\">Знакомая игра. Достойная компания.<br>Один стол — вы и компьютерные соперники.</p>\n      <fieldset class=\"player-picker\"><legend>Сколько нас за столом?</legend><div class=\"player-options\">\n        <button class=\"player-option selected\" data-player-count=\"2\" type=\"button\" aria-pressed=\"true\"><strong>2</strong><span>Вы + 1 соперник</span></button>\n        <button class=\"player-option\" data-player-count=\"3\" type=\"button\" aria-pressed=\"false\"><strong>3</strong><span>Вы + 2 соперника</span></button>\n        <button class=\"player-option\" data-player-count=\"4\" type=\"button\" aria-pressed=\"false\"><strong>4</strong><span>Вы + 3 соперника</span></button>\n      </div></fieldset>\n      <button id=\"btn-start\" data-testid=\"start\" class=\"button button-gold welcome-start\" type=\"button\">Раздать карты <span aria-hidden=\"true\">→</span></button>\n      <button id=\"btn-resume\" class=\"button button-outline welcome-resume\" type=\"button\" hidden>Продолжить партию</button>\n      <div class=\"welcome-foot\"><span>Подкидной · 36 карт</span><button id=\"btn-welcome-rules\" class=\"text-button\" type=\"button\">Как играть <span aria-hidden=\"true\">↗</span></button></div>\n    </section>\n  </div>\n\n  <div id=\"modal-rules\" class=\"modal-overlay\" role=\"dialog\" aria-modal=\"true\" aria-labelledby=\"rules-title\" tabindex=\"-1\" hidden>\n    <section class=\"modal-card rules-card\">\n      <button id=\"btn-close-rules\" class=\"modal-close\" type=\"button\" aria-label=\"Закрыть правила\">×</button>\n      <span class=\"eyebrow\">ПОДКИДНОЙ ДУРАК</span><h2 id=\"rules-title\">Правила нашего стола</h2>\n      <p class=\"rules-intro\">Избавляйтесь от карт. Когда колода закончится, последний игрок с картами становится дураком.</p>\n      <div class=\"rules-list\">\n        <section><span class=\"rule-number\">01</span><div><h3>Раздача и первый ход</h3><p>У каждого по 6 карт. Открытая карта под колодой показывает козырь и забирается последней. Первым ходит обладатель младшего козыря на руках. Если козырей ни у кого нет, первого выбирает жеребьёвка.</p></div></section>\n        <section><span class=\"rule-number\">02</span><div><h3>Ходим и отбиваемся</h3><p>Первая карта — любая. Защищается следующий игрок по часовой стрелке. Карту можно побить старшей той же масти или козырем. Козырь бьётся только старшим козырем. Старшинство: 6, 7, 8, 9, 10, В, Д, К, Т.</p></div></section>\n        <section><span class=\"rule-number\">03</span><div><h3>Подкидываем по очереди</h3><p>Подкидывать можно карты тех достоинств, которые уже лежат на столе, включая карты защиты. После каждого ответа очередь подкинуть начинается с первого атакующего и идёт по кругу, пропуская защитника. Пас действует до следующего подкидывания.</p><p>За один заход — не более 6 атакующих карт и не больше, чем было карт у защитника в начале захода. Это правило действует и в первом раунде.</p></div></section>\n        <section><span class=\"rule-number\">04</span><div><h3>Отбой или «Беру»</h3><p>Когда всё побито и все спасовали — отбой. Следующим ходит защитник. Нажав «Беру», отменить решение уже нельзя: соперники ещё могут подкинуть до лимита. Затем защитник забирает весь стол и пропускает следующий заход.</p></div></section>\n        <section><span class=\"rule-number\">05</span><div><h3>Добор и конец партии</h3><p>После раунда добирают до 6: сначала первый атакующий, затем остальные по кругу, защитник — последним. Выйти из игры без карт можно только после завершения раунда при пустой колоде. Если карт не осталось ни у кого — ничья. Если вы вышли раньше, можно посмотреть финал соперников.</p></div></section>\n      </div>\n      <div class=\"rules-controls\"><span class=\"keyboard-key\">Enter</span> сыграть выбранную карту <span class=\"keyboard-key\">Esc</span> снять выбор / закрыть окно</div>\n      <button id=\"btn-rules-done\" class=\"button button-gold rules-done\" type=\"button\">Всё понятно <span aria-hidden=\"true\">✓</span></button>\n    </section>\n  </div>\n\n  <div id=\"modal-result\" class=\"modal-overlay\" role=\"dialog\" aria-modal=\"true\" aria-labelledby=\"result-title\" tabindex=\"-1\" hidden>\n    <section class=\"modal-card result-card\"><button id=\"btn-close-result\" class=\"modal-close\" type=\"button\" aria-label=\"Посмотреть стол\">×</button><div id=\"result-emblem\" class=\"result-emblem\" aria-hidden=\"true\">♠</div><span id=\"result-eyebrow\" class=\"eyebrow\">ПАРТИЯ ЗАВЕРШЕНА</span><h2 id=\"result-title\">Хорошая партия.</h2><p id=\"result-copy\" class=\"result-copy\"></p><div id=\"result-summary\" class=\"result-summary\"></div><button id=\"btn-again\" class=\"button button-gold welcome-start\" type=\"button\">Ещё одну? <span aria-hidden=\"true\">→</span></button><button id=\"btn-result-table\" class=\"text-button\" type=\"button\">Вернуться к столу</button></section>\n  </div>\n\n  <noscript><div class=\"noscript-notice\">Чтобы сыграть, включите JavaScript в браузере. Игра целиком работает на вашем устройстве.</div></noscript>";
  const STORAGE_KEY = 'game-forge.corpus.durak.match.v1';
  const PREFS_KEY = 'game-forge.corpus.durak.preferences.v1';
  const $ = id => doc.getElementById(id);
  const copy = value => JSON.parse(JSON.stringify(value));
  const esc = value => String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
  const SUIT_NAMES = { S: 'пики', H: 'червы', D: 'бубны', C: 'трефы' };
  const RANK_NAMES = { 6: 'Шестёрка', 7: 'Семёрка', 8: 'Восьмёрка', 9: 'Девятка', 10: 'Десятка', 11: 'Валет', 12: 'Дама', 13: 'Король', 14: 'Туз' };
  const engine = new GameEngine();
  let selected = null;
  let target = null;
  let session = 0;
  let advanceTimer = null;
  let advanceTicket = 0;
  let manualPaused = false;
  let pageHidden = false;
  let modal = null;
  let returnModal = null;
  let previousFocus = null;
  let initialized = false;
  let destroyed = false;
  let renderedView = null;
  let renderedSession = -1;
  let shownResult = null;
  let saveText = 'Без регистрации · работает без сети';
  let saveWarning = false;
  let observedSave = null;
  let saveConflict = false;
  let history = [];
  let preferences = { playerCount: 2, sound: false, quick: false };
  let audio = null;
  let audioContext = null;
  let audioResumePending = null;
  const listeners = [];

  function listen(element, event, callback, options) {
    if (!element) return;
    element.addEventListener(event, callback, options);
    listeners.push(() => element.removeEventListener(event, callback, options));
  }

  function fullCardLabel(id) {
    const c = E.card(id);
    return RANK_NAMES[c.rank] + ', ' + SUIT_NAMES[c.suit];
  }

  function cardArt(id) {
    const c = E.card(id);
    const ink = c.red ? '#b3423e' : '#263d3d';
    const accent = '#b08b43';
    const smallRank = c.rank === 10 ? 18 : 21;
    const corner = '<text x="12" y="23" text-anchor="middle" fill="' + ink + '" font-family="Georgia,serif" font-size="' + smallRank + '" font-weight="700">' + c.rankLabel + '</text><text x="12" y="40" text-anchor="middle" fill="' + ink + '" font-family="Georgia,serif" font-size="17">' + c.symbol + '</text>';
    let middle = '';
    if (c.rank === 14) {
      middle = '<path d="M50 35 72 72 50 109 28 72Z" fill="none" stroke="' + accent + '" stroke-opacity=".3" stroke-width=".7"/><text x="50" y="89" text-anchor="middle" fill="' + ink + '" font-family="Georgia,serif" font-size="55">' + c.symbol + '</text><path d="M39 118h22" stroke="' + accent + '" stroke-width=".9"/>';
    } else if (c.rank > 10) {
      const crown = c.rank === 13
        ? '<path d="m33 41-3-12 12 6 8-13 8 13 12-6-3 12Z" fill="' + accent + '"/><path d="M35 37h30M38 29l2 4m20-4-2 4" stroke="#faeed0" stroke-width="1"/>'
        : c.rank === 12
          ? '<path d="m33 40 3-13 8 7 6-11 6 11 8-7 3 13Z" fill="' + accent + '"/><circle cx="50" cy="29" r="2" fill="' + ink + '"/><path d="M36 40h29" stroke="#f7e9c5" stroke-width="1.3"/>'
          : '<path d="M31 40q8-15 21-14l14 9 4 7Z" fill="' + ink + '"/><path d="M38 34h23M57 26l8-5-3 8" stroke="' + accent + '" fill="none" stroke-width="2"/>';
      const portrait = crown + '<path d="M36 42q0 20 14 22 14-2 14-22" fill="#ebcf9d" stroke="' + accent + '" stroke-width="1"/><path d="M39 46h7m8 0h7M50 48l-2 7h4m-8 3q6 4 12 0" fill="none" stroke="' + ink + '" stroke-width="1"/><path d="m35 45 2 16 9 5-15 6m34-27-2 16-9 5 15 6" fill="none" stroke="' + ink + '" stroke-width="2.2"/><path d="m26 72 14-11 10 9 10-9 14 11" fill="' + ink + '" stroke="' + accent + '" stroke-width="1"/><path d="m38 64 12 8 12-8M31 70l6 4m32-4-6 4" fill="none" stroke="' + accent + '" stroke-width="2"/>';
      middle = '<rect x="24" y="22" width="52" height="100" rx="2" fill="#f2e5c8" stroke="' + accent + '" stroke-width=".75"/><g>' + portrait + '</g><g transform="rotate(180 50 72)">' + portrait + '</g><path d="M25 72h50" stroke="' + accent + '" stroke-width="2"/><path d="m43 72 7-5 7 5-7 5Z" fill="' + accent + '"/><text x="18" y="77" text-anchor="middle" fill="' + ink + '" font-family="Georgia,serif" font-size="12">' + c.symbol + '</text><text x="82" y="77" text-anchor="middle" fill="' + ink + '" font-family="Georgia,serif" font-size="12">' + c.symbol + '</text>';
    } else {
      const pipLayouts = {
        6: [[31,36],[69,36],[31,72],[69,72],[31,108],[69,108]],
        7: [[31,36],[69,36],[31,72],[69,72],[31,108],[69,108],[50,53]],
        8: [[31,36],[69,36],[31,72],[69,72],[31,108],[69,108],[50,53],[50,91]],
        9: [[31,34],[69,34],[31,59],[69,59],[31,85],[69,85],[31,110],[69,110],[50,72]],
        10: [[31,34],[69,34],[31,59],[69,59],[31,85],[69,85],[31,110],[69,110],[50,47],[50,97]]
      };
      middle = pipLayouts[c.rank].map(([x, y]) => '<g transform="translate(' + x + ' ' + y + ') ' + (y > 72 ? 'rotate(180)' : '') + '"><text y="8" text-anchor="middle" fill="' + ink + '" font-family="Georgia,serif" font-size="24">' + c.symbol + '</text></g>').join('');
    }
    return '<svg class="card-art" viewBox="0 0 100 144" aria-hidden="true" focusable="false"><rect x=".5" y=".5" width="99" height="143" rx="8" fill="#fbf7e9" stroke="#e3decb"/>' + corner + '<g transform="rotate(180 50 72)">' + corner + '</g>' + middle + '</svg>';
  }

  function cardsWord(count) {
    const teen = count % 100;
    return count + ' ' + (teen >= 11 && teen <= 14 ? 'карт' : count % 10 === 1 ? 'карта' : count % 10 >= 2 && count % 10 <= 4 ? 'карты' : 'карт');
  }

  function playerName(id, view) {
    const player = view.players.find(item => item.id === id);
    return player ? player.name : 'Игрок';
  }

  function roleFor(player, view) {
    if (player.out) return 'Вышли без карт';
    if (view.phase === 'finished') return view.result && view.result.durak === player.id ? 'Остался с картами' : 'Партия завершена';
    if (view.taking && view.defender === player.id) return 'Берёт карты';
    if (view.phase === 'roundEnd') return view.defender === player.id ? 'Завершает раунд' : 'Ожидает раздачи';
    if (view.actor === player.id) return view.phase === 'defend' ? 'Отбивается' : view.table.length ? 'Может подкинуть' : 'Ходит первым';
    if (view.defender === player.id) return 'Защищается';
    return 'Ожидает хода';
  }

  function renderOpponents(view) {
    if (!view) {
      $('opponents').innerHTML = '<div class="seat"><div class="seat-heading"><div class="seat-avatar">♣</div><div class="seat-info"><span class="seat-name">Место напротив</span><span class="seat-role">Скоро займут</span></div></div><div class="seat-hand"><span class="mini-back" style="--x:0px;--r:0deg"></span></div></div>';
      return;
    }
    $('opponents').innerHTML = view.players.filter(player => player.id !== 0).map(player => {
      const backs = Math.min(7, player.count);
      const stack = Array.from({ length: backs }, (_, index) => '<span class="mini-back" style="--x:' + ((index - (backs - 1) / 2) * 10) + 'px;--r:' + ((index - (backs - 1) / 2) * 4) + 'deg"></span>').join('');
      const thinking = view.actor === player.id && view.phase !== 'roundEnd' && view.phase !== 'finished' ? '<span class="thinking" aria-hidden="true"><i></i><i></i><i></i></span>' : '';
      return '<div class="seat' + (view.actor === player.id ? ' active' : '') + (player.out ? ' out' : '') + '" data-seat="' + player.id + '" aria-label="' + esc(player.name + ', ' + cardsWord(player.count) + '. ' + roleFor(player, view)) + '"><div class="seat-heading"><div class="seat-avatar" aria-hidden="true">' + (player.out ? '✓' : esc(player.name.slice(0, 1))) + '</div><div class="seat-info"><span class="seat-name">' + esc(player.name) + '</span><span class="seat-role">' + esc(roleFor(player, view)) + thinking + '</span></div></div><div class="seat-hand" aria-hidden="true">' + (player.out ? '<span class="seat-out-mark">ВЫШЕЛ ✓</span>' : stack + '<span class="seat-card-count">' + player.count + '</span>') + '</div></div>';
    }).join('');
  }

  function renderDeck(view) {
    const stack = $('deck-stack');
    stack.className = 'deck-stack';
    if (!view) {
      stack.innerHTML = '<div class="deck-back" aria-hidden="true"></div>';
      $('deck-count').textContent = '36';
      $('trump-label').textContent = 'Козырь после раздачи';
      stack.setAttribute('aria-label', 'Колода 36 карт');
      return;
    }
    $('deck-count').textContent = String(view.deckCount);
    const trump = E.card(view.trumpCard);
    if (view.deckCount === 0) {
      stack.classList.add('empty');
      stack.innerHTML = '<span aria-hidden="true">' + trump.symbol + '</span>';
      stack.setAttribute('aria-label', 'Колода закончилась');
    } else {
      if (view.deckCount === 1) stack.classList.add('last');
      stack.innerHTML = '<div class="trump-card" role="img" aria-label="Открытый козырь: ' + esc(fullCardLabel(view.trumpCard)) + '">' + cardArt(view.trumpCard) + '</div>' + (view.deckCount > 1 ? '<div class="deck-back" aria-hidden="true"></div>' : '');
      stack.setAttribute('aria-label', cardsWord(view.deckCount) + ' в колоде');
    }
    $('trump-label').innerHTML = 'Козырь <span class="trump-symbol' + (trump.red ? ' red' : '') + '" aria-label="' + SUIT_NAMES[trump.suit] + '">' + trump.symbol + '</span>';
  }

  function renderTable(view, changed) {
    const field = $('battlefield');
    field.className = 'battlefield';
    field.setAttribute('data-pairs', String(view ? view.table.length : 0));
    $('round-toast').classList.remove('visible');
    $('round-toast').textContent = '';
    if (!view || view.table.length === 0) {
      let title = 'Партия начинается с хода';
      let text = 'Раздайте карты, а мы подскажем, что делать дальше.';
      if (view) {
        title = view.phase === 'finished' ? 'Партия завершена.' : view.actor === 0 ? 'Ваш первый ход' : 'Ходит ' + playerName(view.actor, view);
        text = view.phase === 'finished' ? 'Можно устроить ещё одну партию.' : view.actor === 0 ? 'Выберите любую карту из руки и положите её на стол.' : 'Соперник выбирает карту. Немного терпения.';
      }
      field.innerHTML = '<div class="empty-table"><span class="empty-suit" aria-hidden="true">♧</span><strong>' + esc(title) + '</strong><p>' + esc(text) + '</p></div>';
      return;
    }
    const previousCards = new Set(renderedView && renderedSession === session ? renderedView.table.flatMap(pair => [pair.attack, pair.defense]).filter(Boolean) : []);
    const targetActions = view.legalActions.filter(action => action.type === 'defend');
    const selectedActions = targetActions.filter(action => action.card === selected);
    if (selectedActions.length && !selectedActions.some(action => action.target === target)) target = selectedActions[0].target;
    field.innerHTML = view.table.map((pair, index) => {
      const canTarget = targetActions.some(action => action.target === index);
      const targeted = pair.defense === null && (target === index && selectedActions.length || targetActions.some(action => action.target === index));
      const attackClass = 'table-card' + (canTarget ? ' target-card' : '') + (changed && !previousCards.has(pair.attack) ? ' card-arrive' : '');
      const tag = canTarget ? 'button' : 'div';
      const attack = '<' + tag + ' class="' + attackClass + '"' + (canTarget ? ' type="button" data-target="' + index + '"' : ' role="img"') + ' aria-label="' + esc((canTarget ? 'Отбить: ' : 'Атака: ') + fullCardLabel(pair.attack)) + '">' + cardArt(pair.attack) + '</' + tag + '>';
      const defense = pair.defense ? '<div class="table-card defense-card' + (changed && !previousCards.has(pair.defense) ? ' card-arrive' : '') + '" role="img" aria-label="' + esc('Защита: ' + fullCardLabel(pair.defense)) + '">' + cardArt(pair.defense) + '</div>' : '';
      return '<div class="card-pair' + (pair.defense === null ? ' uncovered' : '') + (targeted ? ' targeted' : '') + '">' + attack + defense + (canTarget ? '<span class="target-label">' + (selected ? 'Бьём эту карту' : 'Нужно отбить') + '</span>' : '') + '</div>';
    }).join('');
    if (view.phase === 'roundEnd') {
      field.classList.add('settling');
      if (view.roundResult.kind === 'taken') field.classList.add('taken');
      $('round-toast').textContent = view.roundResult.kind === 'taken' ? playerName(view.defender, view) + (view.defender === 0 ? ' забираете стол' : ' забирает стол') : 'Отбой. Все карты побиты';
      $('round-toast').classList.add('visible');
    } else if (view.taking) {
      $('round-toast').textContent = (view.defender === 0 ? 'Вы берёте' : playerName(view.defender, view) + ' берёт') + ' · ещё можно подкинуть';
      $('round-toast').classList.add('visible');
    }
  }

  function renderHand(view, changed) {
    const scroll = $('hand-scroll');
    const previousScroll = scroll.scrollLeft || 0;
    if (!view || view.hand.length === 0) {
      const out = view && view.players[0].out;
      $('hand').innerHTML = '<div class="no-hand">' + (out ? '<span class="spectator-mark" aria-hidden="true">✧</span><strong>Вы вышли без карт.</strong><p>' + (view.phase === 'finished' ? 'Отличный повод сыграть ещё раз.' : 'Теперь можно посмотреть финал соперников.') + '</p>' : '<span class="spectator-mark" aria-hidden="true">♠</span><p>' + (view ? 'Карт на руках нет. Дождитесь завершения раунда.' : 'Ваша рука появится здесь') + '</p>') + '</div>';
      return;
    }
    const previousHand = new Set(renderedView && renderedSession === session ? renderedView.hand : []);
    const legalCards = new Set(view.legalActions.filter(action => action.card).map(action => action.card));
    const hand = view.hand.slice().sort((a, b) => {
      const ca = E.card(a), cb = E.card(b);
      const ta = ca.suit === view.trumpSuit ? 1 : 0, tb = cb.suit === view.trumpSuit ? 1 : 0;
      return ta - tb || E.SUITS.indexOf(ca.suit) - E.SUITS.indexOf(cb.suit) || ca.rank - cb.rank;
    });
    $('hand').innerHTML = hand.map((id, index) => {
      const playable = legalCards.has(id);
      const isSelected = selected === id;
      const trump = E.card(id).suit === view.trumpSuit;
      const arrival = changed && !previousHand.has(id);
      const classes = 'hand-card' + (playable ? ' selectable' : '') + (isSelected ? ' selected' : '') + (arrival ? ' deal-in' : '');
      const label = fullCardLabel(id) + (trump ? ', козырь' : '') + (isSelected ? ', выбрана' : playable ? ', можно сыграть' : ', сейчас сыграть нельзя');
      return '<button type="button" class="' + classes + '" data-card="' + id + '" aria-label="' + esc(label) + '" aria-pressed="' + isSelected + '"' + (!playable ? ' disabled' : '') + (arrival ? ' style="animation-delay:' + (Math.min(index, 7) * 35) + 'ms"' : '') + '>' + cardArt(id) + (trump ? '<span class="trump-badge" aria-hidden="true">КОЗЫРЬ</span>' : '') + (isSelected ? '<span class="selected-check" aria-hidden="true">✓</span>' : '') + '</button>';
    }).join('');
    scroll.scrollLeft = previousScroll;
  }

  function renderStatus(view) {
    const play = $('btn-play'), pass = $('btn-pass'), take = $('btn-take');
    play.hidden = false;
    play.disabled = true;
    pass.hidden = true;
    take.hidden = true;
    $('hand-panel').classList.toggle('human-turn', Boolean(view && view.actor === 0));
    if (!view) {
      $('match-label').textContent = 'ВАШ СТОЛ ГОТОВ';
      $('round-number').textContent = '01';
      $('discard-count').textContent = '0';
      $('round-limit').textContent = 'Колода 36 карт';
      $('hand-count').textContent = '0 карт';
      $('human-role').textContent = 'Участник клуба';
      $('turn-label').textContent = 'ГОТОВЫ К ПАРТИИ?';
      $('turn-message').textContent = 'Выберите число игроков и раздайте карты.';
      $('hand-hint').textContent = 'Устраивайтесь поудобнее. Сейчас раздадим.';
      play.innerHTML = 'Выберите карту <span aria-hidden="true">↗</span>';
      return;
    }
    $('match-label').textContent = 'ПАРТИЯ · ' + view.players.length + ' ИГРОКА';
    $('round-number').textContent = String(view.round).padStart(2, '0');
    $('discard-count').textContent = String(view.discard.length);
    $('round-limit').textContent = view.phase === 'finished' ? 'Партия завершена' : 'На столе ' + view.table.length + ' из ' + view.attackLimit;
    $('hand-count').textContent = cardsWord(view.hand.length);
    $('human-role').textContent = roleFor(view.players[0], view);
    const legal = view.legalActions;
    const cards = legal.filter(action => action.card);
    const chosen = cards.find(action => action.card === selected && (action.type !== 'defend' || action.target === target));
    pass.hidden = !legal.some(action => action.type === 'pass');
    take.hidden = !legal.some(action => action.type === 'take');
    pass.textContent = view.taking ? 'Не подкидываю' : 'Больше не подкидываю';
    play.disabled = !chosen;
    play.innerHTML = (chosen ? (chosen.type === 'defend' ? 'Отбить ' : 'Сыграть ') + esc(E.card(chosen.card).label) : 'Выберите карту') + ' <span aria-hidden="true">↗</span>';
    if (!cards.length) play.hidden = true;
    let label, message, hint;
    if (view.phase === 'finished') {
      label = 'ПАРТИЯ ЗАВЕРШЕНА';
      message = view.result.draw ? 'Ничья: ни у кого не осталось карт.' : view.result.durak === 0 ? 'В этот раз карты остались у вас. Сыграем ещё?' : playerName(view.result.durak, view) + ' — последний игрок с картами. Вы вышли из игры!';
      hint = 'Новая раздача — новая история.';
    } else if (view.phase === 'roundEnd') {
      label = 'ЗАВЕРШАЕМ РАУНД';
      message = view.roundResult.kind === 'beaten' ? 'Отбой. Игроки добирают карты до шести.' : (view.defender === 0 ? 'Вы забираете' : playerName(view.defender, view) + ' забирает') + ' карты со стола. Затем — добор.';
      hint = 'Следующий заход начнётся автоматически.';
    } else if (view.players[0].out) {
      label = 'ВЫ УЖЕ ВЫШЛИ';
      message = 'Игра продолжается. ' + playerName(view.actor, view) + (view.phase === 'defend' ? ' отбивается.' : ' выбирает ход.');
      hint = 'Смотрим финал компьютерных соперников.';
    } else if (view.actor === 0) {
      if (view.phase === 'defend') {
        label = 'ВАШ ХОД · ЗАЩИТА';
        const attack = view.table.find(pair => pair.defense === null);
        message = attack ? 'Нужно побить ' + E.card(attack.attack).label + '. ' + (cards.length ? 'Выберите подходящую карту или нажмите «Беру».' : 'Подходящих карт нет. Нажмите «Беру».') : 'Выберите карту для защиты.';
        hint = cards.length ? 'Подсвечены карты, которыми можно отбиться.' : 'Нет подходящей карты — можно забрать стол.';
      } else {
        label = view.table.length ? 'ВАШ ХОД · ПОДКИДЫВАЕМ' : 'ВАШ ХОД · АТАКА';
        message = !view.table.length ? 'Начните с любой карты. Следующий игрок будет отбиваться.' : view.taking ? 'Защитник берёт. Можно подкинуть до лимита или спасовать.' : cards.length ? 'Можно подкинуть карту того же достоинства, что есть на столе, или спасовать.' : 'Подкинуть нечего. Нажмите «Больше не подкидываю».';
        hint = selected ? 'Карта выбрана. Подтвердите ход кнопкой.' : cards.length ? 'Сначала выберите карту, затем подтвердите ход.' : 'В этом заходе вы можете пропустить подкидывание.';
      }
    } else {
      label = 'ХОД СОПЕРНИКА';
      message = playerName(view.actor, view) + (view.phase === 'defend' ? ' решает, чем отбиться.' : view.taking ? ' решает, что подкинуть перед взятием.' : view.table.length ? ' может подкинуть ещё одну карту.' : ' выбирает первую карту.');
      hint = view.taking && view.defender === 0 ? 'Решение «Беру» принято. Ждём остальных.' : 'Ваши карты никуда не торопятся.';
    }
    if (view.hand.length >= 9) hint += ' Руку можно прокручивать вбок.';
    $('turn-label').textContent = label;
    $('turn-message').textContent = message;
    $('hand-hint').textContent = hint;
  }

  function renderPreferences() {
    $('btn-sound').setAttribute('aria-pressed', String(preferences.sound));
    $('btn-sound').setAttribute('title', preferences.sound ? 'Выключить звуки' : 'Включить звуки');
    $('btn-sound').setAttribute('aria-label', preferences.sound ? 'Выключить звуки' : 'Включить звуки');
    $('sound-label').textContent = preferences.sound ? 'Звук вкл.' : 'Звук выкл.';
    $('btn-speed').setAttribute('aria-pressed', String(preferences.quick));
    $('speed-label').textContent = preferences.quick ? 'Быстрый темп' : 'Обычный темп';
    doc.documentElement.classList.toggle('quick-tempo', preferences.quick);
    doc.querySelectorAll('[data-player-count]').forEach(button => {
      const chosen = Number(button.getAttribute('data-player-count')) === preferences.playerCount;
      button.classList.toggle('selected', chosen);
      button.setAttribute('aria-pressed', String(chosen));
    });
    $('save-status').textContent = saveText;
    $('save-status').classList.toggle('warning', saveWarning);
  }

  function renderHistory() {
    $('last-move').textContent = history.length ? history[history.length - 1] : '36 карт. Никакой спешки.';
    $('history-list').innerHTML = history.length ? history.slice().reverse().map(entry => '<li>' + esc(entry) + '</li>').join('') : '<li>Пока ни одного хода. Всё впереди.</li>';
  }

  function renderOriginal() {
    if (destroyed) return;
    const focused = doc.activeElement;
    const focusedCard = focused && $('hand').contains(focused) ? focused.getAttribute('data-card') : null;
    const focusedTarget = focused && $('battlefield').contains(focused) ? focused.getAttribute('data-target') : null;
    const view = engine.state ? E.view(engine.state, 0) : null;
    const changed = Boolean(view && (renderedSession !== session || !renderedView || renderedView.revision !== view.revision));
    if (selected && (!view || !view.legalActions.some(action => action.card === selected))) { selected = null; target = null; }
    renderOpponents(view);
    renderDeck(view);
    renderTable(view, changed);
    renderHand(view, changed);
    renderStatus(view);
    renderPreferences();
    renderHistory();
    // These controls are replaced by rendering; preserve their keyboard identity.
    if (focusedCard !== null) focusControl($('hand').querySelector('[data-card="' + focusedCard + '"]'));
    else if (focusedTarget !== null) focusControl($('battlefield').querySelector('[data-target="' + focusedTarget + '"]'));
    renderedView = view;
    renderedSession = session;
    if (view && view.phase === 'finished' && shownResult !== session + ':' + view.revision) {
      shownResult = session + ':' + view.revision;
      renderResult(view);
      openModal('result');
    }
    scheduleAdvance();
  }

  function notice(message) {
    $('notice').textContent = message || '';
    $('notice').hidden = !message;
  }

  function updateSaveStatus(text, warning) {
    saveText = text;
    saveWarning = Boolean(warning);
    if ($('save-status')) {
      $('save-status').textContent = text;
      $('save-status').classList.toggle('warning', saveWarning);
    }
  }

  function writePreferences() {
    try { root.localStorage.setItem(PREFS_KEY, JSON.stringify(preferences)); }
    catch (_) { updateSaveStatus('Только в этой вкладке · сохранение недоступно', true); }
  }

  function markSaveConflict() {
    saveConflict = true;
    updateSaveStatus('Сохранение изменено в другой вкладке · эта партия только здесь', true);
    return false;
  }

  function checkSaveSlot() {
    if (!engine.state || saveConflict) return !saveConflict;
    try {
      if (root.localStorage.getItem(STORAGE_KEY) !== observedSave) return markSaveConflict();
      return true;
    } catch (_) {
      updateSaveStatus('Только в этой вкладке · сохранение недоступно', true);
      return false;
    }
  }

  function saveMatch(explicitNewGame) {
    if (!engine.state) return false;
    if (saveConflict && !explicitNewGame) return markSaveConflict();
    try {
      if (!E.validate(engine.state).ok) throw new Error('Invalid state');
      const current = root.localStorage.getItem(STORAGE_KEY);
      if (explicitNewGame) { observedSave = current; saveConflict = false; }
      else if (current !== observedSave) return markSaveConflict();
      const serialized = JSON.stringify({ format: 1, state: engine.state, history: history.slice(-80) });
      root.localStorage.setItem(STORAGE_KEY, serialized);
      // Only a successful write becomes the checkpoint for this live branch.
      observedSave = serialized;
      updateSaveStatus('Партия сохранена на этом устройстве', false);
      return true;
    } catch (_) {
      updateSaveStatus('Только в этой вкладке · сохранение недоступно', true);
      return false;
    }
  }

  function loadStorage() {
    try {
      const rawPreferences = root.localStorage.getItem(PREFS_KEY);
      if (rawPreferences) {
        const saved = JSON.parse(rawPreferences);
        if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
          if ([2, 3, 4].includes(saved.playerCount)) preferences.playerCount = saved.playerCount;
          if (typeof saved.sound === 'boolean') preferences.sound = saved.sound;
          if (typeof saved.quick === 'boolean') preferences.quick = saved.quick;
        }
      }
    } catch (_) { updateSaveStatus('Настройки доступны только в этой вкладке', true); }
    try {
      const raw = root.localStorage.getItem(STORAGE_KEY);
      observedSave = raw;
      if (!raw) return;
      const saved = JSON.parse(raw);
      if (!saved || saved.format !== 1 || !saved.state || !E.validate(saved.state).ok) {
        updateSaveStatus('Сохранение повреждено · начните новую партию', true);
        return;
      }
      engine.state = copy(saved.state);
      session++;
      history = Array.isArray(saved.history) ? saved.history.filter(entry => typeof entry === 'string' && entry.length <= 240).slice(-80) : [];
      updateSaveStatus('Найдена сохранённая партия', false);
    } catch (_) { updateSaveStatus('Сохранение недоступно · можно играть в этой вкладке', true); }
  }

  function addHistory(message) {
    history.push(message);
    if (history.length > 160) history.splice(0, history.length - 160);
  }

  function describeAction(action, before, after) {
    const view = E.view(before, 0);
    const name = playerName(before.actor, view);
    if (action.type === 'attack') return name + (before.actor === 0 ? (before.table.length ? ' подкидываете ' : ' ходите ') : (before.table.length ? ' подкидывает ' : ' ходит ')) + E.card(action.card).label + '.';
    if (action.type === 'defend') return name + (before.actor === 0 ? ' бьёте ' : ' бьёт ') + E.card(before.table[action.target].attack).label + ' картой ' + E.card(action.card).label + '.';
    if (action.type === 'take') return name + (before.actor === 0 ? ' решили забрать карты.' : ' решает забрать карты.');
    if (action.type === 'pass') return name + (before.actor === 0 ? ' больше не подкидываете.' : ' больше не подкидывает.');
    if (action.type === 'continue') {
      const result = before.roundResult;
      const base = 'Раунд ' + before.round + ': ' + (result.kind === 'beaten' ? 'отбой.' : playerName(result.defender, view) + (result.defender === 0 ? ' забираете ' : ' забирает ') + cardsWord(before.table.reduce((sum, pair) => sum + (pair.defense ? 2 : 1), 0)) + '.');
      if (after.phase === 'finished') return base + ' Партия завершена.';
      return base + ' Следующий ход: ' + playerName(after.attacker, view) + '.';
    }
    return 'Началась новая партия.';
  }

  function actionEqual(a, b) {
    if (!a || !b || typeof a !== 'object' || Array.isArray(a)) return false;
    const fields = b.type === 'attack' ? ['type', 'card', 'player'] : b.type === 'defend' ? ['type', 'card', 'target', 'player'] : ['type', 'player'];
    return Object.keys(a).every(key => fields.includes(key)) && a.type === b.type && a.card === b.card && a.target === b.target && (a.player === undefined || a.player === engine.state.actor);
  }

  function applyAction(action, source) {
    if (!engine.state || destroyed) return false;
    if (source === 'human' && (engine.state.actor !== 0 || isPaused() || engine.state.phase === 'roundEnd' || engine.state.phase === 'finished')) return false;
    const legal = source === 'system' && engine.state.phase === 'roundEnd' ? E.actions(engine.state) : E.actions(engine.state, source === 'human' ? 0 : engine.state.actor);
    const canonical = legal.find(candidate => actionEqual(action, candidate));
    if (!canonical) return false;
    const before = engine.state;
    try {
      const next = E.step(before, canonical);
      engine.state = next;
      engine.recordEvent(canonical.type);
      selected = null;
      target = null;
      notice('');
      addHistory(describeAction(canonical, before, next));
      if (before.players[0].out === false && next.players[0].out && next.phase !== 'finished') addHistory('Вы вышли без карт. Теперь можно посмотреть финал соперников.');
      saveMatch();
      if(audio)audio.handleEvents(engine.events);
      renderer.draw();
      return true;
    } catch (_) {
      notice('Не удалось выполнить ход. Состояние партии сохранено; попробуйте другую допустимую карту.');
      cancelAdvance();
      return false;
    }
  }

  function isPaused() { return manualPaused || pageHidden || Boolean(doc.hidden) || Boolean(modal) || destroyed; }

  function cancelAdvance() {
    advanceTicket++;
    if (advanceTimer !== null) { root.clearTimeout(advanceTimer); advanceTimer = null; }
  }

  function scheduleAdvance() {
    cancelAdvance();
    if (forgeManualMode || !engine.state || isPaused() || engine.state.phase === 'finished' || engine.state.actor === 0 && engine.state.phase !== 'roundEnd') return;
    const expectedSession = session;
    const expectedRevision = engine.state.revision;
    const expectedPhase = engine.state.phase;
    const expectedTicket = advanceTicket;
    const delay = engine.state.phase === 'roundEnd' ? (preferences.quick ? 340 : 860) : (preferences.quick ? 300 : 820 + engine.state.revision % 3 * 95);
    advanceTimer = root.setTimeout(() => {
      if (expectedTicket !== advanceTicket) return;
      advanceTimer = null;
      if (!engine.state || isPaused() || session !== expectedSession || engine.state.revision !== expectedRevision || engine.state.phase !== expectedPhase) return;
      if (engine.state.phase === 'roundEnd') { applyAction({ type: 'continue' }, 'system'); return; }
      if (engine.state.actor === 0 || engine.state.actor === null) return;
      try {
        const actorView = E.view(engine.state, engine.state.actor);
        const action = B.chooseAction(actorView);
        if (!action || !applyAction(action, 'bot')) throw new Error('Bot did not return an available move');
      } catch (_) {
        cancelAdvance();
        notice('Соперник не смог завершить ход. Откройте и закройте правила, чтобы повторить попытку, или начните новую партию.');
      }
    }, delay);
  }

  function freshSeed() {
    try {
      const bytes = new Uint32Array(2);
      root.crypto.getRandomValues(bytes);
      return Date.now().toString(36) + '-' + bytes[0].toString(36) + bytes[1].toString(36);
    } catch (_) { return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2); }
  }

  function newGame(options, seed) {
    if (destroyed) return null;
    const settings = typeof options === 'number' ? { playerCount: options, seed } : options || {};
    const count = settings.playerCount === undefined ? preferences.playerCount : settings.playerCount;
    if (![2, 3, 4].includes(count)) throw new RangeError('Выберите от 2 до 4 игроков.');
    const next = E.newGame({ playerCount: count, seed: settings.seed === undefined ? (forgePendingSeed === null ? freshSeed() : forgePendingSeed) : settings.seed });
    forgePendingSeed=null;
    cancelAdvance();
    session++;
    engine.state = next;
    engine.seed=next.seed;engine.playerCount=count;engine.session++;engine.paused=false;engine.recordEvent('deal');
    manualPaused = false;
    selected = null;
    target = null;
    shownResult = null;
    history = [];
    preferences.playerCount = count;
    addHistory('Новая партия на ' + count + ' игроков. Козырь: ' + E.card(next.trumpCard).symbol + '. Первым ходит ' + playerName(next.attacker, E.view(next, 0)) + '.');
    closeModal(true);
    $('history-panel').hidden = true;
    $('btn-history').setAttribute('aria-expanded', 'false');
    notice('');
    writePreferences();
    saveMatch(true);
    resetAudioSession();
    if (preferences.sound && audioContext) unlockAudio();
    if(audio)audio.handleEvents(engine.events);
    renderer.draw();
    return copy(engine.state);
  }

  function selectCard(id) {
    if (!engine.state || isPaused() || engine.state.actor !== 0) return false;
    const view = E.view(engine.state, 0);
    const options = view.legalActions.filter(action => action.card === id);
    if (!options.length) return false;
    selected = selected === id ? null : id;
    target = selected && options[0].type === 'defend' ? options[0].target : null;
    notice('');
    sound('select');
    renderer.draw();
    const button = $('hand').querySelector('[data-card="' + id + '"]');
    if (button) {
      try { button.focus({ preventScroll: true }); } catch (_) { /* Older webviews may not support focus options. */ }
      if (typeof button.scrollIntoView === 'function') button.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'auto' });
    }
    return true;
  }

  function selectTarget(index) {
    if (!engine.state || isPaused() || engine.state.actor !== 0 || !Number.isInteger(index)) return false;
    const actions = E.view(engine.state, 0).legalActions.filter(action => action.type === 'defend' && action.target === index);
    if (!actions.length) return false;
    target = index;
    if (selected && !actions.some(action => action.card === selected)) selected = null;
    renderer.draw();
    return true;
  }

  function playSelected() {
    if (!engine.state || !selected) return false;
    const action = E.view(engine.state, 0).legalActions.find(item => item.card === selected && (item.type !== 'defend' || item.target === target));
    return action ? applyAction(action, 'human') : false;
  }

  function openModal(name) {
    if (destroyed) return;
    if (name === 'rules') returnModal = modal === 'start' || modal === 'result' ? modal : null;
    else returnModal = null;
    if (!modal) previousFocus = doc.activeElement;
    ['start', 'rules', 'result'].forEach(item => { $('modal-' + item).hidden = item !== name; });
    modal = name;
    cancelAdvance();
    doc.body.classList.add('modal-open');
    $('app').setAttribute('inert', '');
    $('app').setAttribute('aria-hidden', 'true');
    if (name === 'start') {
      $('welcome-title').textContent = engine.state ? 'Новая партия.' : 'Дурак.';
      $('welcome-copy').innerHTML = engine.state ? 'Выберите компанию для следующей раздачи.<br>Текущая партия заменится после нажатия кнопки.' : 'Знакомая игра. Достойная компания.<br>Один стол — вы и компьютерные соперники.';
      $('btn-resume').hidden = !engine.state;
      $('btn-resume').textContent = engine.state && engine.state.phase === 'finished' ? 'Посмотреть завершённую партию' : 'Продолжить партию';
      $('btn-close-start').hidden = !engine.state;
    }
    const overlay = $('modal-' + name);
    const focusable = overlay.querySelector('button:not([hidden]):not([disabled])');
    if (focusable && typeof focusable.focus === 'function') focusable.focus();
  }

  function closeModal(force) {
    if (!force && modal === 'rules' && returnModal) {
      const destination = returnModal;
      returnModal = null;
      openModal(destination);
      return;
    }
    if (!force && !engine.state) { openModal('start'); return; }
    ['start', 'rules', 'result'].forEach(item => { $('modal-' + item).hidden = true; });
    modal = null;
    returnModal = null;
    doc.body.classList.remove('modal-open');
    $('app').removeAttribute('inert');
    $('app').removeAttribute('aria-hidden');
    if (!focusControl(previousFocus)) focusControl($('btn-new'));
    previousFocus = null;
    scheduleAdvance();
  }

  function focusControl(element) {
    if (!element || element === doc.body || !doc.contains(element) || element.disabled || element.closest('[hidden], [inert]') || typeof element.focus !== 'function') return false;
    try { element.focus({ preventScroll: true }); }
    catch (_) { try { element.focus(); } catch (_) { return false; } }
    return true;
  }

  function renderResult(view) {
    const result = view.result;
    let title, description, emblem;
    if (result.draw) {
      title = 'Ничья. Красиво.';
      description = 'Последние карты ушли в отбой. За этим столом сегодня нет дурака.';
      emblem = '♧';
    } else if (result.durak === 0) {
      title = 'Реванш?';
      description = 'На этот раз карты остались у вас. Колода уже ждёт, чтобы всё переиграть.';
      emblem = '♦';
    } else {
      title = 'Вы вышли!';
      description = 'У вас не осталось карт. ' + playerName(result.durak, view) + ' завершает эту партию с картами на руках.';
      emblem = '♠';
    }
    $('result-title').textContent = title;
    $('result-copy').textContent = description;
    $('result-emblem').textContent = emblem;
    $('result-summary').innerHTML = '<div><strong>' + view.round + '</strong><span>раундов</span></div><div><strong>' + view.players.length + '</strong><span>игрока</span></div><div><strong>' + (result.draw ? '—' : esc(playerName(result.durak, view))) + '</strong><span>' + (result.draw ? 'дурака нет' : 'остался с картами') + '</span></div>';
  }

  function unlockAudio() {
    if (!preferences.sound || destroyed || manualPaused || pageHidden || doc.hidden) return false;
    try {
      if (!audioContext) {
        const Context = root.AudioContext || root.webkitAudioContext;
        if (!Context) throw new Error('No audio');
        audioContext = new Context();
        audio = new GameAudio(audioContext, audioContext.destination);
      }
      audio.setState({enabled:true});
      if (audioContext.state !== 'running' && audioContext.state !== 'closed' && typeof audioContext.resume === 'function' && !audioResumePending) {
        const context = audioContext;
        const resumed = context.resume();
        if (resumed && typeof resumed.then === 'function') {
          const pending = { context };
          audioResumePending = pending;
          resumed.then(() => {
            if (audioResumePending === pending) audioResumePending = null;
            if (context === audioContext && (!preferences.sound || destroyed || manualPaused || pageHidden || doc.hidden)) suspendAudio();
          }, () => { if (audioResumePending === pending) audioResumePending = null; });
        }
      }
      return true;
    } catch (_) {
      preferences.sound = false;
      renderPreferences();
      notice('Этот браузер не поддерживает звуки игры. Партию можно продолжить без звука.');
      return false;
    }
  }

  function suspendAudio() {
    cancelSounds();
    if(audio)audio.setState({enabled:false});
    if (audioContext && audioContext.state === 'running' && typeof audioContext.suspend === 'function') {
      try {
        const context = audioContext;
        const promise = context.suspend();
        if (promise && typeof promise.then === 'function') promise.then(() => {
          // A newer unmute may have arrived while suspend was still pending.
          if (context === audioContext && preferences.sound && !destroyed && !manualPaused && !pageHidden && !doc.hidden) unlockAudio();
        }, () => {});
      } catch (_) { /* Best effort. */ }
    }
  }

  function cancelSounds(){if(audio)audio.cancel();}
  function sound(kind){
    if(destroyed||manualPaused||pageHidden||doc.hidden||modal&&modal!=='result')return;
    if(audio)audio.play(kind);
  }
  function resetAudioSession(){
    if(audio)audio.dispose();audio=null;
    if(audioContext&&audioContext.state!=='closed'){
      audio=new GameAudio(audioContext,audioContext.destination);
      audio.setState({enabled:preferences.sound&&!manualPaused&&!pageHidden&&!doc.hidden,mode:engine.state?engine.state.phase:'menu'});
    }
  }
  function init() {
    if (initialized && !destroyed) return root.DurakApp;
    if (!E || !B || !doc) throw new Error('Durak engine, bots and document are required.');
    initialized = true;
    destroyed = false;
    engine.paused=false;engine.events=[];forgePendingSeed=null;
    cancelAdvance();
    session++;
    engine.state = null; selected = null; target = null;
    manualPaused = false; modal = null; returnModal = null; previousFocus = null;
    renderedView = null; renderedSession = -1; shownResult = null;
    observedSave = null; saveConflict = false; history = [];
    preferences = { playerCount: 2, sound: false, quick: false };
    updateSaveStatus('Без регистрации · работает без сети', false);
    ['start', 'rules', 'result'].forEach(name => { $('modal-' + name).hidden = true; });
    $('history-panel').hidden = true;
    $('btn-history').setAttribute('aria-expanded', 'false');
    notice('');
    pageHidden = Boolean(doc.hidden);
    $('welcome-queen').innerHTML = cardArt('H12');
    $('welcome-ace').innerHTML = cardArt('S14');
    listen($('hand'), 'click', event => {
      const card = event.target.closest ? event.target.closest('[data-card]') : null;
      if (card && !card.disabled && $('hand').contains(card)) { unlockAudio(); selectCard(card.getAttribute('data-card')); }
    });
    listen($('battlefield'), 'click', event => {
      const element = event.target.closest ? event.target.closest('[data-target]') : null;
      if (element && $('battlefield').contains(element)) selectTarget(Number(element.getAttribute('data-target')));
    });
    listen($('btn-play'), 'click', () => { unlockAudio(); playSelected(); });
    listen($('btn-pass'), 'click', () => { unlockAudio(); applyAction({ type: 'pass' }, 'human'); });
    listen($('btn-take'), 'click', () => { unlockAudio(); applyAction({ type: 'take' }, 'human'); });
    listen($('btn-start'), 'click', () => { unlockAudio(); newGame(); });
    listen($('btn-new'), 'click', () => openModal('start'));
    listen($('btn-close-start'), 'click', () => closeModal());
    listen($('btn-resume'), 'click', () => { unlockAudio(); closeModal(true); if (engine.state && engine.state.phase === 'finished') { renderResult(E.view(engine.state, 0)); openModal('result'); } });
    listen($('btn-rules'), 'click', () => openModal('rules'));
    listen($('btn-welcome-rules'), 'click', () => openModal('rules'));
    listen($('btn-close-rules'), 'click', () => closeModal());
    listen($('btn-rules-done'), 'click', () => closeModal());
    listen($('btn-close-result'), 'click', () => closeModal());
    listen($('btn-result-table'), 'click', () => closeModal());
    listen($('btn-again'), 'click', () => openModal('start'));
    listen($('btn-sound'), 'click', () => {
      preferences.sound = !preferences.sound;
      if (preferences.sound) { unlockAudio(); sound('select'); } else suspendAudio();
      writePreferences(); renderPreferences();
    });
    listen($('btn-speed'), 'click', () => { preferences.quick = !preferences.quick; writePreferences(); renderPreferences(); scheduleAdvance(); });
    doc.querySelectorAll('[data-player-count]').forEach(button => listen(button, 'click', () => { preferences.playerCount = Number(button.getAttribute('data-player-count')); writePreferences(); renderPreferences(); }));
    listen($('btn-history'), 'click', () => { const show = $('history-panel').hidden; $('history-panel').hidden = !show; $('btn-history').setAttribute('aria-expanded', String(show)); });
    listen($('btn-close-history'), 'click', () => { $('history-panel').hidden = true; $('btn-history').setAttribute('aria-expanded', 'false'); $('btn-history').focus(); });
    ['start', 'rules', 'result'].forEach(name => listen($('modal-' + name), 'click', event => { if (event.target === $('modal-' + name) && engine.state) closeModal(); }));
    listen(doc, 'keydown', event => {
      if (event.key === 'Escape') {
        if (modal) { event.preventDefault(); closeModal(); }
        else if (selected) { selected = null; target = null; renderer.draw(); event.preventDefault(); }
      } else if (event.key === 'Tab' && modal) {
        const buttons = Array.from($('modal-' + modal).querySelectorAll('button:not([hidden]):not([disabled])')).filter(button => !button.closest('[hidden]'));
        const first = buttons[0], last = buttons[buttons.length - 1];
        if (buttons.length && event.shiftKey && (doc.activeElement === first || !buttons.includes(doc.activeElement))) { event.preventDefault(); last.focus(); }
        else if (buttons.length && !event.shiftKey && (doc.activeElement === last || !buttons.includes(doc.activeElement))) { event.preventDefault(); first.focus(); }
      } else if (event.key === 'Enter' && !modal && selected) {
        const element = event.target;
        const handCard = element && element.closest ? element.closest('.hand-card') : null;
        if (!element || element === doc || element === doc.body || element.id === 'btn-play' || handCard && handCard.getAttribute('data-card') === selected) { event.preventDefault(); unlockAudio(); playSelected(); }
      }
    });
    listen(doc, 'visibilitychange', () => { pageHidden = Boolean(doc.hidden); if (pageHidden) { cancelAdvance(); suspendAudio(); } else { checkSaveSlot(); if (preferences.sound && audioContext) unlockAudio(); scheduleAdvance(); } });
    listen(root, 'pagehide', () => { pageHidden = true; cancelAdvance(); suspendAudio(); });
    listen(root, 'pageshow', () => { pageHidden = Boolean(doc.hidden); checkSaveSlot(); if (!pageHidden && preferences.sound && audioContext) unlockAudio(); scheduleAdvance(); });
    listen(root, 'storage', event => { if (event.key === null || event.key === STORAGE_KEY) checkSaveSlot(); });
    loadStorage();
    renderer.draw();
    openModal('start');
    return root.DurakApp;
  }

  function setPaused(value) {
    manualPaused = Boolean(value);engine.paused=manualPaused;
    if (manualPaused) { cancelAdvance(); suspendAudio(); }
    else { if (preferences.sound && audioContext) unlockAudio(); scheduleAdvance(); }
    return manualPaused;
  }

  function destroy() {
    if (destroyed) return;
    destroyed = true;
    session++;
    cancelAdvance();
    listeners.splice(0).forEach(remove => remove());
    cancelSounds();
    if(audio)audio.dispose();audio=null;
    if(audioContext&&typeof audioContext.close==='function'){
      try{const promise=audioContext.close();if(promise&&typeof promise.catch==='function')promise.catch(()=>{});}catch(_){}
    }
    audioContext=null;audioResumePending=null;
    doc.body.classList.remove('modal-open');
    $('app').removeAttribute('inert');
    $('app').removeAttribute('aria-hidden');
  }

  root.DurakApp = Object.freeze({
    init, newGame, selectCard, selectTarget, playSelected,
    dispatch: action => applyAction(action, 'human'),
    getState: () => engine.state ? copy(engine.state) : null,
    getView: () => engine.state ? E.view(engine.state, 0) : null,
    setPaused, destroy,
    storageKey: STORAGE_KEY,
    preferencesKey: PREFS_KEY
  });
  init();


// QA invokes the same state and action dispatcher as visible controls.
function forgeSnapshot(){
  const snapshot=engine.snapshot();snapshot.paused=manualPaused;
  snapshot.persistence={status:saveConflict?'conflict':saveWarning?'memory':engine.state?'saved':'empty'};
  return snapshot;
}
function forgeAction(action){
  if(!action||typeof action!=='object'||Array.isArray(action)||destroyed)return false;
  if(action.type==='start'){newGame({seed:action.seed??engine.seed,playerCount:action.playerCount??engine.playerCount});return true;}
  if(action.type==='pause'){setPaused(action.value);return true;}
  if(isPaused()||!engine.state)return false;
  if(action.type==='stepBot'){
    if(engine.state.actor===null||engine.state.actor===0)return false;
    return applyAction(B.chooseAction(E.view(engine.state,engine.state.actor)),'bot');
  }
  if(action.type==='continue')return engine.state.phase==='roundEnd'&&applyAction({type:'continue'},'system');
  return applyAction(action,'human');
}
function forgeImport(text){
  const saved=GameEngine.parseSave(text);if(!saved)return {ok:false};
  // Explicit synchronous restore may replace this session, but it still honors
  // the original best-effort guard against overwriting another tab's save.
  cancelAdvance();session++;engine.session++;
  engine.state=saved.state;engine.seed=saved.state.seed;engine.playerCount=saved.state.players.length;
  engine.events=[];engine.paused=false;manualPaused=false;
  selected=null;target=null;shownResult=null;history=saved.history;
  closeModal(true);resetAudioSession();saveMatch();renderer.draw();return {ok:true};
}
const forgeBridge={ready:true,snapshot:forgeSnapshot,act:forgeAction,
  reset(options={}){engine.seed=String(options.seed??'durak-corpus');engine.playerCount=options.playerCount??2;
    cancelAdvance();session++;engine.reset(options);manualPaused=false;selected=null;target=null;history=[];shownResult=null;
    forgePendingSeed=engine.seed;closeModal(true);resetAudioSession();renderer.draw();openModal('start');return forgeSnapshot();},
  setManualMode(enabled){forgeManualMode=Boolean(enabled);scheduleAdvance();},
  advance(){throw new Error('Durak is turn-based; wall time is not a legal card move');},
  exportSave(){return JSON.stringify({format:1,state:engine.state,history:history.slice(-80)});},
  importSave:forgeImport,
  remount(){const manual=forgeManualMode;destroy();init();forgeManualMode=manual;if(engine.state)closeModal(true);scheduleAdvance();return {ok:true};}
};
root.__GAME_TEST__=forgeBridge;
const forgeController={dispose(){
  if(forgeDisposed)return;forgeDisposed=true;destroy();renderer.dispose();engine.dispose();
  if(root.__GAME_TEST__===forgeBridge)delete root.__GAME_TEST__;
  if(root.__DURAK_CORPUS_MOUNT__===forgeController)delete root.__DURAK_CORPUS_MOUNT__;
  host.replaceChildren();
}};
root.__DURAK_CORPUS_MOUNT__=forgeController;
return forgeController;
}
