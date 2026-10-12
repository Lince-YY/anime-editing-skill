(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const places = {local:'本机',service:'内置服务',cloud:'云端 GPU',hybrid:'本机与服务'};
  const statuses = {planned:'计划中',running:'制作中',ready:'已产出',accepted:'已接受',missing:'缺少产物',failed:'未通过'};
  let data, steps, assets, count, selectedStep=0, layoutKey='', drawRequest=0;
  const matrix=$('matrix'), stepDialog=$('step-dialog'), cache=new WeakMap();
  function html(el, value) { if(cache.get(el)!==value){el.innerHTML=value;cache.set(el,value);} }
  function text(el, value) { const next=String(value ?? '');if(el.textContent!==next)el.textContent=next; }
  function tag(place, label){return `<span class="tag ${esc(place)}">${esc(label || places[place])}</span>`;}
  function mediaHTML(asset, {compact=false,poster=''}={}){
    if(!asset)return '';
    if(!asset.src)return `<p class="unavailable">${esc(statuses[asset.status] || '缺少产物')}：${esc(asset.caption || asset.title)}</p>`;
    const label=esc(asset.title),src=esc(asset.src);
    if(asset.type==='image')return `<button class="image-button" data-image="${esc(asset.id)}" aria-label="放大：${label}"><img class="${compact?'activity-media':''}" src="${src}" alt="${label}" loading="lazy" decoding="async"></button>`;
    if(asset.type==='video')return `<video class="${compact?'activity-media':''}" controls playsinline preload="metadata" ${compact?'muted':''} ${poster?`poster="${esc(poster)}"`:''} aria-label="${label}" src="${src}"></video>`;
    if(asset.type==='audio')return `<audio controls preload="metadata" aria-label="${label}" src="${src}"></audio>`;
    return '';
  }
  function modelsHTML(rows){return `<ul class="model-list">${rows.map(m=>`<li><b>${esc(m.role || m.name || '模型文件')}</b><code>${esc(m.file || m.name)}</code><small>${esc(m.state || m.status)}</small></li>`).join('')}</ul>`;}
  function element(source){const t=document.createElement('template');t.innerHTML=source;return t.content.firstElementChild;}
  function pauseMedia(root=document){root.querySelectorAll('video,audio').forEach(el=>el.pause());}
  function progressHTML(step){return typeof step.progress==='number'?`<progress max="100" value="${step.progress}" aria-label="步骤进度"></progress><span>${step.progress}%</span>`:'';}
  function renderMatrix(){
    const lanes=data.chart.lanes,nodes=data.chart.nodes;
    const key=JSON.stringify([count,lanes,nodes.map(n=>[n.id,n.row,n.step])]);
    if(key!==layoutKey){
      const oldCards=new Map([...matrix.querySelectorAll('.activity')].map(el=>[el.id,el]));
      matrix.querySelectorAll(':scope > :not(svg)').forEach(el=>el.remove());
      matrix.style.setProperty('--columns',count);matrix.style.setProperty('--rows',lanes.length);
      for(const [i,step] of data.steps.entries())matrix.append(element(`<button class="step-header" data-open-step="${step.id}" style="grid-column:${i+1};grid-row:1"><span class="step-number">STEP ${String(i+1).padStart(2,'0')}</span><b></b></button>`));
      matrix.append(element(`<div class="tool-header" style="grid-column:${count+1};grid-row:1">工具 / 运行位置 ↓<small>每一行是参与的工具</small></div>`));
      lanes.forEach((lane,row)=>{
        for(let index=1;index<=count;index++){
          const node=nodes.find(n=>n.row===row && n.step===index);
          const cell=element(`<div class="grid-cell ${node?'':'empty'}" style="grid-column:${index};grid-row:${row+2}"></div>`);
          if(node){
            const card=oldCards.get('node-'+node.id) || element(`<article id="node-${node.id}" class="activity"><div class="node-place"></div><span class="status-label"></span><b class="activity-title"></b><div class="node-progress"></div><div class="node-media"></div><p class="activity-caption"></p><button class="expand-card" data-open-step="${node.step}"><span>输入 / 方法 / 产物</span><span>↗</span></button></article>`);
            cell.append(card);
          }
          matrix.append(cell);
        }
        matrix.append(element(`<aside class="tool-lane" style="grid-column:${count+1};grid-row:${row+2}"><span class="lane-number">TOOL ${String(row+1).padStart(2,'0')}</span><b>${esc(lane.name)}</b>${tag(lane.place,lane.tag)}<small>${esc(lane.detail).replace(/\n/g,'<br>')}</small></aside>`));
      });
      layoutKey=key;
    }
    data.steps.forEach(step=>{
      const header=matrix.querySelector(`.step-header[data-open-step="${step.id}"]`);
      text(header.querySelector('b'),step.short_title || step.title);
      header.setAttribute('aria-label',`打开第${step.id}步${step.title}`);
    });
    for(const node of nodes){
      const card=$('node-'+node.id), step=steps.get(node.step);
      card.className='activity '+node.place;card.dataset.place=node.place;
      html(card.querySelector('.node-place'),tag(node.place));
      text(card.querySelector('.status-label'),statuses[node.status || step.status] || '状态未知');
      text(card.querySelector('.activity-title'),node.title);
      text(card.querySelector('.activity-caption'),step.message || node.caption);
      html(card.querySelector('.node-progress'),progressHTML(step));
      const media=node.text?`<div class="text-artifact">${esc(node.text)}</div>`:mediaHTML(assets[node.asset],{compact:true,poster:assets[node.poster]?.src || ''});
      html(card.querySelector('.node-media'),media); // unchanged media DOM stays alive
      card.querySelector('.expand-card').dataset.openStep=node.step;
    }
    applyFilter();drawConnections();
  }
  function drawConnections(){
    cancelAnimationFrame(drawRequest);
    drawRequest=requestAnimationFrame(()=>{
      const base=matrix.getBoundingClientRect();
      $('connections').setAttribute('viewBox',`0 0 ${matrix.scrollWidth} ${matrix.scrollHeight}`);
      $('connection-paths').innerHTML=(data.chart.links || []).map(([from,to])=>{
        const ae=$('node-'+from),be=$('node-'+to);if(!ae || !be)return '';
        const a=ae.getBoundingClientRect(),b=be.getBoundingClientRect();
        let x1=a.right-base.left,y1=a.top+a.height/2-base.top,x2=b.left-base.left,y2=b.top+b.height/2-base.top,d;
        if(Math.abs(a.left-b.left)<8){x1=a.left+a.width/2-base.left;x2=x1;y1=a.bottom-base.top;y2=b.top-base.top;d=`M${x1},${y1} L${x2},${y2}`;}
        else{const bend=Math.max(18,(x2-x1)/2);d=`M${x1},${y1} C${x1+bend},${y1} ${x2-bend},${y2} ${x2},${y2}`;}
        return `<path d="${d}" marker-end="url(#arrow)"/>`;
      }).join('');
    });
  }
  function applyFilter(){const filter=$('environment-filter').value;matrix.querySelectorAll('.activity').forEach(el=>el.classList.toggle('dimmed',filter!=='all' && filter!==el.dataset.place));}
  function renderStep(id, switching=false){
    const step=steps.get(Number(id));if(!step){stepDialog.close();return;}
    if(switching){pauseMedia();$('detail-content').replaceChildren();cache.delete($('detail-content'));}
    if(!$('detail-media'))html($('detail-content'),'<div class="detail-grid"><div id="detail-media"></div><aside class="detail-facts" id="detail-facts"></aside></div><div class="content-box" style="margin-top:24px"><h3>本步脚本 / 输入内容 / 实际参数</h3><pre id="detail-copy"></pre></div><div id="detail-code"></div>');
    text($('detail-kicker'),`STEP ${String(id).padStart(2,'0')} / ${count} · ${statuses[step.status] || '状态未知'}`);
    text($('detail-title'),step.title);text($('detail-subtitle'),step.subtitle || step.message || '');
    const media=(step.media || []).map(key=>assets[key]).filter(Boolean);
    html($('detail-media'),media.map(a=>`<figure class="media-item">${mediaHTML(a)}<figcaption><b>${esc(a.title)}</b><p>${esc(a.caption)}</p>${a.original_src?`<p><a href="${esc(a.original_src)}" download>保留的原始生成文件</a></p>`:''}</figcaption></figure>`).join(''));
    const runtime=(data.runtime || []).find(r=>Number(r.id)===Number(id));
    html($('detail-facts'),[['运行位置',step.environment],['本机软件 / 云端工具',(step.tools || []).join(' · ')],['输入',step.input],['怎么做',step.action],['产物 / 当前状态',step.output],['最新进度',step.message || '未记录']].map(([label,value])=>`<div class="fact"><strong>${esc(label)}</strong><p>${esc(value)}</p></div>`).join('')+progressHTML(step)+((step.models || []).length?`<details open><summary>本步模型</summary>${modelsHTML(step.models)}</details>`:'')+(runtime?.models?.length?`<details><summary>实际模型文件与加载状态</summary>${modelsHTML(runtime.models)}</details>`:'')+((step.notes || []).length?`<details><summary>版本与方法说明</summary><ul>${step.notes.map(n=>`<li>${esc(n)}</li>`).join('')}</ul></details>`:''));
    text($('detail-copy'),step.content || '');
    html($('detail-code'),step.code_excerpt?`<details class="content-box"><summary>实际执行代码节选</summary><pre>${esc(step.code_excerpt)}</pre></details>`:'');
    text($('detail-count'),`${String(id).padStart(2,'0')} / ${count}`);
    $('previous-step').disabled=Number(id)===1;$('next-step').disabled=Number(id)===count;
    if(!stepDialog.open)stepDialog.showModal();
    if(switching)stepDialog.querySelector('.dialog-scroll').scrollTop=0;
  }
  function openStep(id){if(!steps.has(Number(id)))return;selectedStep=Number(id);renderStep(id,true);}
  function render(next){
    if(!next?.steps?.length || !next.chart?.nodes)throw new Error('Invalid snapshot');
    data=next;steps=new Map(data.steps.map(s=>[Number(s.id),s]));assets=data.assets || {};count=data.steps.length;
    const meta=data.meta || {};
    document.title=meta.title || '动漫混剪操作流';text($('page-title'),document.title);text($('brand'),meta.brand || '动漫混剪');
    text($('case-date'),meta.date);text($('page-lead'),meta.lead || `${count} 个步骤 × 工具 × 产物与状态`);text($('overview'),`${count} 步总览`);
    html($('environment-strip'),(meta.environment_legend || []).map(item=>`<span><i class="dot ${esc(item.place)}"></i>${esc(item.text)}</span>`).join(''));
    html($('page-footer'),(meta.footer || []).map(line=>`<p>${esc(line)}</p>`).join(''));
    $('final-launch').hidden=!(meta.final_step && steps.has(Number(meta.final_step)));
    if(!$('final-launch').hidden){$('final-launch').dataset.openStep=meta.final_step;text($('final-label'),meta.final_label || '查看最终产物');text($('final-subtitle'),meta.final_caption);}
    const handoff=data.handoff;$('handoff-section').hidden=!handoff?.items?.length;
    if(handoff?.items?.length){text($('handoff-title'),handoff.title || '关键交接');text($('handoff-description'),handoff.description);html($('handoff-items'),handoff.items.map(i=>`<button data-open-step="${Number(i.step)}">${tag(i.place,i.tag)}<b>${esc(i.title)}</b><small>${esc(i.caption)}</small></button>`).join('<span class="handoff-arrow">→</span>'));}
    const groups=data.runtime_groups || [];$('runtime-section').hidden=!groups.length;
    html($('runtime-cards'),groups.map(group=>{
      const rows=(data.runtime || []).filter(r=>group.ids.includes(Number(r.id))),models=rows.flatMap(r=>r.models || []);
      return `<article class="runtime-card ${esc(group.place)}"><span class="step-tag">${esc(group.label)}</span><h3>${esc(group.title)}</h3><p>${esc(group.description)}</p><details><summary>实际模型文件与加载状态</summary>${models.length?modelsHTML(models):'<p>未记录；以实际执行报告为准。</p>'}</details></article>`;
    }).join(''));
    renderMatrix();if(selectedStep && stepDialog.open)renderStep(selectedStep);
    if($('image-dialog').open){const asset=assets[$('large-image').dataset.asset];if(asset?.src){if($('large-image').getAttribute('src')!==asset.src)$('large-image').src=asset.src;text($('large-caption'),asset.title+' · '+asset.caption);}else $('image-dialog').close();}
  }
  new ResizeObserver(drawConnections).observe(matrix);
  matrix.addEventListener('load',drawConnections,true);matrix.addEventListener('loadedmetadata',drawConnections,true);
  ['overview','expanded'].forEach(id=>$(id).addEventListener('click',()=>{matrix.classList.toggle('expanded',id==='expanded');['overview','expanded'].forEach(other=>{$(other).classList.toggle('active',id===other);$(other).setAttribute('aria-pressed',String(id===other));});drawConnections();}));
  $('environment-filter').addEventListener('change',applyFilter);
  document.addEventListener('click',event=>{
    const image=event.target.closest('[data-image]');if(image){const a=assets[image.dataset.image];if(a?.src){$('large-image').src=a.src;$('large-image').dataset.asset=a.id;$('large-image').alt=a.title;text($('large-caption'),a.title+' · '+a.caption);$('image-dialog').showModal();}return;}
    const step=event.target.closest('[data-open-step]');if(step)openStep(step.dataset.openStep);
  });
  document.addEventListener('play',event=>{if(event.target.matches('video,audio'))document.querySelectorAll('video,audio').forEach(other=>{if(other!==event.target)other.pause();});},true);
  $('close-dialog').addEventListener('click',()=>stepDialog.close());stepDialog.addEventListener('close',()=>{pauseMedia(stepDialog);$('detail-content').replaceChildren();cache.delete($('detail-content'));selectedStep=0;});
  $('previous-step').addEventListener('click',()=>openStep(selectedStep-1));$('next-step').addEventListener('click',()=>openStep(selectedStep+1));
  $('close-image').addEventListener('click',()=>$('image-dialog').close());$('image-dialog').addEventListener('close',()=>$('large-image').removeAttribute('src'));
  [stepDialog,$('image-dialog')].forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}}));
  try{render(window.FLOW_DATA);}catch(_){text(matrix,'页面数据未能加载，请保持 HTML、脚本和 media 文件夹在一起。');return;}
  const connection=$('connection-status'),timestamp=$('last-update');
  function connectionState(label,state){text(connection,label);connection.dataset.state=state;}
  if(!window.FLOW_LIVE){connectionState('离线快照 · 不接收后续进度','offline');text(timestamp,data.meta?.updated_at || '');return;}
  const config=window.FLOW_LIVE;let revision=-1,lastEvent=Date.now(),source,staleError=null;
  text(timestamp,config.updated_at?`记录更新：${config.updated_at}`:'');
  connectionState('正在连接实时进度…','connecting');
  if(!window.EventSource){connectionState('浏览器不支持实时推送；请使用现代浏览器','error');return;}
  function connect(){
  source=new EventSource(config.events);
  source.onopen=()=>{lastEvent=Date.now();connectionState(staleError || '已连接 · 进度自动更新',staleError?'error':'live');};
  source.addEventListener('snapshot',event=>{
    lastEvent=Date.now();
    try{
      const snapshot=JSON.parse(event.data);staleError=snapshot.error;
      const key=`${snapshot.instance_id || ''}:${snapshot.revision}`;
      if(key!==revision){render(snapshot.data);revision=key;}
      text(timestamp,snapshot.updated_at?`记录更新：${snapshot.updated_at}`:'');
      connectionState(snapshot.error || '已连接 · 进度自动更新',snapshot.error?'error':'live');
    }catch(_){connectionState('更新内容异常；保留当前画面，等待有效记录','error');}
  });
  source.addEventListener('heartbeat',()=>{lastEvent=Date.now();});
  source.onerror=()=>connectionState('连接中断 · 正在自动重连，当前为最近记录','reconnecting');
  }
  const checkConnection=()=>{if(Date.now()-lastEvent>15000)connectionState('暂未收到服务响应 · 等待自动恢复','reconnecting');};
  connect();let timer=setInterval(checkConnection,5000);
  window.addEventListener('pagehide',()=>{source.close();clearInterval(timer);});
  window.addEventListener('pageshow',event=>{if(event.persisted){lastEvent=Date.now();connectionState('正在恢复实时进度…','connecting');connect();timer=setInterval(checkConnection,5000);}});
})();
