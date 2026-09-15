// One-command local demo: install locked dependencies, seed, start, verify, stop.
import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import net from 'node:net';
import {createHash} from 'node:crypto';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const home=path.resolve(root,process.env.DEMO_HOME||'artifacts/hackathon-demo');
const venv=path.resolve(root,process.env.DEMO_VENV||'backend/.venv');
const python=path.join(venv,process.platform==='win32'?'Scripts/python.exe':'bin/python');
const apiPort=Number(process.env.DEMO_API_PORT||8000),uiPort=Number(process.env.DEMO_UI_PORT||5173);
const reset=process.argv.includes('--reset'),prepareOnly=process.argv.includes('--prepare-only');
const key='quay-local-demo-only-operator-key-2026';
const children=[];
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));

function run(command,args,options={}){
  return new Promise((resolve,reject)=>{
    const child=spawn(command,args,{cwd:root,stdio:'inherit',...options});
    child.on('error',reject);child.on('exit',code=>code===0?resolve():reject(Error(`${command} exited ${code}`)));
  });
}
// npm's .cmd requires cmd.exe on Windows; arguments are static, never user input.
function npmInstall(){return process.platform==='win32'?run(process.env.ComSpec||'cmd.exe',['/d','/s','/c','npm ci --no-audit --no-fund']):run('npm',['ci','--no-audit','--no-fund'])}
async function available(port){
  if(!Number.isInteger(port)||port<1024||port>65535)throw Error('Demo ports must be integers from 1024 to 65535');
  await new Promise((resolve,reject)=>{const socket=net.createServer();socket.once('error',()=>reject(Error(`Port ${port} is occupied. Stop that server or set DEMO_API_PORT/DEMO_UI_PORT; reset will not touch active services.`)));socket.listen(port,'127.0.0.1',()=>socket.close(resolve))});
}
async function ready(url,timeout=180000){
  const until=Date.now()+timeout;
  while(Date.now()<until&&!stopping){try{const response=await fetch(url,{signal:AbortSignal.timeout(2000)});if(response.ok)return}catch{/* server starting */}await delay(1000)}
  throw Error('Startup check timed out: '+url);
}
async function stop(){
  if(process.platform==='win32'){
    // venv python.exe has a redirector child on Windows: stop only owned trees.
    await Promise.all(children.map(child=>new Promise(resolve=>{
      if(!child.pid||child.exitCode!==null)return resolve();
      const task=spawn('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});
      task.on('exit',resolve);task.on('error',resolve);
    })));
  }else for(const child of children)child.kill('SIGTERM');
  await delay(800);
  for(const child of children)if(child.exitCode===null)child.kill('SIGKILL');
  try{const running=JSON.parse(await fs.readFile(path.join(home,'running.json'),'utf8'));if(running.owner===process.pid)await fs.unlink(path.join(home,'running.json'))}catch{/* no owned marker */}
}
let stopping=false;
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,async()=>{if(stopping)return;stopping=true;await stop();process.exit(0)});

try{
  if(!home.startsWith(path.join(root,'artifacts')+path.sep))throw Error('DEMO_HOME must be a dedicated workspace artifacts subdirectory');
  if(!venv.startsWith(root+path.sep))throw Error('DEMO_VENV must stay inside the workspace');
  if(apiPort===uiPort)throw Error('API and frontend ports must differ');
  await available(apiPort);await available(uiPort);
  try{
    const running=JSON.parse(await fs.readFile(path.join(home,'running.json'),'utf8'));
    for(const pid of [running.owner,...running.children]){
      let alive=false;try{process.kill(pid,0);alive=true}catch{/* stopped */}
      if(alive)throw Error('This demo state is in use. Stop its launcher before resetting or starting again.');
    }
    await fs.unlink(path.join(home,'running.json'));
  }catch(error){if(error.code!=='ENOENT')throw error}
  try{await fs.access(python)}catch{await run(process.env.DEMO_PYTHON||'python',['-m','venv',venv])}
  console.log('Checking locked Python dependencies...');
  await run(python,['-m','pip','--disable-pip-version-check','install','-r','backend/requirements-dev.txt']);
  const lockHash=createHash('sha256').update(await fs.readFile(path.join(root,'package-lock.json'))).digest('hex');
  const npmMarker=path.join(root,'node_modules/.quay-demo-install.json');
  let npmReady=false;try{npmReady=JSON.parse(await fs.readFile(npmMarker,'utf8')).lockHash===lockHash}catch{/* clean or incomplete installation */}
  if(!npmReady){
    console.log('Installing locked frontend dependencies (npm ci). Wait for "QUAY demo ready"; Ctrl+C cancels setup.');
    await npmInstall();await fs.writeFile(npmMarker,JSON.stringify({lockHash}));
    console.log('Frontend dependency installation complete. Preparing the demo database...');
  }
  await run(python,['backend/scripts/prepare_hackathon.py','--home',home,...reset?['--reset']:[]]);
  const state=JSON.parse(await fs.readFile(path.join(home,'demo-state.json'),'utf8'));
  if(prepareOnly){console.log('Demo reset/preparation complete. Previous demo state is archived. Run npm run demo to start.');process.exit(0)}
  const env={...process.env,APP_ENV:'development',DATABASE_URL:'sqlite:///'+path.join(home,'operations.db').replaceAll('\\','/'),
    MODEL_DIRECTORY:path.join(root,'demo/seed/models'),EVALUATION_DIRECTORY:path.join(root,'demo/recorded'),
    LIVE_DEMO_DIRECTORY:path.join(home,'live-demo'),LIVE_DEMO_ENABLED:'true',AUTO_MIGRATE:'true',DEMO_SEED_ON_START:'false',DEMO_TRAIN_ON_START:'false',
    READINESS_REQUIRE_MODEL:'true',READINESS_REQUIRE_DATA:'true',OPERATOR_API_KEY:key,
    CORS_ORIGINS:`http://127.0.0.1:${uiPort}`,VITE_DEMO_MODE:'true',VITE_API_BASE_URL:'/api/v1',
    API_PROXY_TARGET:`http://127.0.0.1:${apiPort}`,COPILOT_API_KEY:'',ALERT_RULES_FILE:'',OPTIMISATION_POLICY_FILE:'',RECOMMENDATION_POLICY_FILE:''};
  const backend=spawn(python,['-m','uvicorn','app.main:app','--app-dir','backend','--host','127.0.0.1','--port',String(apiPort)],{cwd:root,env,stdio:'inherit'});
  // The runner loader avoids Vite's temporary bundled-config file, which can be
  // held open by Windows indexing or an editor after an interrupted demo.
  const frontend=spawn(process.execPath,[path.join(root,'node_modules/vite/bin/vite.js'),'--configLoader','runner','--host','127.0.0.1','--port',String(uiPort)],{cwd:path.join(root,'frontend'),env,stdio:'inherit'});
  children.push(backend,frontend);
  try {
    await fs.writeFile(path.join(home,'running.json'),JSON.stringify({owner:process.pid,children:children.map(c=>c.pid)}));
  } catch (error) {
    // Listener ownership is still protected by available() above. The marker is
    // only a reset convenience, so a transient Windows share lock must not make
    // an otherwise healthy local demo unavailable.
    if (!['EACCES','EPERM'].includes(error?.code)) throw error;
    console.warn('Demo state marker is locked; startup will continue. Stop this launcher before running demo:reset.');
  }
  for(const child of children)child.on('error',async error=>{console.error(error.message);await stop();process.exit(1)});
  const serviceExit=new Promise((resolve,reject)=>{for(const child of children)child.on('exit',code=>stopping?resolve():reject(Error(`Demo service stopped (${code})`)))});
  await Promise.race([Promise.all([ready(`http://127.0.0.1:${apiPort}/ready`),ready(`http://127.0.0.1:${uiPort}`)]),serviceExit]);
  console.log(`\nQUAY demo ready: http://127.0.0.1:${uiPort}/?run=${state.seed.normal_run_id}#overview\nOperator access key: ${key}\nPreloaded storm: ${state.seed.storm_run_id}\nBackup without services: ${path.join(root,'demo/backup/index.html')}\nCtrl+C stops both owned services. Reset after stopping: npm run demo:reset\n`);
  if(process.argv.includes('--smoke')){stopping=true;await stop();process.exit(0)}
  await serviceExit;
}catch(error){stopping=true;console.error('Demo failed: '+error.message);await stop();process.exitCode=1}
