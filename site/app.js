'use strict';
const data = window.FEIGBENCH;
const chart = document.querySelector('#chart');
const enabledVendors = new Set(data.points.map(p => p.vendor));
const effortSelect = document.querySelector('#effort');
const key = p => `${p.model}|${p.effort}`;
const money = value => value == null ? 'Unknown' : `$${value.toFixed(5)}`;
const escapeHTML = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const visiblePoints = () => data.points.filter(p => enabledVendors.has(p.vendor) && (effortSelect.value === 'all' || p.effort === effortSelect.value));
let chartReady = false;
let revision = 0;

document.querySelector('#model-count').textContent = data.models;
document.querySelector('#call-count').textContent = data.scored_calls;
document.querySelector('#run-label').textContent = `Run ${data.run} · ${data.scoring_version}`;
document.querySelector('#settings').textContent = `${data.models} models, ${data.points.length} settings, ${data.repetitions} repetitions per text and setting. ${data.scored_calls} scored calls and ${data.control_calls} control calls. Provider-default sampling (temperature omitted), a ${data.max_tokens.toLocaleString()}-token completion budget including reasoning, and OpenRouter routing with required parameter support. ${data.api_errors} saved API errors.`;

for (const vendor of [...enabledVendors].sort()) {
  const point = data.points.find(p => p.vendor === vendor);
  const button = document.createElement('button');
  button.type = 'button'; button.textContent = point.vendor_name;
  button.style.setProperty('--vendor', point.color);
  button.setAttribute('aria-pressed', 'true');
  button.addEventListener('click', () => {
    if (enabledVendors.has(vendor)) enabledVendors.delete(vendor); else enabledVendors.add(vendor);
    button.setAttribute('aria-pressed', String(enabledVendors.has(vendor)));
    render();
  });
  document.querySelector('#vendor-filters').append(button);
}

function showPoint(p) {
  document.querySelector('#point-detail').innerHTML = `<span class="eyebrow">${escapeHTML(p.vendor_name)} · ${escapeHTML(p.effort)} effort</span><p class="detail-name">${escapeHTML(p.name)}</p><div class="detail-values"><span>Score <b>${p.soft_score.toFixed(1)} / 100</b></span><span>Speaker <b>${p.speaker_conf.toFixed(1)}%</b></span><span>Context <b>${p.context_conf.toFixed(1)}%</b></span><span>Cost <b>${money(p.mean_cost_usd)}</b></span><span>${p.calls} calls · ${p.errors} failed / unparsed</span></div>`;
}
function renderTable(points) {
  const tbody = document.querySelector('#results-table');
  tbody.replaceChildren();
  for (const p of [...points].sort((a,b) => b.soft_score - a.soft_score)) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><button type="button">${escapeHTML(p.name)}</button></td><td>${escapeHTML(p.effort)}</td><td>${p.soft_score.toFixed(1)}</td><td>${p.speaker_conf.toFixed(1)}%</td><td>${p.context_conf.toFixed(1)}%</td><td>${money(p.mean_cost_usd)}</td><td>${p.errors} / ${p.calls}</td>`;
    tr.querySelector('button').addEventListener('click', () => {
      showPoint(p);
      document.querySelector('#point-detail').scrollIntoView({block:'nearest', behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
    });
    tbody.append(tr);
  }
  if (!points.length) tbody.innerHTML = '<tr><td colspan="7">No vendors selected. Select a vendor above to show its results.</td></tr>';
}
function drawChart(points) {
  const mobile = window.innerWidth < 760;
  const plotted = points.filter(p => p.mean_cost_usd !== null);
  const traces = [];
  const byKey = new Map(plotted.map(p => [key(p), p]));
  const positive = data.points.filter(p => p.mean_cost_usd !== null).every(p => p.mean_cost_usd > 0);
  const makeLine = (ps, dash, opacity) => ({type:'scatter', mode:'lines', x:ps.map(p=>p.mean_cost_usd), y:ps.map(p=>p.soft_score), line:{color:ps[0].color,width:1.6,dash},opacity,hoverinfo:'skip',showlegend:false});
  for (const vendor of enabledVendors) {
    const ps = plotted.filter(p=>p.vendor===vendor && p.effort==='medium').sort((a,b)=>a.mean_cost_usd-b.mean_cost_usd);
    if (ps.length>1) traces.push(makeLine(ps,'dash',.35));
  }
  for (const ids of data.links) {
    const ps = ids.map(id=>byKey.get(id)).filter(Boolean);
    if (ps.length>1) traces.push(makeLine(ps,'solid',.65));
  }
  for (const model of new Set(plotted.map(p=>p.model))) {
    const ps = plotted.filter(p=>p.model===model).sort((a,b)=>data.effort_order.indexOf(a.effort)-data.effort_order.indexOf(b.effort));
    traces.push({type:'scatter',mode:'markers',name:ps[0].name,x:ps.map(p=>p.mean_cost_usd),y:ps.map(p=>p.soft_score),
      marker:{color:ps[0].color,size:ps.map(p=>({low:8,medium:11,high:14}[p.effort]||10)),symbol:ps.map(p=>p.effort==='medium'?'circle':'circle-open'),line:{width:2}},
      customdata:ps.map(p=>[p.name,p.effort,p.speaker_conf,p.context_conf,p.calls,p.errors,key(p)]),
      hovertemplate:'<b>%{customdata[0]}</b> · %{customdata[1]}<br>Score: %{y:.1f} / 100<br>Cost / request: $%{x:.5f}<br>Speaker: %{customdata[2]:.1f}% · Context: %{customdata[3]:.1f}%<br>%{customdata[4]} calls · %{customdata[5]} failed / unparsed<extra></extra>',showlegend:false});
  }
  const annotations = [];
  if (!mobile) {
    const labelPoints = [...new Set(plotted.map(p=>p.model))].map(model => plotted.filter(p=>p.model===model).sort((a,b)=>data.effort_order.indexOf(a.effort)-data.effort_order.indexOf(b.effort)).at(-1));
    const allCosts = data.points.map(p=>p.mean_cost_usd).filter(x=>x!==null);
    const lower = positive ? Math.log10(Math.min(...allCosts)/1.7) : -.01;
    const upper = positive ? Math.log10(Math.max(...allCosts)*1.7) : Math.max(...allCosts)*1.2;
    const width = Math.max(200, chart.clientWidth-90), height = Math.max(200,chart.clientHeight-90);
    const position = p => [((positive?Math.log10(p.mean_cost_usd):p.mean_cost_usd)-lower)/(upper-lower)*width,(100-p.soft_score)/100*height];
    const markers = plotted.map(p=>{const [x,y]=position(p);return [x-8,y-8,16,16];});
    const occupied = [];
    const overlap = (a,b) => Math.max(0,Math.min(a[0]+a[2],b[0]+b[2])-Math.max(a[0],b[0]))*Math.max(0,Math.min(a[1]+a[3],b[1]+b[3])-Math.max(a[1],b[1]));
    labelPoints.sort((a,b)=>b.soft_score-a.soft_score).forEach(p=>{
      const [x,y]=position(p), labelWidth=p.name.length*5.7+8;
      const choices=[[0,-24],[0,24],[45,-18],[-45,-18],[45,24],[-45,24],[0,-43],[0,43],[70,-32],[-70,-32]].map(([ax,ay])=>{
        const box=[x+ax-labelWidth/2,y+ay-9,labelWidth,18];
        const outside=box[2]*box[3]-overlap(box,[0,0,width,height]);
        return {ax,ay,box,penalty:100*outside+100*occupied.reduce((s,b)=>s+overlap(box,b),0)+10*markers.reduce((s,b)=>s+overlap(box,b),0)+ax*ax+ay*ay};
      }).sort((a,b)=>a.penalty-b.penalty);
      const {ax,ay,box}=choices[0];occupied.push(box);
      annotations.push({x:positive?Math.log10(p.mean_cost_usd):p.mean_cost_usd,y:p.soft_score,text:escapeHTML(p.name),showarrow:true,arrowhead:0,arrowwidth:.6,arrowcolor:p.color,ax,ay,font:{size:10,color:'#152d35'},bgcolor:'#ebece5',borderpad:2});
    });
  }
  const costs = data.points.map(p=>p.mean_cost_usd).filter(x=>x!==null);
  const min = Math.min(...costs), max = Math.max(...costs);
  return Plotly.react(chart,traces,{paper_bgcolor:'transparent',plot_bgcolor:'transparent',font:{family:'system-ui, sans-serif',color:'#61747b',size:11},margin:{l:mobile?44:55,r:mobile?12:35,t:25,b:65},
    xaxis:{type:positive?'log':'linear',range:positive?[Math.log10(min/1.7),Math.log10(max*1.7)]:[-.01,max*1.2],title:{text:mobile?'Average cost / request (USD, log scale)':'Average cost per request (USD, logarithmic scale)',standoff:18,font:{size:12}},tickformat:'$.4f',gridcolor:'#dde1d9',fixedrange:true,automargin:true,nticks:mobile?5:9,zeroline:false},
    yaxis:{range:[0,100],title:{text:'Score / 100',font:{size:12}},gridcolor:'#d0d9d1',fixedrange:true,dtick:20,zeroline:false},annotations,hovermode:'closest',hoverlabel:{bgcolor:'#152d35',font:{color:'#fff',size:12}},
    uirevision:'fixed',transition:{duration:0},showlegend:false},
    {responsive:true,displaylogo:false,displayModeBar:false,scrollZoom:false}).then(()=>{
      if (!chartReady) {
        const inspect = event => {
          const id = event.points?.[0]?.customdata?.[6];
          const p = data.points.find(p=>key(p)===id); if(p)showPoint(p);
        };
        chart.on('plotly_click',inspect);
        chart.on('plotly_hover',inspect);
        chartReady=true;
      }
    });
}
async function render() {
  const current = ++revision;
  const points = visiblePoints(); renderTable(points);
  document.querySelector('#point-detail').innerHTML='<span class="eyebrow">Explore a model</span><p>Select a point or a model in the table to see its score breakdown here.</p>';
  try {
    if (!window.Plotly) throw new Error('Plotly unavailable');
    await drawChart(points);
    if(current===revision)document.querySelector('#chart-error').hidden=true;
  } catch (error) {
    document.querySelector('#chart-error').hidden=false;
    console.error(error);
  }
}
effortSelect.addEventListener('change',render);
document.querySelector('#download-svg').addEventListener('click',async()=>{
  if(!window.Plotly || !chartReady)return;
  await Plotly.downloadImage(chart,{format:'svg',filename:'feigbench-1.0',width:1200,height:700});
});
const excerpts = document.querySelector('#excerpt');
for(const [id] of Object.entries(data.texts)) {
  const option=document.createElement('option');option.value=id;option.textContent=id.split('_')[0]+(id.startsWith('S6')?' · control':'');excerpts.append(option);
}
function showExcerpt(){document.querySelector('#excerpt-text').textContent=data.texts[excerpts.value].replace(/^#.*\n+/, '').replace(/\*\*/g,'');}
excerpts.addEventListener('change',showExcerpt);showExcerpt();
let resizeTimer;
window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{drawChart(visiblePoints()).catch(console.error);},200);});
render();
