// Trusted, deliberately small fixed-step platformer regression fixture.
class GameEngine {
  constructor({seed='runner'}={}){this.reset({seed});}
  reset({seed='runner'}={}){this.state={seed,phase:'menu',paused:false,distance:0,y:0,vy:0,jumps:0,time:0};this.events=[];this.sequence=0;return this.snapshot();}
  snapshot(){return JSON.parse(JSON.stringify(this.state));}
  act(action){
    const s=this.state;
    if(action.type==='start'&&s.phase==='menu')s.phase='playing';
    else if(action.type==='pause'&&s.phase==='playing')s.paused=!!action.value;
    else if(action.type==='jump'&&s.phase==='playing'&&!s.paused&&s.y===0){s.vy=-250;s.jumps++;this.events.push({id:String(++this.sequence),type:'jump'});}
    else if(action.type==='tick'){
      if(s.phase!=='playing'||s.paused)return {ok:true};
      s.time+=1/60;s.distance+=1;s.vy+=600/60;s.y=Math.min(0,s.y+s.vy/60);if(s.y===0)s.vy=0;
      if(s.distance>=50&&s.distance<=65&&s.y>-5)s.phase='lost';
      else if(s.distance>=100)s.phase='won';
    }else return {ok:false};
    return {ok:true};
  }
  drainEvents(){const result=this.events;this.events=[];return result;}
  dispose(){this.events=[];}
}
