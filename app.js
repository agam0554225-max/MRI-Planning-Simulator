let volumeId=null, shape=[1,1,1], pos=[0,0,0], drag=null;
const $=id=>document.getElementById(id);
const planes=[["sag","sagittal",2],["cor","coronal",1],["ax","axial",0]];
$("files").addEventListener("change",async e=>{
 const fs=[...e.target.files]; if(!fs.length)return;
 $("status").textContent="جارٍ فك ملف ZIP وتجهيز صور DICOM...";
 const data=new FormData(); fs.forEach(f=>data.append("files",f));
 try{const r=await fetch("/api/volume",{method:"POST",body:data});const j=await r.json();if(!r.ok)throw Error(j.detail||"Upload failed");
 volumeId=j.id;shape=j.shape;pos=shape.map(n=>Math.floor(n/2));
 $("study").textContent=`${j.series} · ${j.slices} slices`; $("status").textContent=`${j.patient} | ${shape.join(" × ")} voxels`;
 ["sagSlider","corSlider","axSlider"].forEach((id,i)=>{$(id).max=shape[[2,1,0][i]]-1;$(id).value=pos[[2,1,0][i]]});
 refresh();
 }catch(err){$("status").textContent=err.message;}
});
async function refresh(){if(!volumeId)return;
 for(const [id,plane,axis] of planes){const idx=pos[axis];$(id).src=`/api/slice/${volumeId}/${plane}/${idx}?t=${Date.now()}`;$(id+"idx").textContent=idx;drawOverlay(id+"over",id);}
}
function drawOverlay(cid,view){const c=$(cid),r=c.getBoundingClientRect(),d=window.devicePixelRatio||1;c.width=r.width*d;c.height=r.height*d;const x=c.getContext("2d");x.scale(d,d);x.strokeStyle="#f5a623";x.lineWidth=1.5;x.beginPath();let a=Number($("angle").value)*Math.PI/180, cx=r.width/2,cy=r.height/2,w=r.width*.58,h=r.height*.58;x.save();x.translate(cx,cy);x.rotate(a);x.strokeRect(-w/2,-h/2,w,h);x.restore();x.strokeStyle="#4aa4ff";x.beginPath();x.moveTo(cx,0);x.lineTo(cx,r.height);x.moveTo(0,cy);x.lineTo(r.width,cy);x.stroke();x.fillStyle="#f5a623";x.beginPath();x.arc(cx,cy,4,0,Math.PI*2);x.fill();}
["sagSlider","corSlider","axSlider"].forEach((id,i)=>$(id).addEventListener("input",e=>{if(!volumeId)return;pos[[2,1,0][i]]=+e.target.value;refresh()}));
$("angle").addEventListener("input",e=>{$("angval").textContent=e.target.value+"°";planes.forEach(([id])=>drawOverlay(id+"over",id))});
$("reset").onclick=()=>{if(!volumeId)return;pos=shape.map(n=>Math.floor(n/2));$("angle").value=0;$("angval").textContent="0°";["sagSlider","corSlider","axSlider"].forEach((id,i)=>$(id).value=pos[[2,1,0][i]]);refresh()};
planes.forEach(([id])=>{const c=$(id+"over");c.addEventListener("pointerdown",e=>{drag={x:e.clientX,y:e.clientY};c.setPointerCapture(e.pointerId)});c.addEventListener("pointermove",e=>{if(!drag||!volumeId)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag={x:e.clientX,y:e.clientY};const ax=id==="sag"?1:id==="cor"?0:0;pos[ax]=Math.max(0,Math.min(shape[ax]-1,pos[ax]+Math.round((dx-dy)*.15)));refresh()});c.addEventListener("pointerup",()=>drag=null)});
window.addEventListener("resize",()=>planes.forEach(([id])=>drawOverlay(id+"over",id)));