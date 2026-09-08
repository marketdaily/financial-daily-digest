#!/usr/bin/env python3
"""把 GitHub 原始命中變成可信的 design-in 證據。
⭐ 誠實閘:料號被寫成 9 位純數字(例:912280001)時,程式碼裡任何無關的數字串都會命中。
   所以只有「檔案本身像 EDA/BOM 產物」的命中才算證據,其餘全部丟掉並記錄丟了多少。
"""
import json, os, re, sys, collections

RAW = os.path.expanduser("~/Delvin-agent/intel/research/kingconn_designin/github_hits.json")
STRONG_EXT = {".sch",".kicad_sch",".kicad_pcb",".kicad_sym",".kicad_pro",".brd",".lib",".dcm",
              ".schdoc",".pcbdoc",".prjpcb",".net",".cmp",".bom",".step",".stp",".epw",".lbr"}
HINT = re.compile(r"(bom|schematic|schem|kicad|altium|eagle|pcb|hardware|electronic|component|"
                  r"footprint|symbol|library|part|netlist|assembly|gerber|cpl)", re.I)
AMBIG_EXT = {".csv",".json",".xml",".md",".txt",".yaml",".yml",".tsv",".htm",".html",".xlsx"}

LIBFILE = re.compile(r"(^|/)(lib|lbr|libraries|library|symbols|footprints)/|\.lbr$|"
                     r"(^|/)[^/]*(library|_lib|-lib)[^/]*$", re.I)
CACHE   = re.compile(r"(-cache|-rescue)\.lib$|\.net$|\.sch$|\.kicad_sch$|\.brd$|\.kicad_pcb$|"
                     r"\.schdoc$|\.pcbdoc$|\.prjpcb$|\.bom$", re.I)

def classify(path):
    """A=這塊板子真的用了這顆(原理圖/PCB/網表/該設計的 cache 庫/BOM)
       B=只是躺在通用零件庫裡(貨架存在,不是設計採用)
       None=不是 EDA 檔,丟掉"""
    p = path.lower(); ext = os.path.splitext(p)[1]
    if CACHE.search(p): return "A"
    if ext in AMBIG_EXT and HINT.search(p):
        return "B" if LIBFILE.search(p) else "A"
    if ext in STRONG_EXT:
        return "B" if LIBFILE.search(p) else "A"
    return None

def is_evidence(path): return classify(path) is not None

raw = json.load(open(RAW))
parts, repo_index = {}, collections.defaultdict(set)
tot_files = tot_kept = 0
for mpn, e in raw.items():
    keep = {}
    for repo, rec in e["repos"].items():
        cls = {f: classify(f) for f in rec["files"]}
        ev = [f for f,c in cls.items() if c]
        tot_files += len(rec["files"]); tot_kept += len(ev)
        if ev:
            kind = "A" if any(c=="A" for c in cls.values()) else "B"
            keep[repo] = {**rec, "files": ev, "kind": kind}
            if kind == "A": repo_index[repo].add(mpn)
    parts[mpn] = {"brand": e["brand"], "card": e["card"], "mech": e["mech"], "kc": e["kc"],
                  "raw_repos": len(e["repos"]),
                  "design_repos": sum(1 for v in keep.values() if v["kind"]=="A"),
                  "lib_repos":    sum(1 for v in keep.values() if v["kind"]=="B"),
                  "orgs": sorted(r for r,v in keep.items()
                                 if v["owner_type"]=="Organization" and v["kind"]=="A"),
                  "repos": keep,
                  "max_total": max([c for c in e["queries"].values() if c is not None] or [0])}

print(f"檔案級:命中 {tot_files} → 認列 {tot_kept}(丟棄 {tot_files-tot_kept} 個非 EDA 檔,"
      f"={100*(tot_files-tot_kept)/max(tot_files,1):.0f}% 是數字巧合/無關檔)")
print(f"料號級:{len(parts)} 顆已掃;有 design 證據的 repo 共 {len(repo_index)} 個\n")
print("── 需求排行(有實際設計檔在用的 repo 數)──")
for mpn, v in sorted(parts.items(), key=lambda x: -x[1]["design_repos"])[:15]:
    print(f"{v['brand']:11s} {mpn:12s} {str(v['card']):9s} 設計檔repo={v['design_repos']:3d} "
          f"(組織 {len(v['orgs']):2d}) 零件庫repo={v['lib_repos']:3d} → 皇海 {','.join(v['kc'][:2])}")
json.dump({"parts": parts, "repo_to_mpns": {k: sorted(v) for k,v in repo_index.items()}},
          open(os.path.expanduser("~/Delvin-agent/intel/research/kingconn_designin/analysis.json"),"w"),
          ensure_ascii=False, indent=1)
