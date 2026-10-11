// Procedural renderer for trusted compatibility fixtures only.
class GameRenderer {
  constructor(canvas){this.canvas=canvas;}
  draw(s,now){const c=this.canvas.getContext('2d');c.fillStyle='#102527';c.fillRect(0,0,600,320);c.fillStyle='#f0d2a4';c.font='20px system-ui';c.fillText(s.phase,24,36);
    if(s.lamps){s.lamps.forEach((on,i)=>{c.fillStyle=on?'#ffc866':'#31565c';c.beginPath();c.arc(140+i*160,155,42,0,Math.PI*2);c.fill();});}
    else {c.fillStyle='#497665';c.fillRect(0,260,300,30);c.fillRect(390,260,210,30);const x=30+s.distance*5,y=235+s.y;c.fillStyle='#ffce82';c.fillRect(x-8,y-18,16,20);const gait=s.phase==='playing'?Math.sin(s.distance*.65)*6:0;c.strokeStyle='#ffce82';c.lineWidth=5;c.beginPath();c.moveTo(x,y);c.lineTo(x-6-gait,y+17);c.moveTo(x,y);c.lineTo(x+6+gait,y+17);c.stroke();}
  }
  dispose(){}
}
