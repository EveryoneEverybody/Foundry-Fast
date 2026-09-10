"""Manual Reach farm coordinator. No engine invocation in validation/preparation."""
import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
QUALITIES = ('draft', 'direct_only', 'low', 'medium', 'high', 'super_slow')
MODES = ('ValidateOnly', 'PrepareOnly', 'BakeOnly', 'PrepareAndBake')


def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()
def write(p, value):
    p = Path(p); tmp = p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    for attempt in range(20):
        try:tmp.replace(p);break
        except PermissionError:
            if attempt==19:raise
            time.sleep(.05) # A Windows status reader can briefly hold the file.
def logical(s):
    s = str(s).replace('\\','/')
    if not s or ':' in s or any(x in ('','..','.') for x in s.split('/')):
        raise ValueError('Expected a logical tag path without traversal or drive')
    return s
def safe_path(root, rel):
    root = Path(root).resolve(); p = root / logical(rel)
    if not p.resolve().is_relative_to(root): raise ValueError('Path escapes root')
    return p
def inventory(root):
    root = Path(root).resolve()
    if not root.exists(): return {}
    out = {}
    for p in sorted(root.rglob('*')):
        if not p.resolve().is_relative_to(root) or p.is_symlink(): raise ValueError('Linked output paths are unsupported')
        if p.is_file(): out[p.relative_to(root).as_posix()] = sha(p)
    return out
def differences(before, after):
    return [dict(path=k, before=before.get(k), after=after.get(k)) for k in sorted(before.keys() | after.keys()) if before.get(k)!=after.get(k)]


def require_idle_kit(kit):
    if os.name != 'nt': return
    # Read-only inventory. Never terminate an unrelated editor or Tool process.
    script = "Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('tool.exe','tool_fast.exe','reach_tag_test.exe','reach_tag_play.exe','sapien.exe','guerilla.exe') } | Select-Object Name,ProcessId,ExecutablePath | ConvertTo-Json -Compress"
    text=subprocess.check_output(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],text=True,creationflags=subprocess.CREATE_NO_WINDOW).strip()
    rows=json.loads(text) if text else []
    rows=rows if isinstance(rows,list) else [rows]
    conflicts=[r for r in rows if not r.get('ExecutablePath') or Path(r['ExecutablePath']).resolve().is_relative_to(Path(kit).resolve())]
    if conflicts:raise ValueError('Close these kit clients before guarded writes/restore: '+json.dumps(conflicts))
def select_bsps(request, paths):
    tokens = [x.strip() for item in (request if isinstance(request,list) else [request]) for x in str(item).split(',')]
    if tokens == ['all']: return list(range(len(paths))), True
    selected = []
    for token in tokens:
        if token.isdigit(): index = int(token)
        else:
            matches = [i for i,p in enumerate(paths) if Path(p).stem == token]
            if len(matches)!=1: raise ValueError('Unknown or ambiguous BSP: '+token)
            index = matches[0]
        if index not in range(len(paths)) or index in selected: raise ValueError('Invalid or duplicate BSP selection')
        selected.append(index)
    if not selected: raise ValueError('Empty BSP selection')
    return selected, False


def pipeline(scenario, bsp, quality, workers, job, light_group=''):
    blob = 'faux\\'+str(job)
    groups = [[['faux_data_sync', scenario,bsp]], [['faux_farm_begin',scenario,bsp,light_group,quality,str(job),'true']]]
    # Draft enables final gather but not photon mapping. Never dispatch a
    # disabled phase/merge merely because its preset exists.
    phases = ['dillum']
    if quality not in ('direct_only','draft'): phases.append('pcast')
    if quality != 'direct_only': phases += ['radest_extillum','fgather']
    for phase in phases:
        groups += [[[f'faux_farm_{phase}',blob,str(i),str(workers)] for i in range(workers)],
                   [[f'faux_farm_{phase}_merge',blob,str(workers)]]]
    return groups + [[['faux_farm_finish',blob]],
        [['faux-reorganize-mesh-for-analytical-lights',scenario,bsp]],
        [['faux-build-vmf-textures-from-quadratic',scenario,bsp,'true','true']]]


def metrics(pid):
    """Owned client CPU seconds / working set; unavailable platforms return null."""
    if os.name != 'nt': return {}
    import ctypes as c
    from ctypes import wintypes as w
    class Memory(c.Structure):
        _fields_ = [('cb',w.DWORD),('faults',w.DWORD)]+[(x,c.c_size_t) for x in ('peak','working','quotaPeakPaged','quotaPaged','quotaPeakNonPaged','quotaNonPaged','pagefile','peakPagefile')]
    k = c.WinDLL('kernel32',use_last_error=True); ps = c.WinDLL('psapi',use_last_error=True)
    k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD]; k.OpenProcess.restype=w.HANDLE
    k.CloseHandle.argtypes=[w.HANDLE]; k.GetProcessTimes.argtypes=[w.HANDLE]+[c.POINTER(w.FILETIME)]*4
    ps.GetProcessMemoryInfo.argtypes=[w.HANDLE,c.POINTER(Memory),w.DWORD]
    h=k.OpenProcess(0x410,False,pid)
    if not h:return {}
    try:
        times=[w.FILETIME() for _ in range(4)]; m=Memory();m.cb=c.sizeof(m);r={}
        if k.GetProcessTimes(h,*[c.byref(t) for t in times]):r['cpu_seconds']=sum((t.dwHighDateTime<<32)+t.dwLowDateTime for t in times[2:])/1e7
        if ps.GetProcessMemoryInfo(h,c.byref(m),m.cb):r['working_set_bytes']=m.working
        return r
    finally:k.CloseHandle(h)


def tail_line(path):
    with Path(path).open('rb') as f:
        f.seek(max(0,Path(path).stat().st_size-8192)); lines=f.read().decode(errors='replace').splitlines()
    return next((s.strip() for s in reversed(lines) if s.strip()),'')[:500]


def scan_log(path):
    warnings=[]; fatal=[]; success=False; counts=0
    with Path(path).open(errors='replace') as f:
        for number,line in enumerate(f,1):
            if 'SUCCEEDED' in line:success=True
            if re.search(r'warning|assert|error',line,re.I):
                counts+=1
                if len(warnings)<100:warnings.append(dict(line=number,text=line.strip()[:1000]))
            if any(x in line for x in ('LIGHTMAPPER FAILED','### ASSERTION FAILED')):fatal.append(number)
    return dict(success_marker=success,warning_count=counts,warnings=warnings,fatal_lines=fatal)


def execute_group(commands, tool, kit, run, index, status, interval):
    rows=[]; start=time.monotonic(); handles=[]
    try:
        for i,argv in enumerate(commands):
            path=run/'logs'/f'{index:03}-{argv[0]}-{i}.log'; stream=path.open('xb');handles.append(stream)
            command=[str(tool),*argv]
            child=subprocess.Popen(command,cwd=kit,stdout=stream,stderr=stream,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            row=dict(stage=argv[0],pid=child.pid,command=command,command_text=subprocess.list2cmdline(command),log=str(path),start=now(),exit_code=None)
            rows.append((child,row));status['stages'].append(row)
        next_print=0
        while True:
            active=[]
            for child,row in rows:
                code=child.poll()
                if code is None:active.append(child.pid)
                elif row['exit_code'] is None:
                    row.update(exit_code=code,end=now(),duration_seconds=time.monotonic()-start)
                    row.update(scan_log(row['log']))
                    print(f"STAGE CLIENT COMPLETE {row['stage']} PID={child.pid} exit={code} log={row['log']}",flush=True)
                    if code or row['fatal_lines'] or not row['success_marker']:
                        raise RuntimeError(f"Failed stage {row['stage']}; exit={code}; log={row['log']}; command={row['command_text']}; missing-success/fatal={not row['success_marker'] or bool(row['fatal_lines'])}")
            samples=[metrics(p) for p in active]
            status.update(current_stage=commands[0][0],stage_elapsed_seconds=time.monotonic()-start,
                elapsed_seconds=time.time()-status['start_epoch'],active_client_count=len(active),pids=active,
                aggregate_cpu_seconds=sum(s.get('cpu_seconds',0) for s in samples),
                aggregate_working_set_bytes=sum(s.get('working_set_bytes',0) for s in samples),
                latest_progress=next((tail_line(row['log']) for _,row in reversed(rows) if Path(row['log']).stat().st_size),''),updated=now())
            if time.monotonic()>=next_print or not active:
                write(run/'status.json',status)
                with (run/'telemetry.jsonl').open('a',encoding='utf-8') as f:
                    f.write(json.dumps({k:v for k,v in status.items() if k!='stages'})+'\n')
                print(f"{status['current_stage']} total={status['elapsed_seconds']:.0f}s stage={status['stage_elapsed_seconds']:.0f}s clients={len(active)}/{status['workers']} PIDs={active} CPU={status['aggregate_cpu_seconds']:.1f}s RAM={status['aggregate_working_set_bytes']/1048576:.0f}MiB\nlogs={run/'logs'}\n{status['latest_progress']}",flush=True)
                next_print=time.monotonic()+interval
            if not active:break
            time.sleep(min(1,interval))
    finally:
        for child,row in rows:
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:child.kill();child.wait()
                row.update(exit_code=child.returncode,end=now(),duration_seconds=time.monotonic()-start,cancelled=True)
        for h in handles:h.close()
        write(run/'status.json',status)


def native(config, run, action, **extra):
    for path,digest in config.get('ImplementationHashes',{}).items():
        if sha(path)!=digest:raise ValueError('Runner/translator changed during run: '+path)
    name=action+'-'+secrets.token_hex(3); result=run/(name+'.json')
    request=dict(addon=str(REPO/'blender/addons/io_scene_foundry'),kit=config['HrekRoot'],scenario=config['Scenario'],
                 action=action,native_run=str(run/name),native_result=str(result),**extra)
    cfg=run/(name+'-config.json');write(cfg,request)
    cmd=[config['Blender'],'--background','--factory-startup','--python',str(HERE/'native.py'),'--',str(cfg)]
    log=run/'logs'/(name+'.log')
    started=time.monotonic()
    with log.open('xb') as f:
        process=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        print(f'NATIVE {action} PID={process.pid} log={log}',flush=True)
        try: process.wait()
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
    write(run/(name+'-operation.json'),dict(action=action,command=cmd,pid=process.pid,exit_code=process.returncode,
        duration_seconds=time.monotonic()-started,log=str(log),faux_started=False))
    if process.returncode or not result.exists():raise RuntimeError('Native worker failed: '+str(log))
    data=json.loads(result.read_text())
    if data['status']!='PASS':raise RuntimeError('Native verification failed: '+str(result))
    return data


def backup(root, run, before):
    for rel,digest in before.items():
        dest=safe_path(run/'backups',rel);dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(safe_path(root,rel),dest)
        if sha(dest)!=digest:raise ValueError('Backup checksum failed')
    if inventory(root)!=before:raise ValueError('Inputs changed during backup')
    write(run/'backup-manifest.json',dict(root=str(root),files=before))


def restore(run):
    """No blind rollback: validate complete candidate and backup before any write."""
    run=Path(run).resolve();cfg=json.loads((run/'config.json').read_text());root=Path(cfg['ProtectedRoot']).resolve()
    tags=(Path(cfg['HrekRoot'])/'tags').resolve()
    if root==tags or not root.is_relative_to(tags):raise ValueError('Restore root must stay in a dedicated kit tag namespace')
    manifest=json.loads((run/'backup-manifest.json').read_text())
    if Path(manifest['root']).resolve()!=root:raise ValueError('Restore scope differs from backup manifest')
    lock=Path(cfg['HrekRoot'])/'.foundry-manual-bake.lock'
    with exclusive(lock):
        require_idle_kit(cfg['HrekRoot'])
        before=json.loads((run/'hashes-before.json').read_text());after=json.loads((run/'hashes-after.json').read_text())
        if before!=manifest['files']:raise ValueError('Restore baseline differs from backup manifest')
        if inventory(root)!=after:raise ValueError('Restore refused: concurrent hash mismatch (or candidate changed during manual testing)')
        for rel,digest in before.items():
            if sha(safe_path(run/'backups',rel))!=digest:raise ValueError('Restore backup hash mismatch')
        # Recheck immediately before mutation. External editors must be closed.
        if inventory(root)!=after:raise ValueError('Restore refused: candidate changed during verification')
        for rel in sorted(after.keys()-before.keys()):safe_path(root,rel).unlink()
        for rel,digest in before.items():
            dest=safe_path(root,rel);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(safe_path(run/'backups',rel),dest)
        if inventory(root)!=before:raise RuntimeError('Restore readback mismatch')
        # Completed run remains immutable; restoration has a separate receipt.
        receipt=run.parent/(run.name+'-restore-'+secrets.token_hex(4)+'.json');write(receipt,dict(status='PASS',restored_run=str(run),utc=now()))
        print('RESTORED',receipt)


@contextlib.contextmanager
def exclusive(path):
    try:fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise ValueError('Kit is locked. No resume/stale-lock removal is automatic: '+str(path))
    token=json.dumps(dict(pid=os.getpid(),start=now(),token=secrets.token_hex(16))).encode()
    try:
        os.write(fd,token);os.close(fd);yield
    finally:
        if Path(path).exists() and Path(path).read_bytes()==token:Path(path).unlink()


def run(config):
    c={
        **dict(Mode='ValidateOnly',Bsp=['all'],Quality='low',Workers=1,LightGroup='',Name='manual',IntervalSeconds=30,OutputPolicy='Refuse',ConfirmInPlace=False),**config}
    if c['Mode'] not in MODES:raise ValueError('Unsupported mode')
    if c.get('Resume'):raise ValueError('Resume is not proven safe; use a new run/job')
    if c['Quality'] not in QUALITIES:raise ValueError('Unsupported quality')
    c['Scenario']=logical(c['Scenario']).removesuffix('.scenario')
    c['HrekRoot']=str(Path(c['HrekRoot']).resolve());kit=Path(c['HrekRoot']);tags=kit/'tags'
    if not (kit/'bin/ManagedBlam.dll').is_file():raise ValueError('Missing HREK ManagedBlam')
    c['Workers']=int(c['Workers']) # No Auto or implicit all-CPU dispatch.
    if not 1<=c['Workers']<=64:raise ValueError('Workers must be explicit 1..64 (runner guard, not engine maximum)')
    if not 1<=float(c['IntervalSeconds'])<=3600:raise ValueError('Invalid monitor interval')
    bake=c['Mode'] in ('BakeOnly','PrepareAndBake');prepare=c['Mode'] in ('PrepareOnly','PrepareAndBake')
    if prepare and not c.get('Plan'):raise ValueError('An accepted Plan is required for preparation')
    if c.get('OutputNamespace'):
        c['OutputNamespace']=logical(c['OutputNamespace'])
        if bake:raise ValueError('Prepare-only copies are not isolated bake scenarios')
    root=safe_path(tags,c['OutputNamespace'] if c.get('OutputNamespace') else str(Path(c['Scenario']).parent))
    if root==tags.resolve():raise ValueError('A dedicated scenario namespace is required')
    if (bake or (prepare and not c.get('OutputNamespace'))) and (c['OutputPolicy']!='GuardedInPlace' or c['ConfirmInPlace'] is not True):
        raise ValueError('Installed inputs/Medium may change: explicitly select GuardedInPlace and ConfirmInPlace')
    if c.get('OutputNamespace') and root.exists():raise ValueError('Prepare namespace must be NEW')
    c['ProtectedRoot']=str(root)
    runroot=Path(c['RunRoot']).resolve()
    if runroot.is_relative_to(kit) or kit.is_relative_to(runroot):raise ValueError('RunRoot must be outside the kit and not its ancestor')
    name=re.sub(r'[^A-Za-z0-9_-]+','-',str(c['Name'])).strip('-') or 'manual'
    runroot.mkdir(parents=True,exist_ok=True);out=runroot/(name+'-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+secrets.token_hex(4))
    out.mkdir(exist_ok=False);(out/'logs').mkdir()
    status=dict(status='PREFLIGHT',start=now(),start_epoch=time.time(),workers=c['Workers'],stages=[],run_directory=str(out))
    write(out/'config.json',c);write(out/'status.json',status)
    (out/'commands.txt').write_text('Preflight pending; no Faux command executed.\n',encoding='utf-8')
    print('RUN DIRECTORY:',out,flush=True)
    result=dict(status='FAIL',runtime_status='RUNTIME_TEST_PENDING',config=c,run_directory=str(out),start=status['start'])
    before=None;guarded=False
    allowed_changes=set(); output_refs=set()
    lock=exclusive(kit/'.foundry-manual-bake.lock'); acquired=False
    try:
        lock.__enter__(); acquired=True
        info=native(c,out,'inspect');indices,all_bsps=select_bsps(c['Bsp'],info['bsps'])
        q=[p for p in info['qualities'] if p['name']==c['Quality']]
        if len(q)!=1:raise ValueError('Quality absent or ambiguous in installed globals')
        expected_flags = 0 if c['Quality']=='direct_only' else 2 if c['Quality']=='draft' else 3
        if q[0]['flags'] != expected_flags:
            raise ValueError('Preset phase flags differ from supported pipeline; inspect before baking')
        result.update(indices=indices,preset=q[0])
        output_refs.update(info['output_dependencies'])
        # Shared BSP/lightmap references defeat namespace-only backup/isolation.
        scenario_root=safe_path(tags,str(Path(c['Scenario']).parent))
        for rel in info['bsps']+info['output_dependencies']:
            if not safe_path(tags,rel).resolve().is_relative_to(scenario_root.resolve()):
                raise ValueError('Shared/outside-namespace BSP or lightmap dependency: '+rel)
        for bsp,row in zip(info['bsps'],info['scenario_bsp_rows']):
            expected=bsp.rsplit('.',1)[0]+'.scenario_structure_lighting_info'
            if row.get('structure lighting_info')!=expected or row.get('local structure bsp') or row.get('local structure lighting_info'):
                raise ValueError('Nonstandard/shared BSP lighting identity is unsupported')
        tool=kit/'tool_fast.exe';binary=tool.read_bytes()
        groups=[];jobs=[]
        for bsp in (['all'] if all_bsps else [Path(info['bsps'][i]).stem for i in indices]):
            while True:
                job=secrets.randbelow(2147483646)+1
                if job not in jobs and not (kit/'faux'/str(job)).exists():break
            jobs.append(job);groups+=pipeline(c['Scenario'].replace('/','\\'),bsp,c['Quality'],c['Workers'],job,c['LightGroup'])
        for group in groups:
            for command in group:
                if not any(name.encode() in binary for name in (command[0],command[0].replace('-',' '))):
                    raise ValueError('Command absent from installed executable: '+command[0])
        c.update(Jobs=jobs,SelectedIndices=indices,QualitySettings=q[0]);write(out/'config.json',c)
        write(out/'stage-plan.json',groups)
        (out/'commands.txt').write_text('\n'.join(subprocess.list2cmdline([str(tool),*cmd]) for group in groups for cmd in group)+'\n',encoding='utf-8')
        result['translator_commit']=subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip()
        result['translator_dirty']=bool(subprocess.check_output(['git','-C',str(REPO),'status','--porcelain'],text=True).strip())
        pins={str(p):sha(p) for p in (tool,kit/'project.xml',tags/'globals/lightmapper_globals.lightmapper_globals')}
        if c.get('Plan'):pins[str(Path(c['Plan']).resolve())]=sha(c['Plan'])
        sources=list(HERE.glob('*.py'))+[REPO/'blender/addons/io_scene_foundry'/p for p in (
            'h3_import/port_environment/light_units.py','h3_import/port_environment/native_scene.py',
            'managed_blam/scenario_structure_lighting_info.py','managed_blam/__init__.py')]
        c['ImplementationHashes']={str(p):sha(p) for p in sources};pins.update(c['ImplementationHashes'])
        for source in sources:
            target=out/'implementation'/source.relative_to(REPO);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        write(out/'config.json',c)
        write(out/'engine-input-hashes.json',pins)
        before=inventory(root);write(out/'hashes-before.json',before)
        if prepare:
            for i in indices:
                source=info['bsps'][i].rsplit('.',1)[0]+'.scenario_structure_lighting_info'
                allowed_changes.add((c['OutputNamespace']+'/'+Path(source).name) if c.get('OutputNamespace') else source)
        if bake:
            allowed_changes.update(info['bsps'][i] for i in indices)
            allowed_changes.update([c['Scenario']+'.scenario',c['Scenario']+'_faux_data.scenario_faux_data',
                c['Scenario']+'_faux_probestore.probestore',c['Scenario']+'_faux_lightmap.scenario_lightmap'])
            # Native output verification supplies the selected final lightmap resources.
        if prepare or bake:
            if not c.get('OutputNamespace'):require_idle_kit(kit)
            backup(root,out,before);guarded=True
            (out/'Restore-Bake.ps1').write_text("param([string]$Python = 'python')\n& $Python '"+str(HERE/'runner.py').replace("'","''")+"' --restore '"+str(out).replace("'","''")+"'\nexit $LASTEXITCODE\n",encoding='utf-8')
        extra=dict(indices=indices,plan=c.get('Plan'),output_namespace=c.get('OutputNamespace'),probe=c.get('SolverProbe'))
        if prepare: result['preparation']=native(c,out,'prepare',**extra)
        elif c.get('Plan'):result['preparation']=native(c,out,'validate_inputs',**extra)
        if bake:
            if result.get('preparation') and any(not d['matches_corrected_authoring'] for row in result['preparation']['preparation'] for d in row['definitions']):
                raise ValueError('BakeOnly inputs do not match corrected authoring; run PrepareOnly first')
            status['status']='BAKING'
            for index,group in enumerate(groups):
                require_idle_kit(kit)
                if group[0][0]=='faux_farm_begin' and (kit/'faux'/group[0][-2]).exists():
                    raise ValueError('Job directory appeared before begin; refusing reuse')
                execute_group(group,tool,kit,out,index,status,float(c['IntervalSeconds']))
            result['native_output_verification']=native(c,out,'verify',indices=indices)
            output_refs=set(result['native_output_verification']['outputs']);allowed_changes.update(output_refs)
            for job in jobs:
                source=kit/'faux'/str(job)
                if not source.is_dir():raise ValueError('Completed job has no blob directory')
                shutil.copytree(source,out/'solver'/str(job))
            if c.get('SolverProbe'):
                from solver import verify
                probe=result['preparation'].get('solver_probe')
                if not probe:raise ValueError('SolverProbe BSP was not selected/prepared')
                job_index=0 if all_bsps else indices.index(int(c['SolverProbe']['Bsp']))
                result['solver_verification']=verify(out/'solver'/str(jobs[job_index])/'main.blob',probe)
        if any(sha(p)!=h for p,h in pins.items()):raise ValueError('Executable/project/quality globals changed during run')
        result['status']='PASS';result['baseline_preservation']='PRESERVED' if inventory(root)==before else 'CHANGED_CANDIDATE_LEFT_INSTALLED_BACKUP_VERIFIED'
        result['engine_inputs_preserved']=True
    except BaseException as e:
        result['error']=str(e);print('STOP:',e,flush=True)
    finally:
        try:
            if before is not None:
                after=inventory(root);write(out/'hashes-after.json',after);result['changed_files']=differences(before,after)
                result['lightmap_hashes']={k:v for k,v in after.items() if (root/k).relative_to(tags).as_posix() in output_refs}
                result['lighting_info_hashes']={k:v for k,v in after.items() if k.endswith('.scenario_structure_lighting_info')}
                result['unexpected_changes']=[r for r in result['changed_files'] if (root/r['path']).relative_to(tags).as_posix() not in allowed_changes]
                result['baseline_preservation']='PRESERVED' if not result['changed_files'] else 'CHANGED_CANDIDATE_LEFT_INSTALLED_BACKUP_VERIFIED' if guarded else 'UNEXPECTED_CHANGE'
                if result['unexpected_changes']:result.update(status='FAIL',preservation_error='Files outside expected output/preparation set changed; inspect before restoring')
        except Exception as e:
            result.update(status='FAIL',snapshot_error=str(e))
        result.update(end=now(),duration_seconds=time.time()-status['start_epoch'],stages=status['stages'],
            warnings_summary=[dict(stage=r['stage'],log=r['log'],count=r.get('warning_count',0)) for r in status['stages'] if r.get('warning_count')],
            backup_verified=guarded,faux_started=bool(status['stages']),resume_supported=False)
        result['native_operations']=[json.loads(p.read_text()) for p in sorted(out.glob('*-operation.json'))]
        result['solver_locations']=[str(kit/'faux'/str(job)) for job in c.get('Jobs',[])]
        status.update(status=result['status'],current_stage='COMPLETE' if result['status']=='PASS' else 'FAILED',end=result['end'],pids=[],active_client_count=0)
        try:
            write(out/'status.json',status);write(out/'result.json',result)
        finally:
            if acquired:lock.__exit__(None,None,None)
    print(result['status'],out,flush=True)
    if result['status']=='PASS':
        zone=('game_initial_zone_set '+c['InitialZoneSet']+'\n') if c.get('InitialZoneSet') else ''
        text="Launch reach_tag_test.exe from the HREK working directory. Console:\n"+zone+"game_start "+c['Scenario'].replace('/','\\')+"\nRuntime acceptance: RUNTIME_TEST_PENDING. Choose the scenario's appropriate zone set.\n"
        (out/'tag-test.txt').write_text(text,encoding='utf-8')
    return 0 if result['status']=='PASS' else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path);p.add_argument('--restore',type=Path);a=p.parse_args()
    try:
        if a.restore:restore(a.restore);code=0
        elif a.config:code=run(json.loads(a.config.read_text(encoding='utf-8-sig')))
        else:p.error('--config or --restore required')
    except Exception as e:print('STOP:',e,file=sys.stderr);code=1
    sys.exit(code)
