import os,json,sys
from datetime import date,datetime,time,timedelta,timezone
from zoneinfo import ZoneInfo
from urllib.request import Request,urlopen,HTTPRedirectHandler,build_opener
from urllib.parse import urlencode
from pathlib import Path
from icalendar import Calendar
import recurring_ical_events
TZ=ZoneInfo('America/New_York')
def local(v):
    if isinstance(v,datetime): return v.replace(tzinfo=TZ) if v.tzinfo is None else v.astimezone(TZ)
    return datetime.combine(v,time.min,TZ)
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def main():
    out=Path('site/lookahead.json')
    enabled=os.getenv('PUBLISH_LOOKAHEAD')=='YES'
    result={'enabled':enabled,'updated':datetime.now(timezone.utc).isoformat(),'events':[]}
    if enabled:
        key=os.environ.get('RMJ_LOOKAHEAD_KEY','')
        if not key: raise RuntimeError('Missing calendar secret')
        url='https://www.rmj-dashboard.com/api/v1/lookahead.ics?'+urlencode({'key':key})
        with build_opener(NoRedirect()).open(Request(url,headers={'Accept':'text/calendar'}),timeout=30) as r:
            raw=r.read(5_000_001)
        if len(raw)>5_000_000 or not raw.lstrip().startswith(b'BEGIN:VCALENDAR'): raise RuntimeError('Invalid calendar response')
        cal=Calendar.from_ical(raw)
        today=datetime.now(TZ).date(); monday=today-timedelta(days=today.weekday()); stop=monday+timedelta(days=14)
        startdt=local(monday); stopdt=local(stop)
        for e in recurring_ical_events.of(cal).between(startdt,stopdt):
            if str(e.get('STATUS','')).upper()=='CANCELLED' or str(e.get('CLASS','')).upper() in ('PRIVATE','CONFIDENTIAL'): continue
            if 'DTSTART' not in e: continue
            a=e.decoded('DTSTART'); all_day=not isinstance(a,datetime); b=e.decoded('DTEND') if 'DTEND' in e else (a+e.decoded('DURATION') if 'DURATION' in e else a+(timedelta(days=1) if all_day else timedelta(seconds=1)))
            start,end=local(a),local(b)
            if end<=start: end=start+timedelta(seconds=1)
            title=' '.join(str(e.get('SUMMARY','Scheduled assignment')).split())[:180] or 'Scheduled assignment'
            if os.getenv('PUBLISH_TITLES')!='YES': title='Scheduled assignment'
            for i in range(14):
                day=monday+timedelta(days=i); lo=local(day); hi=local(day+timedelta(days=1))
                if start<hi and end>lo: result['events'].append({'day':day.isoformat(),'title':title,'start':max(start,lo).isoformat(),'allDay':all_day})
        result['events'].sort(key=lambda e:(e['day'],not e['allDay'],e['start'],e['title']))
    out.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
if __name__=='__main__':
    try: main()
    except Exception:
        print('Lookahead sync failed. Check API key, feed availability, and calendar format. No feed contents or credentials logged.',file=sys.stderr);sys.exit(1)
