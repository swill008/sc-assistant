"""List Piper English voices from voices.json, with model size and dataset licence (MODEL_CARD)."""
import json, re, sys, urllib.request
vj = json.load(open(sys.argv[1], encoding="utf-8"))
B = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
for key, v in sorted(vj.items()):
    if v["language"]["family"] != "en":
        continue
    onnx = [f for f in v["files"] if f.endswith(".onnx")][0]
    size = v["files"][onnx]["size_bytes"] / 2**20
    card = [f for f in v["files"] if f.endswith("MODEL_CARD")]
    lic = ""
    if card:
        try:
            txt = urllib.request.urlopen(B + card[0], timeout=15).read().decode("utf-8", "replace")
            m = re.search(r"License:\s*(.+)", txt)
            lic = m.group(1).strip() if m else ""
        except Exception as e:
            lic = f"? {e}"
    print(f"{key}\t{v['num_speakers']} spk\t{size:.0f} MB\t{lic}")
