#!/usr/bin/env python3
"""One permitted public Twitch clip -> 60s 9:16 MP4 with actual speech captions."""
import os,re,json,subprocess,tempfile,pathlib,sys
from faster_whisper import WhisperModel

ROOT=pathlib.Path(__file__).resolve().parents[1]
M=json.loads((ROOT/'production/gta6_15_manifest.json').read_text())
item=next(row for row in M if row['index']==int(os.getenv('CLIP_INDEX','1')))
output=ROOT/'dist/gta6_reels'
output.mkdir(parents=True,exist_ok=True)

def run(args,limit=300):
    res=subprocess.run(args,capture_output=True,text=True,timeout=limit)
    if res.returncode: raise RuntimeError(res.stderr[-1800:])
    return res.stdout

def dur(path):
    return float(run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(path)],20).strip())

def ass_time(x):
    cs=round(max(0,x)*100);h,x=divmod(cs,360000);m,x=divmod(x,6000);s,c=divmod(x,100)
    return f'{h}:{m:02d}:{s:02d}.{c:02d}'

def escaped(x):
    return str(x).replace('{','(').replace('}',')').replace('\\','').replace('\n',' ')

with tempfile.TemporaryDirectory() as temp:
    w=pathlib.Path(temp)
    files=[]
    for i,slug in enumerate(item['twitch_clip_ids']):
        if not re.fullmatch(r'[A-Za-z0-9_-]{12,160}',slug):raise ValueError('Invalid Twitch clip identifier')
        run(['yt-dlp','--no-playlist','--retries','2','--socket-timeout','25',
             '-f','bv*+ba/best','--merge-output-format','mp4',
             '-o',str(w/f'part{i}.%(ext)s'),'https://clips.twitch.tv/'+slug],180)
        got=[p for p in w.glob(f'part{i}.*') if p.suffix in ('.mp4','.mkv','.webm')]
        if not got:raise RuntimeError('Twitch does not supply a downloadable original for '+slug)
        files.append(got[0])
    if len(files)==1:
        original=files[0]
    else:
        normalized=[]
        for i,file in enumerate(files):
            norm=w/f'normalized{i}.mp4'
            run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(file),
                 '-vf','scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30',
                 '-af','aresample=async=1:first_pts=0','-c:v','libx264','-preset','ultrafast',
                 '-c:a','aac','-ar','48000','-ac','2',str(norm)],240)
            normalized.append(norm)
        (w/'concat.txt').write_text(''.join(f"file '{file.name}'\n" for file in normalized))
        original=w/'joined.mp4'
        run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(w/'concat.txt'),'-c','copy',str(original)],90)
    if dur(original)<59.7:raise RuntimeError('Source is too short; no fake stretching to 60 seconds')
    model=WhisperModel('base',device='cpu',compute_type='int8')
    segments,_=model.transcribe(str(original),language=item['language'],word_timestamps=True,vad_filter=True)
    cap=[]
    for seg in segments:
        words=[p for p in (seg.words or []) if p.word.strip()]
        for i in range(0,len(words),5):
            chunk=words[i:i+5]
            cap.append((chunk[0].start,chunk[-1].end,' '.join(p.word.strip() for p in chunk)))
    if not cap:raise RuntimeError('No spoken words detected: subtitles not fabricated')
    header="""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,DejaVu Sans,58,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,0,2,70,70,285,1
Style: Hook,DejaVu Sans,70,&H0000FFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,0,8,60,60,165,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events=['Dialogue: 1,0:00:00.00,0:00:04.00,Hook,,0,0,0,,'+escaped(item['hook'])]
    for begin,end,txt in cap:
        if begin>=60:continue
        events.append(f'Dialogue: 0,{ass_time(begin)},{ass_time(min(60,max(end,begin+.18)))},Sub,,0,0,0,,{escaped(txt)}')
    ass=w/'caption.ass'
    ass.write_text(header+'\n'.join(events)+'\n',encoding='utf-8')
    filename=f"gta6_{item['index']:02d}_{item['streamer']}_60s.mp4"
    dest=output/filename
    filt='[0:v]split[bg][fg];[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:1[back];[fg]scale=1040:1400:force_original_aspect_ratio=decrease[front];[back][front]overlay=(W-w)/2:(H-h)/2,format=yuv420p,ass='+str(ass)+'[v]'
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(original),
         '-filter_complex',filt,'-map','[v]','-map','0:a:0','-af','apad=pad_dur=2',
         '-r','30','-frames:v','1800','-t','60',
         '-c:v','libx264','-preset','veryfast','-crf','21',
         '-c:a','aac','-b:a','160k','-movflags','+faststart',str(dest)],600)
    length=dur(dest)
    if abs(length-60)>0.05:raise RuntimeError(f'Not exactly 60 seconds: {length}')
    (output/(filename+'.json')).write_text(json.dumps({'clip':filename,'duration':length,
        'streamer':item['streamer'],'title':item['title'],'hook':item['hook'],
        'subtitles':'real-word-timestamps','original':item['twitch_clip_ids']},ensure_ascii=False,indent=2))
    print('DONE',filename,length,'seconds')
