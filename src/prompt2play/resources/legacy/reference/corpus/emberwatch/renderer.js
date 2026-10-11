/* Emberwatch procedural painter. No network/assets; state is read only. */
class GameRenderer {
  constructor(canvas, engine) {
    this.canvas = canvas; this.engine = engine; this.ctx = canvas.getContext('2d');
    this.width = 1000; this.height = 640; this.clock = 0; this.disposed = false;
    this.cache = null; this.cssWidth = 0; this.cssHeight = 0; this.dpr = 1;
    this.resize();
  }
  resize() {
    if (this.disposed) return;
    const rect = this.canvas.getBoundingClientRect();
    const width = Math.max(1, rect.width || this.canvas.clientWidth || 1000);
    const height = Math.max(1, rect.height || this.canvas.clientHeight || 640);
    const ratio = Math.max(1, Math.min(2, Number(globalThis.devicePixelRatio) || 1));
    if (this.cache && width === this.cssWidth && height === this.cssHeight && ratio === this.dpr) return;
    this.cssWidth = width; this.cssHeight = height; this.dpr = ratio;
    this.canvas.width = Math.round(width * ratio); this.canvas.height = Math.round(height * ratio);
    this.scale = Math.min(this.canvas.width / this.width, this.canvas.height / this.height);
    this.offsetX = (this.canvas.width - this.width * this.scale) / 2;
    this.offsetY = (this.canvas.height - this.height * this.scale) / 2;
    const resolution = Math.min(ratio, 1.6);
    if (this.cache) { this.cache.width = 1; this.cache.height = 1; }
    if (typeof OffscreenCanvas !== 'undefined') this.cache = new OffscreenCanvas(Math.ceil(1000 * resolution), Math.ceil(640 * resolution));
    else if (typeof document !== 'undefined') { this.cache = document.createElement('canvas'); this.cache.width = Math.ceil(1000 * resolution); this.cache.height = Math.ceil(640 * resolution); }
    else this.cache = new this.canvas.constructor(Math.ceil(1000 * resolution), Math.ceil(640 * resolution));
    const c = this.cache.getContext('2d'); c.scale(resolution, resolution);
    this._scenery(c, this.engine.getState());
  }
  worldPoint(clientX, clientY) {
    if (this.disposed) return { x: NaN, y: NaN };
    const r = this.canvas.getBoundingClientRect();
    if (!r.width || !r.height || !Number.isFinite(clientX) || !Number.isFinite(clientY)) return { x: NaN, y: NaN };
    return { x: ((clientX - r.left) * this.canvas.width / r.width - this.offsetX) / this.scale,
      y: ((clientY - r.top) * this.canvas.height / r.height - this.offsetY) / this.scale };
  }
  pickPad(clientX, clientY) {
    const point = this.worldPoint(clientX, clientY);
    if (!Number.isFinite(point.x) || point.x < 0 || point.x > 1000 || point.y < 0 || point.y > 640) return null;
    const r = this.canvas.getBoundingClientRect();
    const pixelsPerWorld = this.scale * r.width / this.canvas.width;
    const radius = Math.min(48, Math.max(29, 22 / pixelsPerWorld));
    let nearest = null, distance = radius * radius;
    for (const pad of this.engine.getState().pads) {
      const d = (pad.x - point.x) ** 2 + (pad.y - point.y) ** 2;
      if (d <= distance) { distance = d; nearest = pad.id; }
    }
    return nearest;
  }
  _random(seed) {
    let n = seed >>> 0;
    return () => { n = (Math.imul(n, 1664525) + 1013904223) >>> 0; return n / 4294967296; };
  }
  _ellipse(c, x, y, rx, ry, fill, stroke) {
    c.beginPath(); c.ellipse(x, y, Math.max(.01, rx), Math.max(.01, ry), 0, 0, Math.PI * 2);
    if (fill) { c.fillStyle = fill; c.fill(); }
    if (stroke) { c.strokeStyle = stroke; c.stroke(); }
  }
  _poly(c, points, fill, stroke) {
    c.beginPath(); points.forEach(([x,y], i) => i ? c.lineTo(x,y) : c.moveTo(x,y)); c.closePath();
    if (fill) { c.fillStyle = fill; c.fill(); } if (stroke) { c.strokeStyle = stroke; c.stroke(); }
  }
  _line(c, points, color, width = 1) {
    c.beginPath(); points.forEach(([x,y], i) => i ? c.lineTo(x,y) : c.moveTo(x,y)); c.strokeStyle = color; c.lineWidth = width; c.stroke();
  }
  _glow(c, x, y, radius, color) {
    const g = c.createRadialGradient(x,y,1,x,y,radius); g.addColorStop(0,color); g.addColorStop(1,'rgba(0,0,0,0)');
    this._ellipse(c,x,y,radius,radius,g);
  }
  _distanceToRoad(x,y,path) {
    let best = Infinity;
    for (let i = 1; i < path.length; i++) {
      const a = path[i-1], b = path[i], dx = b.x-a.x, dy=b.y-a.y;
      const t = Math.max(0,Math.min(1,((x-a.x)*dx+(y-a.y)*dy)/(dx*dx+dy*dy || 1)));
      best = Math.min(best,Math.hypot(x-a.x-t*dx,y-a.y-t*dy));
    }
    return best;
  }
  _scenery(c, state) {
    const rand = this._random(832701), road = state.path;
    const ground = c.createLinearGradient(0,0,700,640); ground.addColorStop(0,'#284e3f'); ground.addColorStop(.48,'#254c3b'); ground.addColorStop(1,'#153b35');
    c.fillStyle=ground; c.fillRect(0,0,1000,640);
    // Broad painted hill washes, followed by small dry-brush grass strokes.
    for (let i=0;i<42;i++) this._ellipse(c,rand()*1000,rand()*640,35+rand()*145,20+rand()*50,['#34593b40','#0b302c55','#55714420','#355d4840'][i%4]);
    for (let i=0;i<3300;i++) {
      const x=rand()*1000,y=rand()*640; c.fillStyle=['#9db46b1b','#7d96511d','#11372b55','#55896824'][i%4];
      c.fillRect(x,y,2+rand()*6,.7+rand()*1.2);
    }
    // The quiet south-west pond, with terraced shale rather than road obstruction.
    this._poly(c,[[22,348],[72,315],[153,327],[203,381],[181,458],[110,484],[38,438]],'#173b34','#4d6550');
    this._poly(c,[[34,355],[78,330],[145,340],[184,383],[165,444],[108,463],[48,429]],'#16494c','#66827655');
    this._poly(c,[[48,359],[82,344],[138,350],[169,389],[149,431],[104,448],[58,415]],'#1b5052');
    for(let i=0;i<20;i++){const y=351+i*4.5,x=66+Math.sin(i)*14;this._line(c,[[x,y],[x+35+rand()*40,y]],'#75ad951e',1);}
    for(const [x,y] of [[40,345],[50,442],[155,335],[176,448],[93,472]]) {
      this._poly(c,[[x-14,y+4],[x-11,y-9],[x+4,y-15],[x+17,y-5],[x+12,y+8]],'#36514a','#667765');
      this._line(c,[[x-11,y-9],[x+4,y-15],[x+17,y-5]],'#8a95816b',2);
    }
    // Road is exactly the engine polyline; round joins preserve every turn.
    c.lineCap='round';c.lineJoin='round';
    const points=road.map(p=>[p.x,p.y]);
    this._line(c,points,'#0a252d77',66); this._line(c,points,'#6d6742',53);
    this._line(c,points,'#c6a16a',43); this._line(c,points,'#b68e57',35); this._line(c,points,'#c29e6577',23);
    // Seeded grit and stepping-stones never spill outside the route.
    for(let i=1;i<road.length;i++){
      const a=road[i-1],b=road[i],dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy),nx=-dy/len,ny=dx/len;
      for(let d=5;d<len;d+=7+rand()*8){const t=d/len,off=(rand()-.5)*36,x=a.x+dx*t+nx*off,y=a.y+dy*t+ny*off;
        this._ellipse(c,x,y,1.5+rand()*2,.7+rand(),rand()>.5?'#edd5a144':'#785e3a66');}
      for(let d=15;d<len;d+=31+rand()*12){const x=a.x+dx*d/len,y=a.y+dy*d/len;
        c.save();c.translate(x,y);c.rotate(Math.atan2(dy,dx));this._poly(c,[[-6,-9],[5,-8],[7,7],[-4,10]],'#d1b27a38','#836a4133');c.restore();}
    }
    // Fourteen readable, inset stone foundations.
    for(const pad of state.pads){
      this._ellipse(c,pad.x,pad.y+5,33,24,'#102f2c88');
      this._ellipse(c,pad.x,pad.y,29,22,'#656b55','#919579');
      this._ellipse(c,pad.x,pad.y-1,25,18,'#465c4b','#9bab7b44');
      for(let a=0;a<Math.PI*2;a+=Math.PI/4)this._line(c,[[pad.x+Math.cos(a)*24,pad.y+Math.sin(a)*18],[pad.x+Math.cos(a)*29,pad.y+Math.sin(a)*22]],'#263e33',2);
      this._line(c,[[pad.x-6,pad.y],[pad.x+6,pad.y]],'#b4bc8e88',1.7);this._line(c,[[pad.x,pad.y-5],[pad.x,pad.y+5]],'#b4bc8e88',1.7);
    }
    const trees=[];
    for(let i=0;i<185;i++){
      const x=rand()*1050-25,y=rand()*690-30;
      if(this._distanceToRoad(x,y,road)<65 || state.pads.some(p=>Math.hypot(p.x-x,p.y-y)<55) || (x>862&&y>352&&y<513) || (x<215&&y>302&&y<490))continue;
      trees.push({x,y,size:19+rand()*25,color:rand()});
    }
    // Dense border copses frame the battlefield without concealing pads/units.
    for(let i=0;i<54;i++){const x=i*21-30,y=i%2?-4:653;if(this._distanceToRoad(x,y,road)>70)trees.push({x,y,size:27+rand()*17,color:rand()});}
    trees.sort((a,b)=>a.y-b.y).forEach(t=>this._tree(c,t.x,t.y,t.size,t.color));
    for(let i=0;i<55;i++){
      const x=rand()*1000,y=rand()*640;
      if(this._distanceToRoad(x,y,road)<36||state.pads.some(p=>Math.hypot(x-p.x,y-p.y)<36))continue;
      this._ellipse(c,x,y+2,6,3,'#0b272766');this._poly(c,[[x-6,y],[x-3,y-6],[x+2,y-8],[x+7,y-2],[x+5,y+2]],'#61725a','#94a08144');
    }
    this._castle(c);
    // Old boundary stones and a tiny watchman's camp.
    for(const [x,y] of [[323,449],[318,477],[827,85]]){this._ellipse(c,x,y+4,9,4,'#122c2a88');this._poly(c,[[x-5,y+2],[x-4,y-16],[x+3,y-19],[x+6,y+2]],'#768676','#9aad9299');this._line(c,[[x-2,y-11],[x+2,y-11]],'#a9c89a',1);}
    this._poly(c,[[254,570],[273,539],[296,569]],'#b9975c','#dec898');this._poly(c,[[273,539],[287,546],[308,571],[296,569]],'#756044');this._poly(c,[[270,569],[276,552],[282,569]],'#27382d');
    this._line(c,[[249,571],[309,572]],'#6d8260',2);
    // Soft painted vignette, not an opaque HUD over the field.
    const shade=c.createRadialGradient(500,305,190,500,320,615);shade.addColorStop(0,'#051b2400');shade.addColorStop(1,'#051b2477');c.fillStyle=shade;c.fillRect(0,0,1000,640);
  }
  _tree(c,x,y,size,tone) {
    this._ellipse(c,x+7,y+9,size*.75,size*.32,'#072b2b88');
    this._line(c,[[x,y+6],[x-1,y-size*.65]],'#493f2b',4);
    const autumn=tone>.62, base=autumn?'#976d35':'#285843',mid=autumn?'#bd914b':'#3b7150',light=autumn?'#d4ad61':'#62905e';
    if(tone<.27){
      for(let j=0;j<3;j++){const yy=y-j*size*.3;this._poly(c,[[x-size*(.55-j*.08),yy],[x,yy-size*.9],[x+size*(.55-j*.08),yy]],j%2?mid:base);this._line(c,[[x-size*(.45-j*.08),yy-3],[x,yy-size*.82]],light+'99',1.3);}
    } else {
      this._ellipse(c,x,y-size*.45,size*.7,size*.6,base);
      for(let j=0;j<5;j++){const a=j*2.4;this._ellipse(c,x+Math.sin(a)*size*.34,y-size*.56+Math.cos(a)*size*.23,size*.39,size*.32,j%2?mid:base);}
      this._ellipse(c,x-size*.15,y-size*.87,size*.4,size*.24,light+'bb');
      this._line(c,[[x-8,y-size*.61],[x-3,y-size*.69],[x+3,y-size*.67]],light,1.3);
    }
  }
  _castle(c) {
    this._ellipse(c,946,447,79,43,'#0a292da0');
    this._poly(c,[[884,409],[970,395],[1006,422],[1004,474],[920,488],[884,459]],'#676f60','#aeb297');
    this._poly(c,[[884,409],[922,434],[920,488],[884,459]],'#59695c');
    this._poly(c,[[922,434],[1006,422],[1004,474],[920,488]],'#84917a');
    for(let row=0;row<4;row++)for(let col=0;col<5;col++)this._line(c,[[925+col*16+(row%2)*6,440+row*10],[936+col*16+(row%2)*6,438+row*10]],'#57695999',1);
    c.fillStyle='#172d2e';c.fillRect(946,445,25,32);c.beginPath();c.arc(958.5,445,12.5,Math.PI,0);c.fill();
    this._line(c,[[947,476],[948,446],[969,443],[969,473]],'#d6c596',2);
    for(let x=951;x<969;x+=5)this._line(c,[[x,447],[x,472]],'#4d5b48',1.5);
    for(const [x,y] of [[892,417],[987,412]]) {
      this._poly(c,[[x-14,y-7],[x+13,y-9],[x+13,y+32],[x-14,y+35]],'#8d9880','#b3b698');
      this._ellipse(c,x,y-8,16,9,'#667667','#bbc4a0');
      for(let j=-1;j<=1;j++){c.fillStyle='#abb395';c.fillRect(x-13+j*9+9,y-22,6,14);}
      c.fillStyle='#263d38';c.fillRect(x-2,y+2,4,13);
    }
    this._poly(c,[[927,412],[956,409],[956,359],[927,362]],'#899c89','#c0c7a5');
    this._poly(c,[[919,364],[941,333],[965,359]],'#4c7270','#8cb0a0');
    this._poly(c,[[941,333],[947,361],[965,359]],'#2a5052');
    c.fillStyle='#173c3c';c.fillRect(938,376,8,17);
    this._line(c,[[941,334],[941,310]],'#c3b37d',2);
    this._poly(c,[[943,311],[969,314],[960,320],[944,323]],'#d9ac5c','#ffda8b');
    c.fillStyle='#375d56';c.fillRect(935,397,10,21);this._poly(c,[[935,418],[940,424],[945,418]],'#375d56');
    this._glow(c,938,413,38,'#ffdc7330');
  }
  render(dt, options = {}) {
    if(this.disposed || !this.cache) return;
    const state=this.engine.getState(), reduced=!!options.reducedMotion;
    const paused=!!state.paused || state.phase==='won' || state.phase==='lost';
    if(!paused && !reduced && Number.isFinite(dt))this.clock+=Math.max(0,Math.min(.1,dt));
    const c=this.ctx; c.setTransform(1,0,0,1,0,0);c.globalAlpha=1;c.fillStyle='#102b2c';c.fillRect(0,0,this.canvas.width,this.canvas.height);
    c.setTransform(this.scale,0,0,this.scale,this.offsetX,this.offsetY);c.save();c.beginPath();c.rect(0,0,1000,640);c.clip();
    c.drawImage(this.cache,0,0,1000,640); c.lineJoin='round';c.lineCap='round';
    const selected=options.selectedPadId ?? state.selectedPad, hover=options.hoverPadId;
    for(const pad of state.pads){
      const tower=state.towers.find(t=>t.padId===pad.id), chosen=pad.id===selected, over=pad.id===hover;
      if(chosen || over){
        const type=tower?.type || options.buildType;
        if(type){const range=this.engine.getTowerStats(type,tower?.level || 1).range;
          this._ellipse(c,pad.x,pad.y,range,range,chosen?'#acdabb12':'#acdabb09');
          c.setLineDash([5,7]);c.lineWidth=1.4;this._ellipse(c,pad.x,pad.y,range,range,null,chosen?'#d7d99e88':'#a7cdb855');c.setLineDash([]);}
        c.lineWidth=chosen?2.5:1.5;this._ellipse(c,pad.x,pad.y,32,25,chosen?'#f4d48722':null,chosen?'#ffe2a1':'#a8d5bd');
        if(!tower){this._glow(c,pad.x,pad.y-5,30,'#f6d58c22');c.fillStyle='#f5ddb0';c.font='bold 11px Georgia';c.textAlign='center';c.fillText(pad.id,pad.x,pad.y+4);}
      }
    }
    this._portal(c,reduced?0:this.clock);
    // Depth sort feet/foundations; towers remain legible around the curved road.
    const objects=[...state.towers.map(value=>({kind:'tower',value,y:value.y})),...state.enemies.map(value=>({kind:'enemy',value,y:value.y}))];
    objects.sort((a,b)=>a.y-b.y);
    for(const item of objects){if(item.kind==='tower')this._tower(c,item.value,reduced?0:state.time,reduced);else this._enemy(c,item.value,reduced?0:state.time,reduced,state.time);}
    for(const p of state.projectiles)this._projectile(c,p,reduced);
    for(const effect of state.effects.slice(-160))this._effect(c,effect,reduced);
    if(options.meteorAim && Number.isFinite(options.meteorAim.x) && Number.isFinite(options.meteorAim.y))this._meteor(c,options.meteorAim,state.meteor.radius,reduced?0:this.clock);
    // Warm firefly motes, deterministic and capped. No per-frame particle pool.
    if(!reduced)for(let i=0;i<12;i++){
      const x=(i*173+Math.sin(this.clock*.17+i)*20+1010)%1000,y=(i*97+Math.cos(this.clock*.19+i)*15+652)%640;
      const alpha=.12+.18*(.5+.5*Math.sin(this.clock*1.1+i));c.globalAlpha=alpha;this._ellipse(c,x,y,1.4,1.4,'#ffdc8d');
    }
    c.globalAlpha=1;c.restore();
  }
  _portal(c,t) {
    this._glow(c,29,143,61,'#4fd9c44a');
    this._ellipse(c,29,153,30,14,'#102929b0');
    c.save();c.translate(29,133);c.rotate(-.11);
    this._ellipse(c,0,0,22,32,'#153b47','#78bfc0');
    this._ellipse(c,0,0,15,25,'#215961','#85ede299');
    for(let i=0;i<4;i++){
      c.beginPath();c.ellipse(Math.sin(t*.7+i)*3,Math.cos(t*.9+i)*3,6+i*3,9+i*4,t*.14+i*.4,.3,Math.PI*1.55);c.strokeStyle=i%2?'#a7ffe58c':'#5abebc77';c.lineWidth=1.4;c.stroke();
    }
    for(let i=0;i<8;i++){const a=i*Math.PI/4;this._ellipse(c,Math.cos(a)*22,Math.sin(a)*31,1.8,1.8,'#b0f4d6');}
    c.restore();
    this._poly(c,[[7,151],[8,119],[15,112],[17,150]],'#718681','#b3c8af');this._poly(c,[[42,152],[42,114],[48,117],[52,151]],'#607c78','#a3bdaa');
    this._line(c,[[12,125],[12,132]],'#b8f2cf',2);this._line(c,[[47,130],[47,138]],'#b8f2cf',2);
  }
  _tower(c,t,time,reduced) {
    const level=t.level||1, selectedColor={archer:'#e2bf6b',cannon:'#eba16a',frost:'#88e0e7',arcane:'#d8a6f6'}[t.type]||'#dfc18c';
    c.save();c.translate(t.x,t.y);
    this._ellipse(c,4,7,25,12,'#0a292dab');
    this._poly(c,[[-22,0],[-18,-12],[15,-15],[23,-3],[19,10],[-15,12]],'#667363','#a1aa86');
    this._poly(c,[[-19,2],[-14,-8],[12,-10],[20,-1],[16,6],[-12,8]],'#81896b','#c6bd8e44');
    if(t.type==='archer'){
      const height=34+level*4;
      this._poly(c,[[-12,-4],[-11,-height],[11,-height],[13,-5]],'#715536','#b89354');
      this._poly(c,[[4,-5],[4,-height],[11,-height],[13,-5]],'#463f2b');
      for(let y=-10;y>-height;y-=9)this._line(c,[[-11,y],[11,y-2]],'#bf976055',1);
      this._line(c,[[-12,-3],[10,-height+4]],'#bf9e67',2);this._line(c,[[11,-4],[-11,-height+4]],'#b59056',2);
      this._ellipse(c,0,-height,20,10,'#785935','#d3aa6d');
      this._poly(c,[[-23,-height-5],[0,-height-24],[24,-height-7]],level===3?'#c19144':'#9f6042','#e6b76e');
      this._poly(c,[[0,-height-24],[5,-height-7],[24,-height-7]],'#65452f');
      c.save();c.translate(0,-height+4);c.rotate(t.angle||0);
      this._line(c,[[-10,-11],[-3,0],[-10,11]],'#e4cd91',2.5);this._line(c,[[-10,-11],[-10,11]],'#eee0b8',.7);this._line(c,[[-11,0],[18,0]],'#493922',3);this._line(c,[[5,0],[22,0]],'#e4d4a4',1.3);
      c.restore();
      if(level>1){this._line(c,[[-15,-height],[ -15,-height-30]],'#d9bf75',1.4);this._poly(c,[[-15,-height-30],[-29,-height-27],[-15,-height-20]],'#d6a657');}
    } else if(t.type==='cannon'){
      this._poly(c,[[-18,-6],[-17,-28],[15,-31],[19,-7]],'#677675','#abb4a0');
      for(let y=-12;y>-28;y-=8)this._line(c,[[-16,y],[15,y-3]],'#9ba78b77',1);
      this._ellipse(c,0,-29,22,12,'#859181','#c3bd91');
      this._ellipse(c,0,-29,14,8,'#46585b','#b3985a');
      c.save();c.translate(0,-29);c.rotate(t.angle||0);const recoil=reduced?0:Math.max(0,t.recoil||0)*5;
      this._ellipse(c,-7,1,9,9,'#243d40','#b4a779');
      const length=25+level*3;this._poly(c,[[-8-recoil,-7],[length-recoil,-9],[length-recoil,9],[-8-recoil,7]],'#33494b','#8e9b84');
      c.fillStyle='#aa874a';c.fillRect(9-recoil,-9,5,18);if(level>1)c.fillRect(19-recoil,-9,3,18);
      this._ellipse(c,length-recoil,0,4,9,'#112b32','#c5b987');
      c.restore();
      this._ellipse(c,-17,4,4,4,'#263c3c','#809078');this._ellipse(c,-8,7,3.5,3.5,'#263c3c','#809078');
    } else if(t.type==='frost'){
      this._poly(c,[[-13,-6],[-10,-35],[10,-35],[13,-6]],'#436c76','#92c0c3');
      this._poly(c,[[-10,-35],[0,-44],[10,-35],[0,-28]],'#afdad1','#c7f8e7');
      for(let j=-1;j<=1;j++){
        const x=j*11,top=-48-(j===0?level*8:0);this._poly(c,[[x-6,-28],[x-7,top+10],[x,top],[x+7,top+10],[x+5,-28]],'#6fb8c8','#b3f4eb');this._poly(c,[[x,top],[x+7,top+10],[x+5,-28],[x,-28]],'#357d9c');
      }
      this._glow(c,0,-42,28,'#79e9e740');
      this._line(c,[[-9,-16],[0,-10],[9,-16]],'#a6ede4',1.5);
    } else {
      this._poly(c,[[-13,-5],[-9,-34],[9,-34],[14,-6]],'#5b6179','#aba3b6');
      this._poly(c,[[-9,-34],[0,-41],[9,-34],[0,-28]],'#b6a9b7','#e0cdad');
      const orbY=-49-(reduced?0:Math.sin(time*2)*2);
      this._glow(c,0,orbY,30+level*3,'#b08eff42');
      this._ellipse(c,0,orbY,10+level,10+level,'#906cbd','#e4c8ff');this._ellipse(c,-3,orbY-4,4,4,'#f3ddff');
      c.save();c.translate(0,orbY);c.rotate(reduced?-.5:time*.5);c.lineWidth=1.6;this._ellipse(c,0,0,20+level*2,7,null,'#d5b67c');c.restore();
      for(let j=-1;j<=1;j+=2){this._line(c,[[j*12,-5],[j*17,-27],[j*13,-40]],'#948394',3);this._ellipse(c,j*13,-40,2,2,'#e8bdff');}
      if(level===3)this._poly(c,[[-4,-23],[0,-28],[4,-23],[0,-18]],'#e6bcff');
    }
    // Upgrade tier pips are legible even on a small phone viewport.
    for(let i=0;i<level;i++){const x=(i-(level-1)/2)*8;this._ellipse(c,x,13,3.1,2.6,'#18352e','#c2b281');this._ellipse(c,x,12.6,1.7,1.5,selectedColor);}
    c.restore();
  }
  _enemy(c,e,time,reduced,simulationTime) {
    const boss=e.type==='boss', brute=e.type==='brute', wolf=e.type==='wolf';
    const size=boss?1.7:brute?1.3:1, angle=e.angle||0;
    const moving=!reduced, stride=moving?Math.sin(time*(wolf?13:8)+(Number(e.phase)||0)):0;
    const bob=moving?Math.abs(stride)*(wolf?1:1.6):0;
    const slow=e.slowUntil>simulationTime;
    c.save();c.translate(e.x,e.y);
    this._ellipse(c,2,4,(e.radius||11)*1.2,(e.radius||11)*.55,'#102a2daf');
    if(boss){this._glow(c,0,-12,38,'#f58c4630');c.lineWidth=1.5;this._ellipse(c,0,3,23,12,null,'#dd986866');}
    c.scale(size,size);
    if(wolf){
      c.rotate(angle);c.translate(0,-bob);
      for(const side of [-1,1])for(const front of [-1,1]){const x=front*6,y=side*5,step=stride*side*front*4;
        this._line(c,[[x,y],[x+step,y+side*4],[x+step+2,y+side*7]],'#a8a690',2.5);}
      this._line(c,[[-11,0],[-19,-3+stride*2]],'#868977',4);
      this._ellipse(c,0,0,13,6,'#8a8f82','#c3c5ab');
      this._ellipse(c,10,0,7,5,'#c0baa0');this._poly(c,[[8,-3],[8,-8],[13,-4]],'#8e8f7e');this._poly(c,[[8,3],[8,8],[13,4]],'#8e8f7e');
      this._poly(c,[[14,-3],[21,-1],[21,2],[14,4]],'#c9c4ac');this._ellipse(c,20,0,2,2,'#253637');this._ellipse(c,12,-3,1.4,1.4,'#ffbd65');
    } else {
      const armored=e.type==='armored', shaman=e.type==='shaman';
      const body=boss?'#754742':brute?'#706542':armored?'#667581':shaman?'#496e6a':'#9c6244';
      // Legs, knees and counter-swinging arms remain independently articulated.
      for(const side of [-1,1]){
        const swing=stride*side*4;this._line(c,[[side*4,-3],[side*4+swing*.3,3],[side*5+swing,8]],'#373d37',3.5);
        this._line(c,[[side*5+swing,8],[side*5+swing+3,8]],'#817d60',3);
      }
      c.translate(0,-bob);
      if(shaman||boss)this._poly(c,[[-7,-20],[7,-20],[10+stride,-2],[-10+stride,-2]],boss?'#502e38':'#325c56','#789081');
      this._ellipse(c,0,-12,8,11,body,'#171f24');
      if(armored||boss){this._poly(c,[[-8,-18],[0,-21],[8,-18],[6,-6],[0,-3],[-6,-6]],armored?'#89928a':'#855f51','#c6b993');this._line(c,[[-7,-11],[7,-11]],'#364b4b',2);}
      for(const side of [-1,1]){const swing=-stride*side*3;this._line(c,[[side*7,-17],[side*11,-11+swing],[side*11,-5+swing]],body,4);this._ellipse(c,side*11,-5+swing,2.3,2.8,'#c7a576');}
      this._ellipse(c,0,-25,6,6,shaman?'#b0c1a1':'#c4a17a','#403f37');
      if(shaman){this._poly(c,[[-8,-22],[0,-36],[8,-22]],'#46766b','#9fba8d');this._line(c,[[12,-1],[14,-35]],'#947955',2);this._glow(c,14,-36,12,'#92e2bd55');this._ellipse(c,14,-36,3,4,'#b3e6ac');}
      else if(armored||boss){this._ellipse(c,0,-28,7,5,'#808f8a','#c3c6a8');c.fillStyle='#223d40';c.fillRect(-5,-27,10,2);
        if(boss){this._poly(c,[[-7,-29],[-12,-40],[-4,-35],[0,-41],[4,-35],[12,-40],[7,-29]],'#bd9a58','#efc983');this._line(c,[[12,-4],[17,-31]],'#c9aa6d',3);this._poly(c,[[17,-31],[21,-37],[25,-20],[17,-23]],'#b5b2a0','#e8d5a4');}
        else{this._poly(c,[[10,-15],[19,-18],[21,-5],[14,1],[9,-5]],'#59686a','#c0b381');this._line(c,[[14,-14],[16,-4]],'#b5a465',2);}}
      else {this._poly(c,[[-7,-25],[-5,-32],[3,-33],[7,-28],[4,-25]],'#635347','#c08d54');this._line(c,[[11,-3],[13,-20]],'#c6bfa1',2);}
      const facing=Math.cos(angle);this._ellipse(c,facing*2,-24,1,1,'#192f31');
    }
    if(!reduced && e.hitFlash>0){c.globalAlpha=Math.min(.6,e.hitFlash*3);this._ellipse(c,0,wolf?0:-14,wolf?12:10,wolf?7:15,'#fff0b9');c.globalAlpha=1;}
    c.restore();
    if(slow){c.lineWidth=1.3;this._ellipse(c,e.x,e.y+4,(e.radius||10)+4,7,'#7bebef22','#9de5ed99');for(let i=0;i<3;i++)this._line(c,[[e.x-9+i*8,e.y],[e.x-10+i*8,e.y-8]],'#b2f4ec',1);}
    if(e.healedAt>0 && simulationTime-e.healedAt<.45){c.fillStyle='#9ee8a5';c.font='bold 15px Georgia';c.textAlign='center';c.fillText('+',e.x,e.y-45*size);}
    if(e.hp<e.maxHp || boss){const w=boss?50:brute?29:22,y=e.y-(wolf?15:39*size);
      c.fillStyle='#152b2ddb';c.fillRect(e.x-w/2-1,y-1,w+2,5);c.fillStyle=boss?'#eda15f':slow?'#8ce0dc':'#b9d17e';c.fillRect(e.x-w/2,y,w*Math.max(0,Math.min(1,e.hp/e.maxHp)),3);}
  }
  _projectile(c,p,reduced) {
    const color={archer:'#f6dd9b',cannon:'#efad68',frost:'#9de8ed',arcane:'#d8afff'}[p.type]||'#f7d28f';
    const progress=Math.max(0,Math.min(1,p.progress||0)),lift=Math.sin(progress*Math.PI)*(p.arc||0);
    // Engine p.y already includes the ballistic arc. Add only a diminishing
    // visual launch height; trail direction follows the actual arc tangent.
    const x=p.x,y=p.y-15*(1-progress),dx=p.toX-p.fromX,dy=p.toY-p.fromY-Math.cos(progress*Math.PI)*Math.PI*(p.arc||0)+15,angle=Math.atan2(dy,dx),trail=p.type==='cannon'?14:22;
    c.save();c.lineCap='round';
    if(!reduced){this._line(c,[[x-Math.cos(angle)*trail,y-Math.sin(angle)*trail],[x,y]],color+'77',p.type==='archer'?1:3);}
    if(p.type==='archer'){this._line(c,[[x-Math.cos(angle)*11,y-Math.sin(angle)*11],[x,y]],'#3e3d27',2);this._line(c,[[x-3*Math.cos(angle),y-3*Math.sin(angle)],[x,y]],color,2);}
    else if(p.type==='cannon'){this._ellipse(c,x+1,y+lift+10,4,2,'#20372c55');this._ellipse(c,x,y,4,4,'#273b3d','#e2aa69');}
    else{this._glow(c,x,y,13,color+'55');this._ellipse(c,x,y,3,3,color);this._ellipse(c,x-1,y-1,1.2,1.2,'#f5ffff');}
    c.restore();
  }
  _effect(c,e,reduced) {
    const t=Math.max(0,Math.min(1,(e.age||0)/(e.duration||.5))),radius=Math.max(4,e.radius||18),color=e.color||'#f8ca79';
    // Keep a readable, stationary footprint in reduced-motion mode. The effect
    // still fades out, but does not expand, fly upward or add a white hit flash.
    const expansion=reduced?1:t;
    c.save();c.globalAlpha=(1-t)*(reduced?.65:1);c.lineWidth=2;
    if(e.type==='meteor'){
      this._glow(c,e.x,e.y,radius*(reduced?.9:.6+t),'#ffbb5555');this._ellipse(c,e.x,e.y,radius*(.2+expansion*.8),radius*(.2+expansion*.8)*.65,'#dc763333','#ffe4a1');
      if(!reduced)for(let i=0;i<16;i++){const a=i*2.4,d=radius*Math.sqrt(t);this._line(c,[[e.x+Math.cos(a)*d*.7,e.y+Math.sin(a)*d*.7],[e.x+Math.cos(a)*d,e.y+Math.sin(a)*d]],i%2?'#ffd78c':'#eaa252',3*(1-t)+.5);}
    } else if(e.type==='explosion'||e.type==='splash'){
      this._ellipse(c,e.x,e.y,radius*(.2+expansion*.8),radius*(.2+expansion*.8)*.7,color+'44',color);this._glow(c,e.x,e.y,radius,'#ffd18c33');
    } else if(e.type==='frost'){
      this._ellipse(c,e.x,e.y,radius*(.3+expansion*.7),radius*(.3+expansion*.7)*.7,'#8cdde822','#bbf3ef');
      for(let i=0;i<8;i++){const a=i*Math.PI/4,d=radius*(.35+expansion*.5),x=e.x+Math.cos(a)*d,y=e.y+Math.sin(a)*d*.7;
        this._poly(c,[[x-3,y],[x-2,y-7],[x,y-12],[x+3,y-5],[x+2,y+1]],'#a6e4e7','#e0fff4');}
    } else if(e.type==='build'||e.type==='upgrade'||e.type==='sell'){
      this._ellipse(c,e.x,e.y,radius*(.6+expansion*.5),radius*(.4+expansion*.35),null,color);
      for(let i=0;i<6;i++){const a=i*Math.PI/3;this._ellipse(c,e.x+Math.cos(a)*20,e.y+Math.sin(a)*10-(reduced?0:t*30),1.5,2.4,color);}
    } else if(e.type==='heal'){this._ellipse(c,e.x,e.y,radius*(.6+expansion*.4),radius*.55,null,'#a4eab1');}
    else {this._ellipse(c,e.x,e.y,3+expansion*radius*.5,2+expansion*radius*.32,null,color);}
    if(e.text){c.globalAlpha=1-t*.7;c.font='bold 13px Georgia';c.textAlign='center';c.lineWidth=3;c.strokeStyle='#162e2e';c.strokeText(e.text,e.x,e.y-18-(reduced?0:t*25));c.fillStyle=color;c.fillText(e.text,e.x,e.y-18-(reduced?0:t*25));}
    c.restore();
  }
  _meteor(c,aim,radius,time) {
    c.save();c.lineWidth=1.8;this._ellipse(c,aim.x,aim.y,radius,radius,'#edaa5023','#ffd397cc');
    c.setLineDash([5,6]);c.lineDashOffset=-time*12;this._ellipse(c,aim.x,aim.y,radius*.8,radius*.8,null,'#ffd3a18c');c.setLineDash([]);
    this._line(c,[[aim.x-13,aim.y],[aim.x+13,aim.y]],'#ffe5b4',1.5);this._line(c,[[aim.x,aim.y-13],[aim.x,aim.y+13]],'#ffe5b4',1.5);
    for(let i=0;i<4;i++){const a=i*Math.PI/2,x=aim.x+Math.cos(a)*radius,y=aim.y+Math.sin(a)*radius;this._ellipse(c,x,y,3,3,'#ffe5b4');}
    c.restore();
  }
  dispose() {
    if(this.disposed)return;this.disposed=true;
    if(this.cache){this.cache.width=1;this.cache.height=1;}this.cache=null;this.ctx=null;this.engine=null;this.canvas=null;
  }
}
