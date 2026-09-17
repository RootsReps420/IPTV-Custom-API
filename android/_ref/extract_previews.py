import pathlib

src = pathlib.Path(r"C:\Users\Dan\Desktop\photos reference")
dst = pathlib.Path(r"C:\Repos\IPTV-Custom-API\android\_ref")
dst.mkdir(exist_ok=True)


def extract_jpegs(data: bytes):
    out = []
    i = 0
    while True:
        start = data.find(b"\xff\xd8\xff", i)
        if start < 0:
            break
        end = data.find(b"\xff\xd9", start + 3)
        if end < 0:
            break
        end += 2
        blob = data[start:end]
        if len(blob) > 20_000:
            out.append(blob)
        i = start + 3
    return out


for p in sorted(src.iterdir()):
    if p.suffix.lower() not in {".jpeg", ".dng", ".jpg"}:
        continue
    data = p.read_bytes()
    jpegs = extract_jpegs(data)
    jpegs.sort(key=len, reverse=True)
    print(f"{p.name}: file={len(data)} jpegs={[len(j) for j in jpegs[:6]]}")
    if jpegs:
        out = dst / f"{p.stem}.jpg"
        out.write_bytes(jpegs[0])
        print("  wrote", out.name, len(jpegs[0]))
