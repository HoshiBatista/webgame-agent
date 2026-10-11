/* Emberwatch simulation. Damage resolves immediately when fired; projectiles are
   visual tracers only and never apply damage a second time. No browser APIs. */
const EngineRoute = [[-35,145],[150,145],[245,245],[435,245],[505,120],[710,120],[800,230],[755,395],[540,395],[430,515],[660,515],[805,530],[960,465],[1035,465]];
const EnginePads = [[110,225],[225,135],[285,335],[380,165],[515,275],[590,195],[705,295],[875,225],[860,380],[665,445],[430,410],[380,545],[575,590],[800,590]];
const EngineTowerData = {
  archer: {name:'Дозорная башня',subtitle:'Точные стрелы',description:'Быстро поражает одну цель. Надёжна против быстрых налётчиков.',cost:90,color:'#d9b25d',maxLevel:3,
    levels:[[18,160,.62,0,0,0,70],[31,172,.58,0,0,0,115],[49,185,.53,0,0,0,null]]},
  cannon: {name:'Бастион',subtitle:'Урон по площади',description:'Тяжёлые снаряды разбивают плотные группы. Медленная перезарядка.',cost:125,color:'#ec8654',maxLevel:3,
    levels:[[42,174,1.8,0,65,0,100],[74,184,1.7,0,75,0,155],[115,195,1.6,0,86,0,null]]},
  frost: {name:'Ледяной обелиск',subtitle:'Контроль пути',description:'Замедляет небольшой отряд, давая другим башням больше времени. Вождь сопротивляется холоду.',cost:105,color:'#7bd4e0',maxLevel:3,
    levels:[[10,145,1.15,.62,35,0,90],[16,156,1.05,.48,46,0,130],[24,170,.95,.35,55,0,null]]},
  arcane: {name:'Руническая башня',subtitle:'Цепная магия',description:'Магия игнорирует броню и перескакивает между соседними врагами.',cost:150,color:'#bd9be5',maxLevel:3,
    levels:[[27,150,1.2,0,0,2,125],[43,166,1.05,0,0,3,175],[65,178,.95,0,0,4,null]]}
};
const EngineEnemyData = {
  raider:{name:'Налётчик',color:'#c67856',hp:80,speed:57,armor:0,radius:12,bounty:7,leak:1},
  wolf:{name:'Пепельный волк',color:'#b8b9a6',hp:61,speed:94,armor:0,radius:11,bounty:7,leak:1},
  armored:{name:'Щитоносец',color:'#879d9a',hp:205,speed:43,armor:12,radius:15,bounty:14,leak:2},
  shaman:{name:'Шаман тумана',color:'#b49fcc',hp:150,speed:49,armor:2,radius:13,bounty:16,leak:2},
  brute:{name:'Каменный громила',color:'#a88069',hp:470,speed:33,armor:8,radius:19,bounty:25,leak:3},
  boss:{name:'Король Пепла',color:'#e8a462',hp:3500,speed:29,armor:14,radius:27,bounty:150,leak:12}
};
const EngineDifficultyData = {
  story:{name:'Легенда',description:'Спокойная оборона: враги −24% здоровья, −8% скорости; 30 жизней и 340 золота.',hp:.76,speed:.92,reward:1.08,lives:30,gold:340},
  normal:{name:'Дозор',description:'Сбалансированный вызов: 20 жизней, 260 золота. Сочетайте башни и метеор.',hp:1,speed:1,reward:1,lives:20,gold:260},
  veteran:{name:'Ветеран',description:'Враги +30% здоровья, +10% скорости; доход −8%, 16 жизней и 230 золота.',hp:1.3,speed:1.1,reward:.92,lives:16,gold:230}
};
const EngineWaves = [
  ['Первые искры','Разведчики проверяют дорогу. Начните с двух разных башен.',[['raider',10]]],
  ['Волчья тропа','Быстрые волки прорываются между налётчиками.',[['raider',10],['wolf',6]]],
  ['Железный строй','Щитоносцы поглощают часть физического урона. Магия игнорирует броню.',[['raider',10],['armored',5]]],
  ['Шёпот тумана','Шаманы лечат соседей. Сосредоточьте огонь на плотных группах.',[['wolf',16],['raider',10],['shaman',2]]],
  ['Тяжёлая поступь','Бронированный отряд требует улучшений и замедления.',[['armored',10],['raider',10]]],
  ['Багровый прилив','Много лёгких целей и целители: настало время бастионов.',[['raider',16],['shaman',4],['wolf',14]]],
  ['Каменная клятва','Громилы наносят крепости три повреждения при прорыве.',[['armored',12],['brute',3],['wolf',10]]],
  ['Ночная охота','Длинная быстрая волна. Сохраните метеор для опасного скопления.',[['wolf',22],['shaman',5],['raider',14]]],
  ['Осада бастиона','Тяжёлые бойцы под прикрытием шаманов.',[['armored',14],['brute',5],['shaman',3]]],
  ['Разлом небес','Разнородный штурм: стройте защиту вдоль всего изгиба дороги.',[['wolf',24],['armored',12],['shaman',6]]],
  ['Последний рубеж','Последний крупный отряд перед вождём. Доведите ключевые башни до третьего уровня.',[['brute',8],['armored',16],['raider',18],['shaman',5]]],
  ['Король Пепла','Вождь идёт в середине своего войска. Его прорыв отнимает двенадцать жизней.',[['boss',1],['brute',7],['armored',15],['wolf',24],['shaman',6]]]
];

class GameEngine {
  static TOWERS = Object.freeze(Object.fromEntries(Object.entries(EngineTowerData).map(([id,t])=>[id,Object.freeze({name:t.name,subtitle:t.subtitle,description:t.description,cost:t.cost,color:t.color,maxLevel:t.maxLevel})])));
  static ENEMIES = Object.freeze(Object.fromEntries(Object.entries(EngineEnemyData).map(([id,e])=>[id,Object.freeze({name:e.name,color:e.color})])));
  static DIFFICULTIES = Object.freeze(Object.fromEntries(Object.entries(EngineDifficultyData).map(([id,d])=>[id,Object.freeze({...d})])));

  constructor({difficulty='normal',seed=20261010}={}) {
    this._eventId=0; this._events=[];
    this.reset({difficulty,seed});
  }
  reset({difficulty=this.state?.difficulty||'normal',seed=this.state?.seed??20261010}={}) {
    if(!Object.hasOwn(EngineDifficultyData,difficulty)) difficulty='normal';
    if(!Number.isSafeInteger(seed)) seed=20261010;
    seed=seed>>>0;
    const config=EngineDifficultyData[difficulty];
    this._rng=seed||0x6d2b79f5; this._id=0; this._events=[]; this._spawnQueue=[]; this._spawnClock=0;
    const path=EngineRoute.map(([x,y])=>({x,y}));
    this._segments=[]; let length=0;
    for(let i=1;i<path.length;i++) {
      const a=path[i-1],b=path[i],distance=Math.hypot(b.x-a.x,b.y-a.y);
      this._segments.push({a,b,start:length,length:distance,angle:Math.atan2(b.y-a.y,b.x-a.x)}); length+=distance;
    }
    this.state={version:1,seed,difficulty,phase:'menu',paused:false,width:1000,height:640,time:0,wave:0,totalWaves:12,
      gold:config.gold,lives:config.lives,maxLives:config.lives,kills:0,score:0,selectedPad:null,path,pathLength:length,
      pads:EnginePads.map(([x,y],i)=>({id:'P'+(i+1),x,y})),towers:[],enemies:[],projectiles:[],effects:[],
      waveRemaining:0,spawnRemaining:0,meteor:{cooldown:0,maxCooldown:26,radius:90},
      stats:{goldEarned:config.gold,goldSpent:0,damageDealt:0,leaks:0,meteorsUsed:0,towersBuilt:0}};
    return this.state;
  }
  getState(){return this.state;}
  snapshot(){return JSON.parse(JSON.stringify(this.state));}
  drainEvents(){const events=this._events;this._events=[];return events;}
  _random(){let x=this._rng;x^=x<<13;x^=x>>>17;x^=x<<5;this._rng=x>>>0;return this._rng/4294967296;}
  _emit(type,data={}){this._events.push({id:String(++this._eventId),type,...data});if(this._events.length>512)this._events.splice(0,this._events.length-512);}
  _effect(type,x,y,radius,color,text){const s=this.state;s.effects.push({id:'fx'+(++this._id),type,x,y,age:0,duration:type==='meteor'?1.1:.55,radius,color,...(text?{text}:{})});if(s.effects.length>160)s.effects.splice(0,s.effects.length-160);}
  _reject(reason){return {ok:false,reason};}
  _pad(id){return this.state.pads.find(p=>p.id===id);}
  _tower(id){return this.state.towers.find(t=>t.padId===id);}
  _cost(type,level){let cost=EngineTowerData[type].cost;for(let i=1;i<level;i++)cost+=EngineTowerData[type].levels[i-1][6];return cost;}
  getTowerStats(type,level=1){
    if(!Object.hasOwn(EngineTowerData,type)||!Number.isInteger(level)||level<1||level>3)return null;
    const t=EngineTowerData[type],v=t.levels[level-1];
    return {damage:v[0],range:v[1],interval:v[2],slow:v[3],splash:v[4],chain:v[5],cost:t.cost,upgradeCost:v[6]};
  }
  getWaveInfo(number){
    if(!Number.isInteger(number)||number<1||number>12)return null;
    const wave=EngineWaves[number-1],groups=wave[2].map(([type,count])=>({type,count}));
    return {number,name:wave[0],description:wave[1],groups,total:groups.reduce((sum,g)=>sum+g.count,0),boss:groups.some(g=>g.type==='boss'),reward:Math.round((35+number*6)*EngineDifficultyData[this.state.difficulty].reward)};
  }
  act(action){
    if(!action||typeof action!=='object'||typeof action.type!=='string')return this._reject('Неизвестное действие.');
    if(action.type==='tick'){this.update(1/60);return {ok:true};}
    const s=this.state;
    if(action.type==='select'){
      if(action.padId!==null&&!this._pad(action.padId))return this._reject('Площадка не найдена.');
      s.selectedPad=action.padId;return {ok:true};
    }
    if(action.type==='reset'){
      if(action.difficulty!==undefined&&!Object.hasOwn(EngineDifficultyData,action.difficulty))return this._reject('Неизвестная сложность.');
      if(action.seed!==undefined&&!Number.isSafeInteger(action.seed))return this._reject('Некорректное зерно мира.');
      this.reset(action);return {ok:true};
    }
    if(action.type==='start'){
      if(s.phase!=='menu')return this._reject('Оборона уже началась.');
      s.phase='build';this._emit('start',{text:'Дозор начат'});return {ok:true};
    }
    if(action.type==='pause'){
      if(typeof action.value!=='boolean'||!['build','wave'].includes(s.phase))return this._reject('Сейчас нельзя изменить паузу.');
      if(s.paused!==action.value){s.paused=action.value;this._emit('pause',{value:action.value?1:0});}return {ok:true};
    }
    if(!['build','wave'].includes(s.phase))return this._reject('Начните новую оборону.');
    if(s.paused)return this._reject('Снимите паузу, чтобы продолжить.');
    if(action.type==='wave'){
      if(s.phase!=='build')return this._reject('Сначала отбейте текущую волну.');
      this._startWave();return {ok:true};
    }
    if(action.type==='meteor'){
      if(s.phase!=='wave')return this._reject('Метеор доступен во время штурма.');
      if(s.meteor.cooldown>0)return this._reject('Метеор ещё восстанавливается.');
      if(!Number.isFinite(action.x)||!Number.isFinite(action.y)||action.x<0||action.x>1000||action.y<0||action.y>640)return this._reject('Выберите цель на поле.');
      s.meteor.cooldown=s.meteor.maxCooldown;s.stats.meteorsUsed++;
      const damage=180+s.wave*22;
      for(const enemy of [...s.enemies])if(enemy.hp>0&&!enemy._escaped&&Math.hypot(enemy.x-action.x,enemy.y-action.y)<=s.meteor.radius+enemy.radius)this._damage(enemy,damage,null,true);
      this._effect('meteor',action.x,action.y,s.meteor.radius,'#ffd58c');this._emit('meteor',{x:action.x,y:action.y,value:damage});
      this._cleanupEnemies();this._checkWaveEnd();return {ok:true};
    }
    const pad=this._pad(action.padId);
    if(!pad)return this._reject('Выберите строительную площадку.');
    const tower=this._tower(pad.id);
    if(action.type==='build'){
      if(!Object.hasOwn(EngineTowerData,action.towerType))return this._reject('Неизвестная башня.');
      if(tower)return this._reject('Эта площадка уже занята.');
      const config=EngineTowerData[action.towerType];
      if(s.gold<config.cost)return this._reject('Недостаточно золота для строительства.');
      s.gold-=config.cost;s.stats.goldSpent+=config.cost;s.stats.towersBuilt++;
      s.towers.push({id:'tower'+(++this._id),padId:pad.id,type:action.towerType,level:1,x:pad.x,y:pad.y,angle:-Math.PI/2,cooldown:0,recoil:0,spent:config.cost,targetMode:'first',kills:0});
      this._effect('build',pad.x,pad.y,40,config.color);this._emit('build',{x:pad.x,y:pad.y,towerType:action.towerType,value:config.cost});return {ok:true};
    }
    if(!tower)return this._reject('На этой площадке нет башни.');
    if(action.type==='upgrade'){
      const stats=this.getTowerStats(tower.type,tower.level);
      if(stats.upgradeCost===null)return this._reject('Башня уже достигла третьего уровня.');
      if(s.gold<stats.upgradeCost)return this._reject('Недостаточно золота для улучшения.');
      s.gold-=stats.upgradeCost;s.stats.goldSpent+=stats.upgradeCost;tower.spent+=stats.upgradeCost;tower.level++;
      tower.cooldown=Math.min(tower.cooldown,this.getTowerStats(tower.type,tower.level).interval);
      this._effect('upgrade',tower.x,tower.y,46,EngineTowerData[tower.type].color);this._emit('upgrade',{x:tower.x,y:tower.y,towerType:tower.type,value:tower.level});return {ok:true};
    }
    if(action.type==='sell'){
      const refund=Math.floor(tower.spent*70/100);s.gold+=refund;s.towers=s.towers.filter(t=>t!==tower);
      this._emit('sell',{x:tower.x,y:tower.y,towerType:tower.type,value:refund});this._effect('sell',tower.x,tower.y,30,'#dbb871');return {ok:true};
    }
    if(action.type==='target'){
      if(!['first','strong','last'].includes(action.mode))return this._reject('Неизвестный режим прицеливания.');
      tower.targetMode=action.mode;return {ok:true};
    }
    return this._reject('Неизвестное действие.');
  }
  _startWave(){
    const s=this.state;s.wave++;s.phase='wave';s.paused=false;
    const info=this.getWaveInfo(s.wave),groups=info.groups.filter(g=>g.type!=='boss').map(g=>({...g}));
    const queue=[];
    while(groups.some(g=>g.count>0))for(const g of groups)if(g.count>0){queue.push(g.type);g.count--;}
    if(info.boss)queue.splice(Math.floor(queue.length*.3),0,'boss');
    this._spawnQueue=queue;this._spawnClock=.6;s.spawnRemaining=queue.length;s.waveRemaining=queue.length;
    s.meteor.cooldown=0;for(const t of s.towers)t.cooldown=0;
    this._emit('wave-start',{value:s.wave,text:info.name});
  }
  _point(distance){
    const segment=this._segments.find(p=>distance<=p.start+p.length)||this._segments[this._segments.length-1];
    const progress=Math.max(0,Math.min(1,(distance-segment.start)/segment.length));
    return {x:segment.a.x+(segment.b.x-segment.a.x)*progress,y:segment.a.y+(segment.b.y-segment.a.y)*progress,angle:segment.angle};
  }
  _spawn(type){
    const s=this.state,c=EngineEnemyData[type],d=EngineDifficultyData[s.difficulty],scale=1+(s.wave-1)*.24;
    const hp=Math.round(c.hp*scale*d.hp*(.96+this._random()*.08));
    s.enemies.push({id:'enemy'+(++this._id),type,...this._point(0),distance:0,hp,maxHp:hp,speed:c.speed*d.speed,armor:c.armor,radius:c.radius,slowUntil:0,slowFactor:1,hitFlash:0,phase:this._random()*Math.PI*2,healedAt:-10,_healClock:3.1+this._random()});
  }
  _damage(enemy,amount,tower,ignoreArmor=false){
    // Movement resolves before tower fire; an escape is terminal even before cleanup.
    if(enemy.hp<=0||enemy._escaped)return;
    const s=this.state,damage=Math.min(enemy.hp,Math.max(1,amount-(ignoreArmor?0:enemy.armor)));
    enemy.hp=Math.max(0,enemy.hp-damage);enemy.hitFlash=.14;s.stats.damageDealt+=damage;
    this._emit('hit',{x:enemy.x,y:enemy.y,value:Math.round(damage),enemyType:enemy.type,towerType:tower?.type});
    if(enemy.hp===0){
      const bounty=Math.max(1,Math.round(EngineEnemyData[enemy.type].bounty*EngineDifficultyData[s.difficulty].reward));
      s.gold+=bounty;s.stats.goldEarned+=bounty;s.kills++;s.score+=bounty*10;if(tower)tower.kills++;
      this._emit('kill',{x:enemy.x,y:enemy.y,value:bounty,enemyType:enemy.type});
      this._effect('death',enemy.x,enemy.y,enemy.radius+10,EngineEnemyData[enemy.type].color);
    }
  }
  _trace(tower,target,from){
    const s=this.state,origin=from||tower,duration=tower.type==='cannon'?.38:tower.type==='archer'?.16:.12;
    s.projectiles.push({id:'shot'+(++this._id),type:tower.type,x:origin.x,y:origin.y,fromX:origin.x,fromY:origin.y,toX:target.x,toY:target.y,progress:0,duration,arc:tower.type==='cannon'?42:0});
    if(s.projectiles.length>140)s.projectiles.splice(0,s.projectiles.length-140);
  }
  _fire(tower,target,stats){
    const s=this.state;tower.angle=Math.atan2(target.y-tower.y,target.x-tower.x);tower.recoil=1;tower.cooldown=stats.interval;
    this._emit('shot',{x:tower.x,y:tower.y,towerType:tower.type});this._trace(tower,target);
    if(tower.type==='cannon'||tower.type==='frost'){
      const targets=s.enemies.filter(e=>e.hp>0&&!e._escaped&&Math.hypot(e.x-target.x,e.y-target.y)<=stats.splash+e.radius);
      for(const enemy of targets){
        if(tower.type==='frost'){
          const factor=enemy.type==='boss'?1-(1-stats.slow)*.45:stats.slow;
          enemy.slowFactor=enemy.slowUntil>s.time?Math.min(enemy.slowFactor,factor):factor;
          enemy.slowUntil=Math.max(enemy.slowUntil,s.time+2.3);
        }
        this._damage(enemy,stats.damage,tower);
      }
      this._effect(tower.type==='cannon'?'explosion':'frost',target.x,target.y,stats.splash,EngineTowerData[tower.type].color);
    }else if(tower.type==='arcane'){
      const hit=new Set();let current=target,previous=tower;
      for(let n=0;n<stats.chain&&current;n++){
        if(n>0)this._trace(tower,current,previous);
        hit.add(current.id);this._damage(current,stats.damage*Math.pow(.78,n),tower,true);previous=current;
        let next=null,best=105;
        for(const enemy of s.enemies)if(enemy.hp>0&&!enemy._escaped&&!hit.has(enemy.id)){
          const distance=Math.hypot(enemy.x-current.x,enemy.y-current.y);if(distance<best){best=distance;next=enemy;}
        }
        current=next;
      }
    }else this._damage(target,stats.damage,tower);
  }
  _cleanupEnemies(){this.state.enemies=this.state.enemies.filter(e=>e.hp>0&&!e._escaped);this.state.waveRemaining=this.state.spawnRemaining+this.state.enemies.length;}
  _checkWaveEnd(){
    const s=this.state;
    if(s.phase!=='wave'||s.spawnRemaining>0||s.enemies.some(e=>e.hp>0&&!e._escaped))return;
    const reward=this.getWaveInfo(s.wave).reward;s.gold+=reward;s.stats.goldEarned+=reward;s.score+=s.wave*100;
    s.phase=s.wave===12?'won':'build';s.waveRemaining=0;s.meteor.cooldown=0;
    this._emit('wave-complete',{value:s.wave,text:'Доход за волну: '+reward});
    if(s.phase==='won'){s.score+=s.lives*200;this._emit('win',{value:s.score,text:'Долина защищена'});this._effect('win',945,455,180,'#ffe0a0');}
  }
  update(dt){
    if(!Number.isFinite(dt)||dt<=0)return;
    const s=this.state;if(s.paused||!['build','wave'].includes(s.phase))return;
    dt=Math.min(.1,dt);s.time+=dt;
    for(const e of s.effects)e.age+=dt;s.effects=s.effects.filter(e=>e.age<e.duration);
    for(const p of s.projectiles){p.progress=Math.min(1,p.progress+dt/p.duration);p.x=p.fromX+(p.toX-p.fromX)*p.progress;p.y=p.fromY+(p.toY-p.fromY)*p.progress-Math.sin(p.progress*Math.PI)*p.arc;}
    s.projectiles=s.projectiles.filter(p=>p.progress<1);
    for(const tower of s.towers)tower.recoil=Math.max(0,tower.recoil-dt*6);
    if(s.phase!=='wave')return;
    s.meteor.cooldown=Math.max(0,s.meteor.cooldown-dt);
    this._spawnClock-=dt;
    while(this._spawnQueue.length&&this._spawnClock<=0){
      this._spawn(this._spawnQueue.shift());s.spawnRemaining=this._spawnQueue.length;
      this._spawnClock+=Math.max(.37,1.06-s.wave*.043)*(0.91+this._random()*.18);
    }
    for(const enemy of s.enemies){
      if(enemy.hp<=0)continue;
      enemy.hitFlash=Math.max(0,enemy.hitFlash-dt);
      if(enemy.slowUntil<=s.time)enemy.slowFactor=1;
      enemy.distance+=enemy.speed*Math.max(.2,Math.min(1,enemy.slowFactor))*dt;
      Object.assign(enemy,this._point(enemy.distance));
      if(enemy.distance>=s.pathLength){
        const damage=EngineEnemyData[enemy.type].leak;enemy._escaped=true;s.stats.leaks++;s.lives=Math.max(0,s.lives-damage);
        this._emit('leak',{x:945,y:455,value:damage,enemyType:enemy.type});this._effect('leak',945,455,60,'#ed775f');
        if(s.lives===0){s.phase='lost';s.waveRemaining=s.spawnRemaining+s.enemies.filter(e=>e.hp>0&&!e._escaped).length;this._emit('lose',{value:s.wave,text:'Огонь дозора погас'});return;}
        continue;
      }
      if(enemy.type==='shaman'){
        enemy._healClock-=dt;
        if(enemy._healClock<=0){
          enemy._healClock+=4.2;let healed=false;
          for(const other of s.enemies)if(other.hp>0&&!other._escaped&&other.id!==enemy.id&&Math.hypot(other.x-enemy.x,other.y-enemy.y)<=100){
            const amount=Math.min(other.maxHp-other.hp,18+s.wave*3);if(amount>0){other.hp+=amount;other.healedAt=s.time;healed=true;}
          }
          if(healed)this._effect('heal',enemy.x,enemy.y,100,'#91d5a4');
        }
      }
    }
    for(const tower of s.towers){
      tower.cooldown=Math.max(0,tower.cooldown-dt);if(tower.cooldown>0)continue;
      const stats=this.getTowerStats(tower.type,tower.level);let target=null;
      for(const enemy of s.enemies){
        if(enemy.hp<=0||enemy._escaped||Math.hypot(enemy.x-tower.x,enemy.y-tower.y)>stats.range+enemy.radius)continue;
        if(!target||(tower.targetMode==='first'&&enemy.distance>target.distance)||(tower.targetMode==='last'&&enemy.distance<target.distance)||(tower.targetMode==='strong'&&(enemy.hp>target.hp||(enemy.hp===target.hp&&enemy.distance>target.distance))))target=enemy;
      }
      if(target)this._fire(tower,target,stats);
    }
    this._cleanupEnemies();this._checkWaveEnd();
  }
  exportSave(){
    const s=this.state;if(s.phase!=='build')return null;
    return JSON.parse(JSON.stringify({version:1,seed:s.seed,difficulty:s.difficulty,wave:s.wave,gold:s.gold,lives:s.lives,kills:s.kills,score:s.score,time:s.time,stats:s.stats,
      towers:s.towers.map(({padId,type,level,spent,targetMode,kills})=>({padId,type,level,spent,targetMode,kills})),rng:this._rng,eventId:this._eventId,entityId:this._id}));
  }
  loadSave(data){
    const invalid=()=>this._reject('Сохранение повреждено или относится к другой версии.');
    try{
      if(!data||typeof data!=='object'||Array.isArray(data)||data.version!==1||!Object.hasOwn(EngineDifficultyData,data.difficulty))return invalid();
      const integer=(v,min,max)=>Number.isSafeInteger(v)&&v>=min&&v<=max;
      if(!integer(data.seed,0,4294967295)||!integer(data.wave,0,11)||!integer(data.gold,0,1000000)||!integer(data.lives,1,EngineDifficultyData[data.difficulty].lives)||!integer(data.kills,0,100000)||!integer(data.score,0,100000000)||!Number.isFinite(data.time)||data.time<0||data.time>10000000||!integer(data.rng,1,4294967295)||!integer(data.eventId,0,1000000000)||!integer(data.entityId,0,1000000000))return invalid();
      if(!data.stats||typeof data.stats!=='object'||!Array.isArray(data.towers)||data.towers.length>14)return invalid();
      const expected=['goldEarned','goldSpent','damageDealt','leaks','meteorsUsed','towersBuilt'];
      if(Object.keys(data.stats).length!==expected.length||expected.some(k=>!Number.isFinite(data.stats[k])||data.stats[k]<0||data.stats[k]>100000000))return invalid();
      if(expected.filter(k=>k!=='damageDealt').some(k=>!Number.isInteger(data.stats[k])))return invalid();
      const completedEnemies=EngineWaves.slice(0,data.wave).reduce((sum,wave)=>sum+wave[2].reduce((n,group)=>n+group[1],0),0);
      const lostLives=EngineDifficultyData[data.difficulty].lives-data.lives;
      if(data.kills+data.stats.leaks!==completedEnemies||lostLives<data.stats.leaks||lostLives>data.stats.leaks*12||data.gold>data.stats.goldEarned||data.stats.towersBuilt<data.towers.length)return invalid();
      const pads=new Set();
      for(const t of data.towers){
        if(!t||typeof t!=='object'||!this._pad(t.padId)||pads.has(t.padId)||!Object.hasOwn(EngineTowerData,t.type)||!integer(t.level,1,3)||t.spent!==this._cost(t.type,t.level)||!integer(t.kills,0,data.kills)||!['first','strong','last'].includes(t.targetMode))return invalid();
        pads.add(t.padId);
      }
      if(data.towers.reduce((n,t)=>n+t.kills,0)>data.kills)return invalid();
      if(data.towers.reduce((n,t)=>n+t.spent,0)>data.stats.goldSpent)return invalid();
      const candidate=new GameEngine({difficulty:data.difficulty,seed:data.seed}),s=candidate.state;
      Object.assign(s,{phase:'build',wave:data.wave,gold:data.gold,lives:data.lives,kills:data.kills,score:data.score,time:data.time,stats:{...data.stats}});
      candidate._rng=data.rng;candidate._id=data.entityId;
      for(const tower of data.towers){const pad=candidate._pad(tower.padId);s.towers.push({...tower,id:'tower'+(++candidate._id),x:pad.x,y:pad.y,angle:-Math.PI/2,cooldown:0,recoil:0});}
      const nextEvent=Math.max(this._eventId,data.eventId);
      this.state=s;this._segments=candidate._segments;this._rng=candidate._rng;this._id=candidate._id;this._spawnQueue=[];this._spawnClock=0;this._events=[];this._eventId=nextEvent;
      this._emit('start',{text:'Дозор продолжен'});return {ok:true};
    }catch(_){return invalid();}
  }
}
