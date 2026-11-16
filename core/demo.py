"""Fictional, self-contained demo. Never opens WeChat data."""
from datetime import datetime

SESSIONS = [
    ('demo_design@chatroom', '周末出走计划', '群聊', '照片收到了，这次的日落真的很美。', '山'),
    ('demo_lin', '林间', '私聊', '好，那我们周六上午见。', '林'),
    ('demo_designers@chatroom', '小小设计工作室', '群聊', '新版本的页面已整理好，明天一起看。', '设'),
    ('demo_family@chatroom', '一家人', '群聊', '到家记得说一声，晚饭给你留着。', '家'),
    ('demo_chen', '陈一', '私聊', '那个书单我发给你啦。', '陈'),
    ('demo_books@chatroom', '读点好书', '群聊', '下个月一起读《看不见的城市》。', '书'),
    ('demo_file', '文件传输助手', '私聊', '旅行清单.pdf', '文'),
]


class DemoArchive:
    def __init__(self, library=None):
        self.library = library

    def close(self):
        pass

    def sessions(self):
        base = int(datetime(2026, 10, 30, 15, 30).timestamp())
        return [dict(username=u, display=n, summary=s, is_group=u.endswith('@chatroom'),
                     last_time=base-i*2700, sort_time=base-i*2700, has_messages=True,
                     unread=0, initial=a) for i, (u, n, t, s, a) in enumerate(SESSIONS)]

    def messages(self, session, options=None, descending=False, before=None, cancel=None):
        options = options or {}
        base = int(datetime(2026, 10, 30, 10, 10).timestamp())
        text = [
            ('林间', '周末的天气看起来不错，去山里走走吧？', False),
            ('我', '好呀！上次收藏的那条路线正好可以安排上。', True),
            ('陈一', '我整理了一份行程，走到观景台大概两小时，不会太累。', False),
            ('林间', '那就慢慢走，沿路找一家小店吃午饭。', False),
            ('我', '带上相机和热咖啡。\n最近很想把这些小小的日常好好留下来。', True),
            ('陈一', '日程已经记下啦，周六 9:00 在地铁站集合。', False),
            ('林间', '[图片] 山顶的日落', False),
            ('我', '这张光线真好，下次我们也等到日落再回来。', True),
            ('陈一', '照片收到了，这次的日落真的很美。', False),
            ('林间', '[文件] 徒步路线与装备清单.pdf', False),
        ]
        rows = []
        for i, (sender, content, me) in enumerate(text):
            ts = base + i * 240
            kind = 'image' if i == 6 else ('file' if i == 9 else 'text')
            extra = {'filename': '徒步路线与装备清单.pdf', 'filesize': '2457600'} if kind == 'file' else {}
            key = [ts, 0, i+1]
            if before and key >= before: continue
            if options.get('start') is not None and ts < options['start']: continue
            if options.get('end') is not None and ts > options['end']: continue
            target_kind = options.get('kind', 'all')
            if target_kind != 'all':
                if target_kind == 'media' and kind not in ('image', 'video'): continue
                elif target_kind != 'media' and target_kind != kind: continue
            if options.get('query', '').casefold() not in (sender+' '+content).casefold(): continue
            rows.append(dict(local_id=i+1, server_id=str(i+1), shard=0, type=3 if kind=='image' else (6 if kind=='file' else 1),
                             type_name='图片' if kind=='image' else ('文件' if kind=='file' else '文本'), create_time=ts,
                             time_str=datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S'),
                             sender=sender, sender_wxid='demo_me' if me else 'demo_friend',
                             is_sender=me, text=content, content=content, kind=kind, extra=extra,
                             session=session, _cursor=key))
        for msg in reversed(rows) if descending else rows:
            if cancel: cancel()
            yield msg

    def page(self, session, options=None, before=None, limit=60):
        rows = list(self.messages(session, options, descending=True, before=before))
        page = rows[:limit]
        return dict(messages=list(reversed(page)), more=len(rows)>limit,
                    cursor=page[-1]['_cursor'] if page else None)

    def global_search(self, query: str, kind: str = 'all', limit: int = 50, offset: int = 0, session: str = None, cancel=None):
        query = str(query or '').strip()
        kind = str(kind or 'all').strip()
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        if not query and kind == 'all':
            return {'items': [], 'total': 0, 'sessions_hit': 0, 'session_groups': [], 'query': query, 'limit': limit, 'offset': offset}

        all_sessions = self.sessions()
        session_map = {s['username']: s for s in all_sessions}
        target_sessions = [session] if (session and session in session_map) else [s['username'] for s in all_sessions]
        target_sessions.sort(key=lambda u: session_map[u].get('sort_time') or session_map[u].get('last_time') or 0, reverse=True)

        matched_items = []
        session_counts = {}
        options = {'query': query, 'kind': kind}
        query_fold = query.casefold()

        for s_user in target_sessions:
            if cancel: cancel()
            s_info = session_map[s_user]
            for msg in self.messages(s_user, options=options, descending=True, cancel=cancel):
                session_counts[s_user] = session_counts.get(s_user, 0) + 1
                text = msg.get('text', '')
                snippet = text
                if query_fold and query_fold in text.casefold():
                    idx = text.casefold().find(query_fold)
                    start_idx = max(0, idx - 30)
                    end_idx = min(len(text), idx + len(query) + 30)
                    prefix = '…' if start_idx > 0 else ''
                    suffix = '…' if end_idx < len(text) else ''
                    snippet = prefix + text[start_idx:end_idx].strip() + suffix
                elif len(snippet) > 80:
                    snippet = snippet[:80] + '…'

                matched_items.append({
                    'session': s_user,
                    'session_name': s_info.get('display', s_user),
                    'session_avatar': '',
                    'is_group': s_info.get('is_group', False),
                    'msg_id': f"{msg.get('shard', 0)}_{msg.get('local_id', 0)}_{msg.get('server_id', '')}",
                    'local_id': msg.get('local_id', 0),
                    'server_id': str(msg.get('server_id', '')),
                    'create_time': msg.get('create_time', 0),
                    'time_str': msg.get('time_str', ''),
                    'sender': msg.get('sender', ''),
                    'sender_wxid': msg.get('sender_wxid', ''),
                    'avatar_url': '',
                    'is_sender': msg.get('is_sender', False),
                    'kind': msg.get('kind', 'text'),
                    'text': text,
                    'snippet': snippet,
                    'extra': msg.get('extra', {}),
                })

        total = len(matched_items)
        session_groups = [
            {
                'session': u,
                'display': session_map[u].get('display', u),
                'avatar_url': '',
                'is_group': session_map[u].get('is_group', False),
                'count': cnt,
            }
            for u, cnt in session_counts.items()
        ]
        session_groups.sort(key=lambda x: x['count'], reverse=True)

        return {
            'items': matched_items[offset:offset + limit],
            'total': total,
            'sessions_hit': len(session_counts),
            'session_groups': session_groups,
            'query': query,
            'limit': limit,
            'offset': offset,
        }
