import sys
from fontTools.ttLib import TTFont

STRIP = ("DSIG", "GDEF", "GPOS", "GSUB")


def prep(src, dst, family):
    t = TTFont(src)
    if "glyf" not in t:
        sys.exit("CFF/OTF outlines: convert to TrueType (glyf) first")
    removed = [tag for tag in STRIP if tag in t]
    for tag in removed:
        del t[tag]
    t["OS/2"].fsType = 8
    for n in t["name"].names:
        if n.nameID in (1, 4, 16):
            n.string = family
        elif n.nameID == 6:
            n.string = family.replace(" ", "") + "-Regular"
    t.save(dst)
    cmap = t.getBestCmap()
    print(f"{dst}: family='{family}' removed={removed} glyphs={t['maxp'].numGlyphs} digits_ok={all(ord(c) in cmap for c in '0123456789.-')}")


if __name__ == "__main__":
    prep(sys.argv[1], sys.argv[2], sys.argv[3])
