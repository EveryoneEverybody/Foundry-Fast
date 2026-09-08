"""Conservative reuse of completed native object batches."""


def verify_reuse(receipt,plan,current_files,retry_sources=None):
    if receipt['status']!='COMPLETE' or receipt['plan_sha256']!=plan['plan_sha256']:
        raise ValueError('Prior native receipt is incomplete or from another plan')
    files={r['path']:r['sha256'] for r in receipt['generated_files']}
    if not files or any(current_files.get(p)!=h for p,h in files.items()):
        raise ValueError('Prior native receipt outputs changed or are missing')
    rows=receipt['worker']['objects'];known={r['source_tag'] for r in rows}
    expected={r['source_tag']:r['target_tag'] for r in plan['objects'] if r['plan_status']=='READY_FOR_NATIVE'}
    if known!=expected.keys() or len(known)!=len(rows):raise ValueError('Retry requires complete source accounting')
    if any(r['status'] not in {'NATIVE_COMPILED','DEFERRED'} or r['target_tag']!=expected[r['source_tag']] for r in rows):
        raise ValueError('Prior object results are incomplete or have different native identities')
    if retry_sources and set(retry_sources)-known:raise ValueError('Retry identities absent from prior batch')
    return len(files)
