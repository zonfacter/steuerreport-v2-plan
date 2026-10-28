"""Ausfuehrbarer RO-Audit; Einzelbelege nur in neuer privater Untermappe."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from parity_probe import compare, file_identity, packed, snapshot, tag


HERE = Path(__file__).resolve().parent


def private_json(root,name,obj):
    fd=os.open(root/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w") as handle:
        json.dump(obj,handle,indent=2,sort_keys=True)
        handle.write("\n")


def command(args,content=None):
    result=subprocess.run(args,input=content,text=True,capture_output=True,timeout=300)
    if result.returncode:
        raise RuntimeError("subprocess_failed_without_public_stderr")
    return result.stdout


def process(pid):
    root=Path('/proc')/str(pid)
    env=dict(x.split('=',1) for x in (root/'environ').read_bytes().decode().split('\0') if '=' in x)
    allowed=('STEUERREPORT_DB_PATH','STEUERREPORT_V2_DB','STEUERREPORT_V2_ROOT','PYTHONPATH','HOME')
    record={'pid':pid,'cwd':os.readlink(root/'cwd'),'cmdline':(root/'cmdline').read_bytes().decode().split('\0')[:-1],
            'starttime_ticks':(root/'stat').read_text().rsplit(')',1)[1].split()[19],
            'cgroup':(root/'cgroup').read_text(),'environment':{k:env[k] for k in allowed if k in env},'fd_matches':[]}
    for fd in (root/'fd').iterdir():
        try:
            target=os.readlink(fd)
            if not any(x in target for x in ('.duckdb','.db','.sqlite','.wal')):
                continue
            identity=file_identity(fd)
            matched=Path(target).is_file() and file_identity(target)['inode']==identity['inode'] and file_identity(target)['device']==identity['device']
            record['fd_matches'].append({'fd':fd.name,'path':target,'identity':identity,'named_path_same_inode':matched})
        except OSError:
            pass
    record['mapped_database_paths']=[line.rsplit(' ',1)[-1] for line in (root/'maps').read_text().splitlines() if '.duckdb' in line or 'steuerreport.db' in line]
    return record


def passive(pids,seconds):
    end=time.monotonic()+seconds; samples=0;hits={}
    while time.monotonic()<end:
        samples+=1
        for pid in pids:
            for fd in (Path('/proc')/str(pid)/'fd').iterdir():
                try:
                    name=os.readlink(fd)
                    if '.duckdb' in name:
                        s=fd.stat();hits[(pid,fd.name,name)]=(s.st_dev,s.st_ino)
                except OSError:
                    pass
        time.sleep(.02)
    return {'samples':samples,'seconds':seconds,'hits':[{'pid':p,'fd':f,'path':n,'device':v[0],'inode':v[1]} for (p,f,n),v in hits.items()]}


def source_documents(base):
    names=['Docker-Nachpruefung-18010-2026-10-28.md','BMF-Quellenpruefung-2026-10-28.md',
           'v1-baseline-evidence-2026-10-28/manifest.json','v1-baseline-evidence-2026-10-28/reproduce_v1.py',
           'v1-baseline-evidence-2026-10-28/results.json','v2-baseline-evidence-2026-10-28/README.md',
           'v2-baseline-evidence-2026-10-28/source-manifest.json','v2-baseline-evidence-2026-10-28/reproduce.py',
           'v2-baseline-evidence-2026-10-28/results.json']
    return {name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in names}


def stable(a,b):
    return (a['tables']==b['tables'] and a['archive_file_bag']==b['archive_file_bag'] and
            a['database_identity']==b['database_identity'] and a['sidecars_before']==b['sidecars_after'])


def audit(args):
    os.umask(0o077)
    root=Path(args.private_root).resolve()
    root.mkdir(mode=0o700,parents=True,exist_ok=False)
    key=os.urandom(32)
    descriptor=os.open(root/'hmac.key',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as handle:
        handle.write(key)
    started=datetime.now(timezone.utc).isoformat()
    sources=source_documents(Path(args.user_sources))
    v1=process(args.v1_pid);v2=process(args.v2_pid)
    container=json.loads(command(['docker','inspect',args.container]))[0]
    env=dict(x.split('=',1) for x in container['Config']['Env'] if '=' in x)
    db_inside=env['STEUERREPORT_V2_DB']
    observation=passive([args.v2_pid,container['State']['Pid']],args.sample_seconds)
    private_json(root,'process-before.json',{'v1':v1,'v2':v2,'passive':observation})
    v1_path=v1['environment'].get('STEUERREPORT_DB_PATH')
    if not v1_path or not any(x['path']==v1_path and x['named_path_same_inode'] for x in v1['fd_matches']):
        raise RuntimeError('v1_runtime_identity_not_confirmed')
    candidate=Path(args.v2_candidate).resolve(strict=True)
    observed_v2=any(x['path']==str(candidate) and x['named_path_same_inode'] for x in v2['fd_matches']) or any(
        x['pid']==args.v2_pid and x['path']==str(candidate) and (x['device'],x['inode'])==
        (candidate.stat().st_dev,candidate.stat().st_ino) for x in observation['hits'])
    mounted=[m for m in container['Mounts'] if m['Destination']=='/state']
    if len(mounted)!=1 or not Path(db_inside).is_relative_to('/state'):
        raise RuntimeError('docker_state_mount_ambiguous')
    docker_host_path=Path(mounted[0]['Source'])/Path(db_inside).relative_to('/state')
    docker_pid_path=Path('/proc')/str(container['State']['Pid'])/'root'/Path(db_inside).relative_to('/')
    identity=file_identity(docker_host_path)
    if (identity['device'],identity['inode'])!=(file_identity(docker_pid_path)['device'],file_identity(docker_pid_path)['inode']):
        raise RuntimeError('docker_mount_inode_mismatch')
    container_config_before=tag(key,{k:container[k] for k in ('Id','Image','Config','HostConfig','Mounts')})
    docker_meta={'id':container['Id'],'image_id':container['Image'],'pid':container['State']['Pid'],
        'started_at':container['State']['StartedAt'],'database_path':db_inside,'host_database_path':str(docker_host_path),
        'database_identity':identity,'mount':{k:mounted[0].get(k) for k in ('Name','Type','Destination')},
        'process_root_same_inode':True}
    private_json(root,'docker-identity.json',docker_meta)
    core=(HERE/'parity_probe.py').read_text()
    driver="\nprint(json.dumps(snapshot("+repr(db_inside)+",'duckdb-v2',bytes.fromhex("+repr(key.hex())+")),sort_keys=True))\n"

    def docker_snapshot():
        # Code nur ueber stdin, kein Schreiben/Copieren in den Container.
        return json.loads(command(['docker','exec','-i',args.container,'python','-'],core+driver))

    before={}
    before['v1-live']=snapshot(v1_path,'sqlite-v1',key)
    private_json(root,'v1-before.json',before['v1-live'])
    before['v2-candidate']=snapshot(candidate,'duckdb-v2',key)
    private_json(root,'v2-candidate-before.json',before['v2-candidate'])
    before['docker-live']=docker_snapshot()
    private_json(root,'docker-before.json',before['docker-live'])
    results={'v1_vs_docker':compare(before['v1-live'],before['docker-live']),
             'v2_candidate_vs_docker':compare(before['v2-candidate'],before['docker-live'])}
    private_json(root,'comparisons.json',results)
    after={'v1-live':snapshot(v1_path,'sqlite-v1',key),'v2-candidate':snapshot(candidate,'duckdb-v2',key),
           'docker-live':docker_snapshot()}
    for name,value in after.items():
        private_json(root,name+'-after.json',value)
    after_v1,after_v2=process(args.v1_pid),process(args.v2_pid)
    private_json(root,'process-after.json',{'v1':after_v1,'v2':after_v2})
    container_after=json.loads(command(['docker','inspect',args.container]))[0]
    config_unchanged=container_config_before==tag(key,{k:container_after[k] for k in ('Id','Image','Config','HostConfig','Mounts')})
    summary={'started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),
        'private_evidence_root':str(root),'private_key_published':False,
        'v1_runtime_identity_confirmed':True,'v2_candidate_runtime_identity_confirmed':observed_v2,
        'docker_mount_identity_confirmed':True,'v2_runtime_limit':None if observed_v2 else
        'No observed fd/mmap binding. Default source path is a candidate, not proof of loaded module/global state.',
        'no_database_or_schema_api_get':True,'no_database_file_copy':True,
        'all_table_and_archive_fingerprints_stable':{name:stable(before[name],after[name]) for name in before},
        'file_metadata_unchanged_during_reads':{name:before[name]['file_metadata_unchanged_during_read'] and after[name]['file_metadata_unchanged_during_read'] for name in before},
        'process_identities_unchanged':all(beforep['starttime_ticks']==afterp['starttime_ticks'] and beforep['cwd']==afterp['cwd'] and beforep['environment']==afterp['environment'] for beforep,afterp in ((v1,after_v1),(v2,after_v2))),
        'docker_configuration_and_start_unchanged':config_unchanged and container_after['State']['StartedAt']==container['State']['StartedAt'],
        'sources_unchanged':sources==source_documents(Path(args.user_sources)),
        'source_document_sha256':sources,'datasets':{},'comparisons':results,
        'engine_parity_proven':False}
    for name,data in before.items():
        summary['datasets'][name]={'backend':data['backend'],'dimensions':data['dimensions'],
            'tables':{table:{'count':value['strict']['count'],'strict_hmac':value['strict']['hmac_sha256'],
                            'semantic_hmac':value['semantic']['hmac_sha256']} for table,value in data['tables'].items()},
            'archive_file_count':data['archive_file_bag']['count'],'notes':data['notes'],
            'v1_payload_shape_counts':data.get('v1_payload_shape_counts')}
    private_json(root,'summary.json',summary)
    # Nur Aggregate/HMACs, niemals Rowbags, Pfade zu Kontodateien oder Werte.
    Path(args.public_output).write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':'finished','v1_identity':True,'v2_runtime_identity':observed_v2,
        'stable':summary['all_table_and_archive_fingerprints_stable'],
        'engine_parity_proven':False,'summary':args.public_output}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--private-root',required=True)
    p.add_argument('--public-output',required=True)
    p.add_argument('--user-sources',default='/tmp/steuerreport-migration-20261028-coordinator/docs/blockpit-analysis')
    p.add_argument('--v1-pid',type=int,default=158)
    p.add_argument('--v2-pid',type=int,default=3145184)
    p.add_argument('--v2-candidate',default='/workspace/steuerreport-v2-plan/data/steuerreport_v2.duckdb')
    p.add_argument('--container',default='steuerreport-v2-lan')
    p.add_argument('--sample-seconds',type=float,default=30)
    audit(p.parse_args())
