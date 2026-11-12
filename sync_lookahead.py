import os, json, sys
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.parse import urlencode, urlsplit
from urllib.error import HTTPError, URLError
from pathlib import Path
from icalendar import Calendar
import recurring_ical_events

TZ = ZoneInfo('America/New_York')
HOSTS = {'www.rmj-dashboard.com', 'rmj-dashboard.com'}
class SyncError(Exception): pass
class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urlsplit(newurl)
        if p.scheme != 'https' or p.hostname not in HOSTS or p.username or p.password or p.port not in (None,443):
            raise SyncError('Dashboard redirected outside the approved HTTPS hosts.')
        if p.path.rstrip('/') != '/api/v1/lookahead.ics':
            raise SyncError('Dashboard redirected away from the calendar endpoint (possibly to login). Verify the subscription URL and API key.')
        # Retain the key only on the approved calendar endpoint.
        url = p._replace(query=urlencode({'key': os.environ['RMJ_LOOKAHEAD_KEY'].strip()}), fragment='').geturl()
        print(f'Following approved dashboard redirect (HTTP {code}).')
        return super().redirect_request(req, fp, code, msg, headers, url)

def local(v):
    if isinstance(v, datetime): return v.replace(tzinfo=TZ) if v.tzinfo is None else v.astimezone(TZ)
    return datetime.combine(v,time.min,TZ)

def retrieve():
    key = os.getenv('RMJ_LOOKAHEAD_KEY','').strip()
    if not key: raise SyncError('Repository secret RMJ_LOOKAHEAD_KEY is missing or empty.')
    if '://' in key or '?key=' in key: raise SyncError('Repository secret must contain only the API key, not the full subscription URL.')
    url = 'https://www.rmj-dashboard.com/api/v1/lookahead.ics?' + urlencode({'key':key})
    try:
        with build_opener(SafeRedirect()).open(Request(url,headers={'Accept':'text/calendar, */*;q=0.1','User-Agent':'RMJ-Breakroom-Lookahead/1.1'}),timeout=30) as r:
            raw=r.read(5_000_001)
            print(f'Dashboard returned HTTP {r.status}; downloaded {len(raw)} bytes.')
    except HTTPError as e:
        hints={400:'Verify the subscription URL and key format.',401:'Verify the key is valid and not revoked.',403:'Check key permissions and dashboard access restrictions.',404:'Verify the exact ICS endpoint on the API Keys page.',429:'Dashboard rate limit reached.',500:'Dashboard server error.',502:'Dashboard gateway error.',503:'Dashboard unavailable.'}
        raise SyncError(f'Dashboard HTTP {e.code}. '+hints.get(e.code,'Check the dashboard endpoint.')) from None
    except (URLError, TimeoutError) as e:
        raise SyncError(f'Dashboard network connection failed ({type(e).__name__}). Check DNS, TLS and server availability.') from None
    if len(raw)>5_000_000: raise SyncError('Calendar feed exceeds 5 MB.')
    if not raw.lstrip(b'\xef\xbb\xbf \t\r\n').startswith(b'BEGIN:VCALENDAR'):
        raise SyncError('Dashboard returned a response that is not an ICS calendar. Check whether the endpoint requires login or returned an error page.')
    try: return Calendar.from_ical(raw.lstrip(b'\xef\xbb\xbf'))
    except Exception as e: raise SyncError(f'ICS parsing failed ({type(e).__name__}). Ask dashboard team to verify calendar formatting.') from None

def main():
    out=Path('site/lookahead.json')
    enabled=os.getenv('PUBLISH_LOOKAHEAD','').strip().upper()=='YES'
    titles=os.getenv('PUBLISH_TITLES','').strip().upper()=='YES'
    result={'enabled':enabled,'updated':datetime.now(timezone.utc).isoformat(),'events':[]}
    if enabled:
        cal=retrieve()
        today=datetime.now(TZ).date(); monday=today-timedelta(days=today.weekday()); stop=monday+timedelta(days=14)
        try:
            entries=recurring_ical_events.of(cal).between(local(monday),local(stop))
            for e in entries:
                if str(e.get('STATUS','')).upper()=='CANCELLED' or str(e.get('CLASS','')).upper() in ('PRIVATE','CONFIDENTIAL'): continue
                if 'DTSTART' not in e: continue
                a=e.decoded('DTSTART'); all_day=not isinstance(a,datetime)
                b=e.decoded('DTEND') if 'DTEND' in e else (a+e.decoded('DURATION') if 'DURATION' in e else a+(timedelta(days=1) if all_day else timedelta(seconds=1)))
                start,end=local(a),local(b)
                if end<=start: end=start+timedelta(seconds=1)
                title=' '.join(str(e.get('SUMMARY','Scheduled assignment')).split())[:180] or 'Scheduled assignment'
                if not titles: title='Scheduled assignment'
                for i in range(14):
                    day=monday+timedelta(days=i); lo=local(day); hi=local(day+timedelta(days=1))
                    if start<hi and end>lo: result['events'].append({'day':day.isoformat(),'title':title,'start':max(start,lo).isoformat(),'allDay':all_day})
            result['events'].sort(key=lambda e:(e['day'],not e['allDay'],e['start'],e['title']))
        except Exception as e: raise SyncError(f'Calendar event processing failed ({type(e).__name__}). Check event date/time or recurrence formatting.') from None
    else: print('Schedule publication disabled by PUBLISH_LOOKAHEAD.')
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    print(f'Prepared {len(result["events"])} display entries. No credentials or event contents logged.')

if __name__=='__main__':
    try: main()
    except SyncError as e:
        print(f'Lookahead sync failed: {e}',file=sys.stderr); sys.exit(1)
    except Exception as e:
        print(f'Lookahead sync failed unexpectedly ({type(e).__name__}). No credentials or feed contents logged.',file=sys.stderr);sys.exit(1)
