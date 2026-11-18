import sys, zipfile
src, dst, *repls = sys.argv[1:]
data = {p.split('=')[0]: open(p.split('=')[1],'rb').read() for p in repls}
zin = zipfile.ZipFile(src)
with zipfile.ZipFile(dst, 'w') as zout:
    for it in zin.infolist():
        buf = data.get(it.filename)
        if buf is None:
            buf = zin.read(it.filename)
        zi = zipfile.ZipInfo(it.filename, it.date_time)
        zi.compress_type = it.compress_type
        zi.external_attr = it.external_attr
        zi.internal_attr = it.internal_attr
        zi.create_system = it.create_system
        zi.comment = it.comment
        zout.writestr(zi, buf)
print("repacked ->", dst, "replaced:", list(data))
