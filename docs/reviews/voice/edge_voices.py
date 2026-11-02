"""List edge-tts English voices."""
import asyncio, json, edge_tts
vs = asyncio.run(edge_tts.list_voices())
en = [v for v in vs if v["Locale"].startswith("en-")]
print(len(vs), "total;", len(en), "English")
for v in en:
    print(v["ShortName"], v["Gender"], ",".join(v.get("VoiceTag", {}).get("VoicePersonalities", [])))
