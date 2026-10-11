// Internal CPU Canvas inspection. Not bundled with the game.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { createRequire } = require('node:module');
const req = createRequire('/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/__qa__.cjs');
const { createCanvas } = req('@napi-rs/canvas');
const sandbox = vm.createContext({console, devicePixelRatio:1});
vm.runInContext(fs.readFileSync(path.join(__dirname,'engine.js'),'utf8') + '\n' + fs.readFileSync(path.join(__dirname,'renderer.js'),'utf8') + '\nglobalThis.QA={AshenEngine,AshenRenderer};',sandbox);
const {AshenEngine,AshenRenderer} = sandbox.QA;
function setup(classId='warden') {
  const canvas=createCanvas(480,360);
  canvas.getBoundingClientRect=()=>({left:0,top:0,width:480,height:360});
  const renderer=new AshenRenderer(canvas);
  const engine=new AshenEngine({seed:'walk-qa',classId});
  const s=engine.state;
  s.tiles=Array.from({length:s.h},(_,y)=>Array.from({length:s.w},(_,x)=>x>0&&y>0&&x<s.w-1&&y<s.h-1?1:0));
  s.seen=s.tiles.map(row=>row.map(Boolean));s.visible=s.seen.map(row=>row.slice());
  s.player.x=20;s.player.y=14;s.enemies=[];s.features=[];s.items=[];s.events=[];s.stairs=null;
  renderer.draw(s,0);
  return {renderer,canvas,s};
}
function sprite(renderer,s) {
  const image=createCanvas(112,124),ctx=image.getContext('2d');
  ctx.fillStyle='#11191b';ctx.fillRect(0,0,112,124);
  const original=renderer.ctx;
  renderer.ctx=ctx;
  renderer._entity(s.player,{...renderer.positions.get('player'),x:0,y:0},108,true);
  renderer.ctx=original;
  return image;
}
const hash=image=>crypto.createHash('sha256').update(image.getContext('2d').getImageData(0,0,image.width,image.height).data).digest('hex');
const classes=['warden','rogue','mage'];
const directions=[['down',0,1],['right',1,0],['left',-1,0],['up',0,-1]];
const times=[0,48,96,144,192,240,288,384,640];
const contact=createCanvas(112+times.length*116,62+classes.length*directions.length*134);
const c=contact.getContext('2d');c.fillStyle='#081012';c.fillRect(0,0,contact.width,contact.height);
c.font='bold 17px sans-serif';c.fillStyle='#e5c79b';c.fillText('WALK CYCLE / procedural Canvas / 3 classes × 4 directions',16,23);
c.font='12px sans-serif';c.fillStyle='#9aacac';c.fillText('Two steps at 0 and 192 ms; last column is settled idle.',16,44);
for(let i=0;i<times.length;i++)c.fillText(times[i]+' ms',122+i*116,60);
let row=0;
for(const classId of classes)for(const [direction,dx,dy] of directions){
  const {renderer,s}=setup(classId);
  s.player.x+=dx;s.player.y+=dy;renderer.draw(s,0);
  const initialState=JSON.stringify(s);
  const poses=[];let col=0,settled;
  for(let t=0;t<=800;t+=16){
    if(t===192){s.player.x+=dx;s.player.y+=dy;}
    renderer.draw(s,t);
    if(times.includes(t)){
      const img=sprite(renderer,s);c.drawImage(img,112+col*116,66+row*134);
      poses.push(hash(img));col++;
    }
    if(t===640)settled=hash(sprite(renderer,s));
    if(t===800)assert.equal(hash(sprite(renderer,s)),settled,classId+'/'+direction+' should return to a still pose');
  }
  assert(new Set(poses.slice(0,-1)).size>=6,'Walking must produce visibly different rendered frames');
  c.fillStyle='#c5c4b3';c.font='12px sans-serif';c.fillText(classId,10,98+row*134);c.fillText(direction,10,116+row*134);
  const before=JSON.stringify(s);renderer.draw(s,816);assert.equal(JSON.stringify(s),before,'Renderer changed game rules/state');
  const tr=renderer.transform,p=s.player;
  const hit=renderer.hitTest(tr.x+(p.x+.5)*tr.tile,tr.y+(p.y+.5)*tr.tile);
  assert.equal(hit.x,p.x);assert.equal(hit.y,p.y);
  row++;
}
fs.writeFileSync(path.join(__dirname,'qa-walk-phases.png'),contact.toBuffer('image/png'));

// Exercise actual render options: pause, accessibility mode, map and resets.
{
  const {renderer,s}=setup();s.player.x++;
  for(let t=16;t<=112;t+=16)renderer.draw(s,t);
  const paused=hash(sprite(renderer,s));
  for(let t=128;t<=256;t+=16)renderer.draw(s,t,{paused:true});
  assert.equal(hash(sprite(renderer,s)),paused,'Pause must freeze the current pose');
  renderer.draw(s,272,{reduceMotion:true});const calm=hash(sprite(renderer,s));
  for(let t=288;t<=400;t+=16)renderer.draw(s,t,{reduceMotion:true});
  assert.equal(hash(sprite(renderer,s)),calm,'Reduced motion must disable the gait');
  renderer.draw(s,416,{mapMode:true});renderer.draw(s,432);
  assert.equal(hash(sprite(renderer,s)),calm,'Map must not replay an old step');
  renderer.reset();renderer.draw(s,0);const reset=hash(sprite(renderer,s));renderer.draw(s,80);
  assert.equal(hash(sprite(renderer,s)),reset,'Load/reset should not start walking');
  s.floor++;renderer.draw(s,96);const floor=hash(sprite(renderer,s));renderer.draw(s,176);
  assert.equal(hash(sprite(renderer,s)),floor,'New floor should not start walking');
}
console.log('PASS: 3 classes × 4 directions, distinct walking frames, still idle, pause, reduced motion, map/reset/floor, state immutability and hit testing. CPU Canvas only.');
