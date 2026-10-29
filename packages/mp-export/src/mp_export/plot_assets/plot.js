"use strict";
(() => {
  const svg = document.getElementById("plot");
  const original = svg.getAttribute("viewBox");
  const view = () => svg.getAttribute("viewBox").split(/\s+/).map(Number);
  const scale = () => {
    const box = view(), rect = svg.getBoundingClientRect();
    const pixelsPerFoot = Math.min(rect.width / box[2], rect.height / box[3]);
    const wanted = 100 / pixelsPerFoot;
    const power = 10 ** Math.floor(Math.log10(wanted));
    const length = [1, 2, 5, 10].map(n => n * power).find(n => n >= wanted);
    document.getElementById("plot-scale").textContent = `${Number(length.toPrecision(3))} ft = ${(length * pixelsPerFoot).toFixed(0)} screen px · local feet`;
  };
  const setView = values => { if (values.every(Number.isFinite) && values[2] > 1e-9 && values[3] > 1e-9) { svg.setAttribute("viewBox", values.join(" ")); scale(); } };
  const zoom = factor => { const [x,y,w,h] = view(); setView([x+w*(1-factor)/2,y+h*(1-factor)/2,w*factor,h*factor]); };
  document.getElementById("plot-zoom-in").onclick = () => zoom(0.8);
  document.getElementById("plot-zoom-out").onclick = () => zoom(1.25);
  for (const id of ["plot-fit", "plot-reset"]) document.getElementById(id).onclick = () => { svg.setAttribute("viewBox", original); scale(); };
  document.getElementById("plot-labels").onchange = event => svg.classList.toggle("label-hidden", !event.target.checked);
  const select = id => {
    let selected;
    document.querySelectorAll("[data-call-row]").forEach(row => { const active = row.dataset.callRow === id; row.classList.toggle("selected", active); if (active) selected = row; });
    document.querySelectorAll("[data-plot-call], [data-source-call]").forEach(node => { const active = (node.dataset.plotCall || node.dataset.sourceCall) === id; node.classList.toggle("selected", active); node.setAttribute("aria-pressed", String(active)); });
    if (selected) {
      document.getElementById("source-status").textContent = `Selected ${id}: ${selected.querySelector("blockquote").textContent}`;
      selected.scrollIntoView({block:"nearest", inline:"nearest"});
    }
  };
  document.querySelectorAll("[data-plot-call], [data-source-call]").forEach(node => {
    const activate = () => select(node.dataset.plotCall || node.dataset.sourceCall);
    node.addEventListener("click", activate);
    node.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.stopPropagation(); activate(); } });
  });
  svg.addEventListener("keydown", event => {
    const [x,y,w,h] = view();
    const pans = {ArrowLeft:[-w*.1,0],ArrowRight:[w*.1,0],ArrowUp:[0,-h*.1],ArrowDown:[0,h*.1]};
    if (pans[event.key]) { event.preventDefault(); setView([x+pans[event.key][0],y+pans[event.key][1],w,h]); }
    else if (event.key === "+" || event.key === "=") { event.preventDefault(); zoom(.8); }
    else if (event.key === "-") { event.preventDefault(); zoom(1.25); }
  });
  let drag;
  svg.addEventListener("pointerdown", event => { if (event.button !== 0 || event.target.closest("[data-plot-call], [data-source-call]")) return; drag = {x:event.clientX,y:event.clientY,box:view()}; svg.setPointerCapture(event.pointerId); });
  svg.addEventListener("pointermove", event => {
    if (!drag) return;
    const rect = svg.getBoundingClientRect(), [x,y,w,h] = drag.box;
    const ratio = Math.min(rect.width/w,rect.height/h);
    setView([x-(event.clientX-drag.x)/ratio,y-(event.clientY-drag.y)/ratio,w,h]);
  });
  const stopDrag = () => { drag = null; };
  svg.addEventListener("pointerup", stopDrag);
  svg.addEventListener("pointercancel", stopDrag);
  window.addEventListener("resize", scale);
  scale();
})();
