import json,collections,statistics
with open("chat.json",encoding="utf-8") as f: data=json.load(f)
comments=data.get("comments",[])
bins=collections.Counter(int(float(c.get("content_offset_seconds",0)))//10 for c in comments if c.get("content_offset_seconds") is not None)
candidates=[]
for b,count in bins.items():
    neighbors=[bins.get(i,0) for i in range(max(0,b-6),b)]+[bins.get(i,0) for i in range(b+1,b+7)]
    baseline=statistics.median(neighbors) if neighbors else 0
    if count>=5 and count>baseline:
        candidates.append((count/(baseline+1),count,b,baseline))
candidates.sort(reverse=True)
selected=[]
for ratio,count,b,base in candidates:
    if all(abs(b*10-x["offset_seconds"])>=120 for x in selected):
        selected.append({"offset_seconds":b*10,"messages_in_10s":count,"local_median":base,"ratio":round(ratio,2),"link":"https://www.twitch.tv/videos/2932305259?t=%dh%dm%ds"%(b*10//3600,(b*10%3600)//60,b*10%60)})
    if len(selected)>=15: break
out={"vod":"2932305259","coverage_seconds":[0,3600],"total_messages":len(comments),"candidate_peaks":selected,"note":"Chat peak is a candidate, not proof of video quality. Only first hour examined."}
with open("chat_peaks.json","w",encoding="utf-8") as f: json.dump(out,f,indent=2)
print(json.dumps(out,indent=2))
