'use strict';
const $ = id => document.getElementById(id);
let boards = [], generation = 0;
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL = value => { try {const u = new URL(value); return ['https:','http:'].includes(u.protocol) ? u.href : '#';}catch{return '#';} };
function options(id, values){$(id).replaceChildren(...values.map(([value,label])=>{const o=document.createElement('option');o.value=value;o.textContent=label;return o;}));}
function matching(){return boards.filter(b=>b.platform===$('platform').value && (!$('audience').value || b.audience===$('audience').value));}
function categories(){options('category',[['','全部分类'],...[...new Set(matching().map(b=>b.category))].filter(x=>x!=='全部').map(x=>[x,x])]);selectBoards();}
function scoped(){return matching().filter(b=>!$('category').value || b.category===$('category').value);}
function selected(){return scoped().filter(b=>!$('board').value || b.id===$('board').value);}
function selectBoards(){options('board',[['','全部榜单'],...scoped().map(b=>[b.id,`${b.audience==='male'?'男频':'女频'} · ${b.category} · ${b.label}`])]);load();}
let refreshing=false;
async function api(url, init){const response=await fetch(url,{cache:'no-store',...init});const data=await response.json();if(!response.ok || !data.ok)throw Error(data.error||data.message||'请求失败');return data;}
function dateText(value){return value ? new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})+' 北京时间' : '尚未采集';}
async function load(){
 const seq=++generation,list=selected(),days=Number($('days').value);
 $('feedback').textContent='';$('table').replaceChildren();$('source').hidden=true;
 $('refresh').disabled=refreshing || !list.length;
 $('heading').textContent=list.length?`当前范围：${list.length} 个榜单`:'此范围暂未接入官方榜单';
 $('meta').textContent=list.length?'正在读取已保存快照…':'请选择其他平台或频道。';
 $('coverage').textContent='全部仅指已接入入口。按来源榜单分别展示，同书多榜保留各自名次，不合并为总排名。';
 let index=0,success=0,failed=0;
 const slots=list.map(()=>{const el=document.createElement('section');el.className='board-group';$('table').append(el);return el;});
 async function worker(){while(index<list.length){const i=index++,b=list[i];try{
  const data=await api('/api/hotlists?'+new URLSearchParams({board:b.id,days}));if(seq!==generation)return;
  const elements={};for(const key of ['heading','meta','coverage','feedback','source','table']){const el=document.createElement(key==='heading'?'h2':key==='source'?'a':key==='table'?'div':'p');elements[key]=el;slots[i].append(el);}
  elements.source.textContent='查看官方原榜 ↗';elements.source.target='_blank';elements.source.rel='noopener noreferrer';elements.source.hidden=true;elements.table.className='table-wrap';
  render(data,days,b.id,key=>elements[key]);success++;
 }catch(error){if(seq!==generation)return;failed++;slots[i].textContent=`${b.category} · ${b.label}：读取失败，${error.message}`;}
 if(seq===generation)$('meta').textContent=`已读取 ${success}/${list.length} 个榜单${failed?`，失败 ${failed} 个`:''}；采集时间、官方统计时间和覆盖天数见各榜单。`;
 }}
 await Promise.all(Array.from({length:Math.min(3,list.length)},worker));
}
function render(data,days,id,$){
 const b=boards.find(x=>x.id===id),s=data.snapshot;
 $('heading').textContent=`${b.platform} · ${b.audience==='male'?'男频':'女频'} · ${b.category} · ${b.label}`;
 if(!s){$('meta').textContent='尚无成功采集记录。可点击“联网刷新当前范围”，或等待每日采集完成。';$('coverage').textContent='已覆盖 0 天';$('feedback').textContent=data.attempt?.error||'';return;}
 $('meta').textContent=`采集：${dateText(s.captured_at)} ｜ 平台统计：${s.platform_cutoff}`;
 const old=Date.now()-new Date(s.captured_at).getTime()>24*3600*1000;
 $('coverage').textContent=days?`窗口：${data.window_start} 至 ${data.window_end}；实际覆盖 ${data.covered_days}/${days} 天${data.covered_days<days?'，样本不足，不能代表完整期间':''}。按观察上榜天数、平均名次排序；升降比较期间首末出现名次。`:`当前入口 ${s.count} 本；${b.note}。${old?'这是超过24小时的历史快照，请刷新。':'这是已保存快照，需要最新结果请点击联网刷新。'}`;
 $('source').href=safeURL(s.source_url);$('source').hidden=false;
 if(data.attempt?.error)$('feedback').textContent=`最近一次采集失败（${dateText(data.attempt.at)}）：${data.attempt.error}。以下保留上次成功数据。`;
 const trend=days>0;
 const rows=data.books.map(book=>{const change=book.rank_change==null?'样本不足':book.rank_change>0?`↑ ${book.rank_change}`:book.rank_change<0?`↓ ${-book.rank_change}`:'持平';return `<tr><td>${escapeHTML(book.rank)}</td><td><a href="${escapeHTML(safeURL(book.url))}" target="_blank" rel="noopener noreferrer">${escapeHTML(book.title)}</a><p>${escapeHTML(book.author)}</p><span class="tags">${escapeHTML((book.genres||[]).join(' · '))}</span><details><summary>查看简介</summary><p>${escapeHTML(book.description||'未提供简介')}</p></details></td>${trend?`<td>${book.observed_days}/${data.covered_days} 天</td><td>${book.avg_rank}</td><td>${change}</td><td>${escapeHTML(book.last_seen)}<p>${book.in_latest?'最近快照中在榜':'最近快照中未出现；不推断全榜落榜'}</p></td>`:`<td>${escapeHTML(book.metric||'未提供')}</td><td>${escapeHTML(book.status||'待核实')}<p>${book.words?escapeHTML(book.words)+' 万字':'字数未确认'}</p></td>`}</tr>`;}).join('');
 $('table').innerHTML=data.books.length?`<table><thead><tr><th>${trend?'最后观察名次':'官方名次'}</th><th>书名 / 作者 / 分类</th>${trend?'<th>观察上榜</th><th>平均名次</th><th>首末升降</th><th>最后出现</th>':'<th>官方指标</th><th>作品状态</th>'}</tr></thead><tbody>${rows}</tbody></table>`:'<p class="empty">所选时间窗口内尚无可用记录。</p>';
}
$('platform').onchange=categories;$('audience').onchange=categories;$('category').onchange=selectBoards;$('board').onchange=load;$('days').onchange=load;
$('refresh').onclick=async()=>{
 const list=selected();if(refreshing || !list.length)return;refreshing=true;
 const controls=[...document.querySelectorAll('.filters select'),$('refresh')];controls.forEach(el=>el.disabled=true);
 let completed=0;const failures=[];
 try{for(const b of list){$('feedback').textContent=`联网刷新 ${completed+1}/${list.length}：${b.audience==='male'?'男频':'女频'} · ${b.category} · ${b.label}…`;
 try{await api('/api/hotlists/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({board:b.id})});}catch(error){failures.push(`${b.category} · ${b.label}：${error.message}`);}completed++;
 }
 await load();$('feedback').textContent=`刷新完成：成功 ${completed-failures.length}/${list.length} 个榜单。${failures.length?'失败的榜单保留旧快照：'+failures.join('；'):''}`;
 }finally{refreshing=false;controls.forEach(el=>el.disabled=false);$('refresh').disabled=!selected().length;}
};
api('/api/hotlists').then(data=>{boards=data.boards;categories();}).catch(error=>{$('feedback').textContent=error.message;$('heading').textContent='无法加载榜单目录';});
