#!/usr/bin/env python3
"""레퍼런스 수집·판정 (유튜브 롱폼/쇼츠 · 인스타 릴스, 국내·해외).

상태 흐름: 포착 → 검수대기(기준 통과) → 촬영대기(사람이 고름) → 완료 / 제외
저장: reels/data/refs.jsonl (한 줄 = 레퍼런스 1개)

  python3 reels/scripts/collect.py youtube [--fit 유이선생] [--region KR|GLOBAL] [--period week|month]
  python3 reels/scripts/collect.py instagram [--fit 채널] # APIFY_TOKEN 필요, 채널별 instagram.accounts/hashtags
  python3 reels/scripts/collect.py tiktok [--fit 채널]    # APIFY_TOKEN 필요, 채널별 tiktok.keywords
  python3 reels/scripts/collect.py add <url> [--fit 채널] # 우연히 본 링크 1개 직접 추가 (유튜브·틱톡·인스타)
  python3 reels/scripts/collect.py score                 # 배수·참여율 다시 계산해 상태 갱신
  python3 reels/scripts/collect.py list [--status 검수대기] [--fit 채널] [--region KR]
  python3 reels/scripts/collect.py set <id> --status 촬영대기 [--note "…"]
  python3 reels/scripts/collect.py selftest              # 네트워크 없이 판정 로직 점검

필요: pip install yt-dlp  (인스타는 환경변수 APIFY_TOKEN)
수치는 수집 시점 값이다. 지어내지 않는다 — 못 얻은 값은 null 로 둔다.
"""
import argparse, datetime as dt, json, os, re, statistics, sys, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CFG = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))
DB = os.path.join(ROOT, 'data', 'refs.jsonl')
TODAY = dt.date.today().isoformat()


def load():
    if not os.path.exists(DB):
        return {}
    return {r['id']: r for r in (json.loads(l) for l in open(DB, encoding='utf-8') if l.strip())}


def save(refs):
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    with open(DB, 'w', encoding='utf-8') as f:
        for r in sorted(refs.values(), key=lambda r: (r.get('collected_at', ''), r['id'])):
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def judge(r):
    """배수(outlier)·참여율 계산 → 상태 결정. 사람이 정한 상태(촬영대기·완료·제외)는 건드리지 않는다."""
    t = CFG['thresholds']
    v = r.get('views') or 0
    base = r.get('author_median_views') or r.get('author_followers')
    r['outlier'] = round(v / base, 1) if base else None
    r['outlier_basis'] = '채널 중앙값 조회수' if r.get('author_median_views') else ('구독자/팔로워' if r.get('author_followers') else None)
    inter = [x for x in (r.get('likes'), r.get('comments')) if x is not None]
    r['engagement'] = round(sum(inter) / v, 4) if v and inter else None
    reasons = []
    if r['engagement'] is not None and r['engagement'] < t['min_engagement']:
        reasons.append(f"참여율 {r['engagement']:.2%} < {t['min_engagement']:.1%} (광고·부풀리기 의심)")
        ok = False
    else:
        reg = r.get('region', 'KR')
        hit_out = r['outlier'] is not None and r['outlier'] >= t['min_outlier'] and v >= t['min_views_for_outlier'][reg]
        hit_big = v >= t['big_views'][reg]
        ok = hit_out or hit_big
        if hit_out: reasons.append(f"평소의 {r['outlier']}배 ({r['outlier_basis']})")
        if hit_big: reasons.append(f"조회 {v:,} ≥ {t['big_views'][reg]:,}")
        if r['engagement'] is None: reasons.append('참여 수치 미확인 — 검수 때 확인')
        if not ok: reasons.append('기준 미달')
    r['judge'] = ' · '.join(reasons)
    ca = t['carousel_auto']
    r['carousel_candidate'] = bool(ok and (r['outlier'] or 0) >= ca['min_outlier'] and (r.get('comments') or 0) >= ca['min_comments'])
    if r.get('status') in (None, '포착', '검수대기'):
        r['status'] = '검수대기' if ok else '포착'
    return r


def upsert(refs, r):
    old = refs.get(r['id'], {})
    keep = {k: old[k] for k in ('status', 'note', 'fit', 'collected_at', 'topic_ko') if k in old}
    if old.get('status') in ('포착', '검수대기'): keep.pop('status')
    merged = {**old, **{k: v for k, v in r.items() if v is not None}, **keep}
    merged.setdefault('collected_at', TODAY)
    merged['updated_at'] = TODAY
    refs[r['id']] = judge(merged)


# ---------------- YouTube (yt-dlp) ----------------
def ydl(opts=None):
    import yt_dlp
    return yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True, **(opts or {})})


def yt_search(query, period, n):
    sp = CFG['youtube']['period_sp'][period]
    url = f'https://www.youtube.com/results?search_query={urllib.request.quote(query)}&sp={sp}'
    try:
        info = ydl({'extract_flat': True, 'playlistend': n}).extract_info(url, download=False)
        ents = [e for e in (info.get('entries') or []) if e and e.get('id')]
    except Exception as e:
        print(f'  ! 기간 필터 검색 실패({e.__class__.__name__}) → 일반 검색으로 대체', file=sys.stderr)
        ents = []
    if not ents:
        info = ydl({'extract_flat': True}).extract_info(f'ytsearch{n}:{query}', download=False)
        ents = [e for e in (info.get('entries') or []) if e and e.get('id')]
    return ents[:n]


_median_cache = {}
def yt_channel_median(channel_id, short):
    key = (channel_id, short)
    if key in _median_cache: return _median_cache[key]
    med = None
    try:
        tab = 'shorts' if short else 'videos'
        info = ydl({'extract_flat': True, 'playlistend': CFG['youtube']['channel_sample']}).extract_info(
            f'https://www.youtube.com/channel/{channel_id}/{tab}', download=False)
        vs = [e['view_count'] for e in (info.get('entries') or []) if e and e.get('view_count')]
        if len(vs) >= 5: med = int(statistics.median(vs))
    except Exception as e:
        print(f'  ! 채널 중앙값 실패 {channel_id}: {e.__class__.__name__}', file=sys.stderr)
    _median_cache[key] = med
    return med


def yt_detail(vid):
    i = ydl().extract_info(f'https://www.youtube.com/watch?v={vid}', download=False)
    dur = i.get('duration') or 0
    short = dur and dur <= 180 and (i.get('width') or 0) <= (i.get('height') or 1)
    up = i.get('upload_date')
    return {
        'id': f'yt_{vid}', 'platform': 'youtube_shorts' if short else 'youtube',
        'url': f'https://www.youtube.com/shorts/{vid}' if short else f'https://www.youtube.com/watch?v={vid}',
        'title': i.get('title'), 'author': i.get('channel') or i.get('uploader'), 'author_id': i.get('channel_id'),
        'author_followers': i.get('channel_follower_count'), 'views': i.get('view_count'), 'likes': i.get('like_count'),
        'comments': i.get('comment_count'), 'duration': dur, 'uploaded': f'{up[:4]}-{up[4:6]}-{up[6:]}' if up else None,
        'thumb': f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg', 'lang': i.get('language'),
        'author_median_views': yt_channel_median(i['channel_id'], short) if i.get('channel_id') else None,
    }


def cmd_youtube(a):
    refs = load()
    jobs = []
    for fit, c in CFG['channels'].items():
        if a.fit and fit != a.fit: continue
        for reg, key in (('KR', 'kr'), ('GLOBAL', 'global')):
            if a.region and reg != a.region: continue
            jobs += [(fit, reg, q) for q in c.get(key, [])]
    if not a.fit:
        jobs += [(None, 'KR', q) for q in CFG['hot_any_field']['kr']] + [(None, 'GLOBAL', q) for q in CFG['hot_any_field']['global']]
    y = CFG['youtube']
    for fit, reg, q in jobs:
        print(f'[{reg}] {fit or "전 분야"} · {q}')
        try:
            ents = yt_search(q, a.period, y['per_query'])
        except Exception as e:
            print(f'  ! 검색 실패: {e}', file=sys.stderr); continue
        ents = sorted(ents, key=lambda e: e.get('view_count') or 0, reverse=True)[:y['detail_top']]
        for e in ents:
            try:
                r = yt_detail(e['id'])
            except Exception as ex:
                print(f"  ! 상세 실패 {e['id']}: {ex.__class__.__name__}", file=sys.stderr); continue
            r.update(region=reg, source=f'키워드:{q}')
            if fit: r['fit'] = fit
            upsert(refs, r)
            x = refs[r['id']]
            print(f"  {x['status']:<4} {x.get('outlier') or '-':>6}배  {x.get('views') or 0:>10,}  {x['title'][:40]}", flush=True)
    for k, v in load().items(): refs.setdefault(k, v)   # 수집 도중 다른 창에서 추가된 링크 보존
    save(refs); summary(refs)


# ---------------- Instagram (Apify) ----------------
def apify(actor, payload):
    tok = os.environ.get('APIFY_TOKEN')
    if not tok: sys.exit('APIFY_TOKEN 환경변수가 없습니다. (apify.com → Settings → API tokens)  인스타는 건너뛰거나 `add <url>` 로 직접 넣으세요.')
    req = urllib.request.Request(
        f'https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={tok}',
        data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=600))


def g(d, *keys):
    for k in keys:
        if d.get(k) not in (None, ''): return d[k]


def ig_item(it, reg, source):
    code = g(it, 'shortCode', 'shortcode', 'code')
    if not code: return None
    views = g(it, 'videoPlayCount', 'videoViewCount', 'playCount')
    likes = g(it, 'likesCount', 'likeCount')
    return {
        'id': f'ig_{code}', 'platform': 'instagram', 'region': reg, 'source': source,
        'url': g(it, 'url') or f'https://www.instagram.com/reel/{code}/', 'title': (g(it, 'caption') or '')[:300],
        'author': g(it, 'ownerUsername', 'username'), 'author_followers': g(it, 'ownerFollowersCount', 'followersCount'),
        'views': views, 'likes': likes if (likes or 0) >= 0 else None, 'comments': g(it, 'commentsCount', 'commentCount'),
        'duration': g(it, 'videoDuration'), 'uploaded': (g(it, 'timestamp') or '')[:10] or None,
        'thumb': g(it, 'displayUrl', 'thumbnailUrl'), 'transcript_hint': g(it, 'transcript'),
    }


def to_hashtag(s):
    """유튜브 검색어 → 인스타 해시태그: 공백·기호 제거, '쇼츠/shorts' 같은 플랫폼 단어 제거."""
    import re as _re
    s = _re.sub(r'(?i)\b(shorts?|youtube|유튜브|쇼츠|릴스|영상)\b', ' ', s)
    s = _re.sub(r'[^\w가-힣]', '', s)
    return s.lower()[:30]


def plat_keywords(c, plat, reg):
    """채널 c 의 플랫폼별 키워드. 인스타(해시태그)·틱톡(검색어)이 비어 있으면 유튜브 키워드를 기본으로 쓴다.
    반환: (키워드 목록, 유튜브에서 가져왔는지)"""
    key = 'hashtags' if plat == 'instagram' else 'keywords'
    own = [x.strip() for x in (((c.get(plat) or {}).get(key) or {}).get(reg) or []) if str(x).strip()]
    if own:
        return own, False
    yt = c.get('kr' if reg == 'KR' else 'global') or []
    if plat == 'instagram':
        yt = list(dict.fromkeys(h for h in (to_hashtag(x) for x in yt) if len(h) >= 2))
    return yt, True


def ig_sources(fit=None):
    """수집 대상 묶음 [(채널 또는 None, 지역, 계정 목록, 해시태그 목록)].
    채널별 목록은 config.json channels[채널].instagram = {"accounts": {"GLOBAL": [], "KR": []}, "hashtags": {...}},
    채널을 정하지 않은 공용 목록은 config.json instagram.accounts / hashtags."""
    out = []
    pools = [(None, CFG['instagram'])] if not fit else []
    pools += [(ch, c.get('instagram') or {}) for ch, c in CFG['channels'].items() if not fit or ch == fit]
    for ch, ig in pools:
        for reg in ('GLOBAL', 'KR'):
            accs = [x.lstrip('@').strip() for x in ((ig.get('accounts') or {}).get(reg) or []) if x.strip()]
            tags = [x.lstrip('#').strip() for x in ((ig.get('hashtags') or {}).get(reg) or []) if x.strip()]
            if ch and not tags:                       # 채널 전용 해시태그가 없으면 유튜브 키워드에서 기본 생성
                tags, _ = plat_keywords(CFG['channels'][ch], 'instagram', reg)
            if accs or tags: out.append((ch, reg, accs, tags))
    return out


def cmd_instagram(a):
    refs, ig = load(), CFG['instagram']
    srcs = ig_sources(a.fit)
    if not srcs: sys.exit('수집할 인스타그램 계정·해시태그가 없습니다. 대시보드 「인스타그램」 탭에서 계정이나 해시태그를 먼저 저장하세요.')
    got = []
    for ch, reg, accs, tags in srcs:
        if accs:
            print(f'[{reg}] {ch or "공용"} · 계정 {len(accs)}개: {", ".join(accs)}', flush=True)
            items = apify(ig['actor_reels'], {'username': accs, 'resultsLimit': ig['results_per_account']})
            got += [dict(x, fit=ch) for x in (ig_item(it, reg, '계정') for it in items) if x]
        if tags:
            for tag in tags:                 # 해시태그마다 따로 불러 진행률과 수집 경로를 남긴다
                print(f'[{reg}] {ch or "공용"} · #{tag}', flush=True)
                try:
                    items = apify(ig['actor_hashtag'], {'hashtags': [tag], 'resultsType': 'reels', 'resultsLimit': ig['results_per_account']})
                except Exception as e:
                    print(f'  ! 수집 실패: {str(e)[:120]}', file=sys.stderr, flush=True); continue
                got += [dict(x, fit=ch) for x in (ig_item(it, reg, f'해시태그:{tag}') for it in items) if x]
    if not got: sys.exit('가져온 릴스가 없습니다. 계정 이름·해시태그 철자와 Apify 실행 한도를 확인하세요.')
    by = {}
    for r in got:
        if r.get('views'): by.setdefault(r['author'], []).append(r['views'])
    for r in got:
        vs = by.get(r['author'], [])
        if len(vs) >= 5: r['author_median_views'] = int(statistics.median(vs))
        upsert(refs, r)
    print(f'릴스 {len(got)}건 반영', flush=True)
    for k, v in load().items(): refs.setdefault(k, v)   # 수집 도중 다른 창에서 추가된 링크 보존
    save(refs); summary(refs)


# ---------------- TikTok (Apify) ----------------
def tt_item(it, reg, source):
    vid = str(it.get('id') or '')
    if not vid or it.get('errorCode'): return None
    am, vm = it.get('authorMeta') or {}, it.get('videoMeta') or {}
    return {
        'id': f'tt_{vid}', 'platform': 'tiktok', 'region': reg, 'source': source,
        'url': it.get('webVideoUrl') or f"https://www.tiktok.com/@{am.get('name', '_')}/video/{vid}",
        'title': (it.get('text') or '')[:300], 'author': am.get('name'), 'author_followers': am.get('fans'),
        'views': it.get('playCount'), 'likes': it.get('diggCount'), 'comments': it.get('commentCount'),
        'duration': vm.get('duration'), 'uploaded': (it.get('createTimeISO') or '')[:10] or None, 'thumb': vm.get('coverUrl'),
    }


def cmd_tiktok(a):
    """채널별 틱톡 검색어(config.json channels[채널].tiktok.keywords = {"GLOBAL": [], "KR": []})로 수집."""
    refs, tt = load(), CFG.get('tiktok') or {'actor': 'clockworks~tiktok-scraper', 'results_per_query': 15}
    got, n = [], 0
    for ch, c in CFG['channels'].items():
        if a.fit and ch != a.fit: continue
        for reg in ('GLOBAL', 'KR'):
            kws, inherited = plat_keywords(c, 'tiktok', reg)
            if inherited and kws: print(f'[{reg}] {ch}: 틱톡 키워드가 없어 유튜브 키워드 {len(kws)}개를 기본으로 씁니다', flush=True)
            for q in kws:
                n += 1
                print(f'[{reg}] {ch} · {q}', flush=True)
                try:
                    items = apify(tt['actor'], {'searchQueries': [q], 'resultsPerPage': tt['results_per_query'],
                                                'shouldDownloadVideos': False, 'shouldDownloadCovers': False})
                except Exception as e:
                    print(f'  ! 검색 실패: {str(e)[:120]}', file=sys.stderr, flush=True); continue
                rows = [dict(x, fit=ch) for x in (tt_item(it, reg, f'키워드:{q}') for it in items) if x]
                print(f'  {len(rows)}건', flush=True)
                got += rows
    if not n: sys.exit('수집할 틱톡 키워드가 없습니다. 대시보드 「틱톡」 탭에서 키워드를 먼저 저장하세요.')
    if not got: sys.exit('가져온 틱톡 영상이 없습니다. 키워드와 Apify 실행 한도를 확인하세요.')
    for r in got: upsert(refs, r)
    print(f'틱톡 {len(got)}건 반영', flush=True)
    for k, v in load().items(): refs.setdefault(k, v)   # 수집 도중 다른 창에서 추가된 링크 보존
    save(refs); summary(refs)


def generic_detail(url):
    """틱톡 등 yt-dlp 가 읽는 단일 영상의 공개 수치. 못 얻은 값은 None."""
    i = ydl().extract_info(url, download=False)
    up = i.get('upload_date')
    return {'title': (i.get('title') or i.get('description') or '')[:300], 'author': i.get('uploader') or i.get('channel'),
            'author_followers': i.get('channel_follower_count'), 'views': i.get('view_count'), 'likes': i.get('like_count'),
            'comments': i.get('comment_count'), 'duration': i.get('duration'),
            'uploaded': f'{up[:4]}-{up[4:6]}-{up[6:]}' if up else None, 'thumb': i.get('thumbnail')}


# ---------------- 수동 추가 / 조회 ----------------
def cmd_add(a):
    refs = load()
    u = a.url
    m = re.search(r'(?:v=|shorts/|youtu\.be/)([\w-]{11})', u)
    if m:
        try:
            r = yt_detail(m.group(1))
        except Exception as e:
            print(f'! 수치 조회 실패({e.__class__.__name__}) — 링크만 저장', file=sys.stderr)
            r = {'id': f'yt_{m.group(1)}', 'platform': 'youtube', 'url': u}
    else:
        t = re.search(r'tiktok\.com/.*?/video/(\d+)', u)
        m = re.search(r'instagram\.com/(?:reels?|p)/([\w-]+)', u)
        if t:
            r = {'id': f'tt_{t.group(1)}', 'platform': 'tiktok', 'url': u}
            try:
                r.update(generic_detail(u))
            except Exception as e:
                print(f'! 수치 조회 실패({e.__class__.__name__}) — 링크만 저장', file=sys.stderr)
        elif m:
            r = {'id': f'ig_{m.group(1)}', 'platform': 'instagram', 'url': u}
            try:
                r.update(generic_detail(u))   # 공개 릴스면 조회·좋아요를 얻는다 (로그인 벽이면 링크만 저장)
            except Exception as e:
                print(f'! 수치 조회 실패({e.__class__.__name__}) — 링크만 저장', file=sys.stderr)
        else:
            sys.exit('유튜브 · 틱톡(/video/) · 인스타 /reel/ · /p/ 링크만 지원합니다.')
    r.update(region=a.region or 'GLOBAL', source='직접 추가')
    if a.fit: r['fit'] = a.fit
    upsert(refs, r)
    refs[r['id']]['status'] = '검수대기'   # 사람이 고른 링크는 기준과 무관하게 검수 대기
    save(refs); print(json.dumps(refs[r['id']], ensure_ascii=False, indent=1))


def cmd_score(a):
    refs = load()
    for r in refs.values(): judge(r)
    save(refs); summary(refs)


def cmd_list(a):
    rows = [r for r in load().values() if (not a.status or r.get('status') == a.status)
            and (not a.fit or r.get('fit') == a.fit) and (not a.region or r.get('region') == a.region)]
    rows.sort(key=lambda r: r.get('outlier') or 0, reverse=True)
    for r in rows[:a.n]:
        print(f"{r['id']:<18} {r['status']:<4} {str(r.get('outlier') or '-'):>6}배 {r.get('views') or 0:>11,} "
              f"{r.get('region','')[:2]} {r.get('fit') or '-':<6} {'🎠' if r.get('carousel_candidate') else '  '} {(r.get('title') or '')[:44]}")
    print(f'({len(rows)}건)')


def cmd_set(a):
    refs = load()
    if a.id not in refs: sys.exit('없는 id')
    if a.status: refs[a.id]['status'] = a.status
    if a.note: refs[a.id]['note'] = a.note
    if a.fit: refs[a.id]['fit'] = a.fit
    if a.topic: refs[a.id]['topic_ko'] = a.topic
    save(refs); print(refs[a.id]['id'], refs[a.id]['status'])


def summary(refs):
    c = {}
    for r in refs.values(): c[r['status']] = c.get(r['status'], 0) + 1
    print('합계:', ' · '.join(f'{k} {v}' for k, v in c.items()), f"· 캐러셀 후보 {sum(1 for r in refs.values() if r.get('carousel_candidate'))}")


def cmd_selftest(a):
    cases = [
        ({'views': 3080000, 'author_median_views': 10000, 'likes': 90000, 'comments': 1200, 'region': 'GLOBAL'}, '검수대기', True),
        ({'views': 900000, 'author_median_views': 800000, 'likes': 900, 'comments': 20, 'region': 'KR'}, '포착', False),   # 참여율 미달
        ({'views': 40000, 'author_followers': 3000, 'likes': 1500, 'comments': 60, 'region': 'KR'}, '검수대기', False),
        ({'views': 8000, 'author_median_views': 500, 'likes': 300, 'comments': 5, 'region': 'KR'}, '포착', False),          # 최소 조회 미달
        ({'views': 2000000, 'region': 'GLOBAL'}, '검수대기', False),                                                         # 수치 미확인이지만 대형
    ]
    for r, st, car in cases:
        j = judge(dict(r, id='t'))
        assert j['status'] == st and j['carousel_candidate'] == car, (r, j)
        print('ok', st, j['outlier'], j['judge'])
    print('selftest 통과')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('youtube'); p.add_argument('--fit'); p.add_argument('--region', choices=['KR', 'GLOBAL']); p.add_argument('--period', default='week', choices=['day', 'week', 'month', 'year'])
    p = sp.add_parser('instagram'); p.add_argument('--fit')
    p = sp.add_parser('tiktok'); p.add_argument('--fit')
    p = sp.add_parser('add'); p.add_argument('url'); p.add_argument('--fit'); p.add_argument('--region', choices=['KR', 'GLOBAL'])
    sp.add_parser('score'); sp.add_parser('selftest')
    p = sp.add_parser('list'); p.add_argument('--status'); p.add_argument('--fit'); p.add_argument('--region'); p.add_argument('-n', type=int, default=40)
    p = sp.add_parser('set'); p.add_argument('id'); p.add_argument('--status', choices=['포착', '검수대기', '촬영대기', '완료', '제외']); p.add_argument('--note'); p.add_argument('--fit'); p.add_argument('--topic')
    a = ap.parse_args()
    globals()['cmd_' + a.cmd](a)
