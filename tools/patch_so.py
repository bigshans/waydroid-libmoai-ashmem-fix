import struct, sys

THUMB_RET = bytes([0x00,0x20, 0x70,0x47])                      # movs r0,#0 ; bx lr
ARM_RET   = bytes([0x00,0x00,0xa0,0xe3, 0x1e,0xff,0x2f,0xe1])   # mov r0,#0  ; bx lr
A64_RET   = bytes([0x00,0x00,0x80,0x52, 0xc0,0x03,0x5f,0xd6])   # mov w0,#0  ; ret

SYM = "ashmem_set_prot_region"

def parse(so):
    d = open(so,'rb').read()
    assert d[:4] == b'\x7fELF'
    is64 = d[4] == 2
    little = d[5] == 1
    e = '<' if little else '>'
    if is64:
        e_shoff, = struct.unpack_from(e+'Q', d, 0x28)
        e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(e+'HHH', d, 0x3a)
    else:
        e_shoff, = struct.unpack_from(e+'I', d, 0x20)
        e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(e+'HHH', d, 0x2e)
    # program headers for vaddr->offset
    if is64:
        e_phoff, = struct.unpack_from(e+'Q', d, 0x20)
        e_phentsize, e_phnum = struct.unpack_from(e+'HH', d, 0x36)
    else:
        e_phoff, = struct.unpack_from(e+'I', d, 0x1c)
        e_phentsize, e_phnum = struct.unpack_from(e+'HH', d, 0x2a)
    segs = []
    for i in range(e_phnum):
        o = e_phoff + i*e_phentsize
        if is64:
            p_type, p_flags, p_offset, p_vaddr, _, p_filesz = struct.unpack_from(e+'IIQQQQ', d, o)
        else:
            p_type, p_offset, p_vaddr, _, p_filesz = struct.unpack_from(e+'IIIII', d, o)
        if p_type == 1:  # PT_LOAD
            segs.append((p_vaddr, p_offset, p_filesz))
    # sections for dynsym
    syms = []
    for i in range(e_shnum):
        o = e_shoff + i*e_shentsize
        if is64:
            name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info, sh_align, sh_entsize = struct.unpack_from(e+'IIQQQQIIQQ', d, o)
        else:
            name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info, sh_align, sh_entsize = struct.unpack_from(e+'IIIIIIIIII', d, o)
        if sh_type == 11:  # SHT_DYNSYM
            strtab_off = None
            o2 = e_shoff + sh_link*e_shentsize
            if is64:
                _,_,_,_,strtab_off,_,_,_,_,_ = struct.unpack_from(e+'IIQQQQIIQQ', d, o2)
            else:
                _,_,_,_,strtab_off,_,_,_,_,_ = struct.unpack_from(e+'IIIIIIIIII', d, o2)
            n = sh_size // sh_entsize
            for j in range(n):
                so_ = sh_offset + j*sh_entsize
                if is64:
                    st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack_from(e+'IBBHQQ', d, so_)
                else:
                    st_name, st_value, st_size, st_info, st_other, st_shndx = struct.unpack_from(e+'IIIBBH', d, so_)
                if st_name and st_shndx != 0:
                    end = d.index(b'\0', strtab_off+st_name)
                    nm = d[strtab_off+st_name:end].decode()
                    syms.append((nm, st_value, st_size, shndx_is := st_shndx))
    return d, is64, syms, segs

def vaddr_to_off(v, segs, is64):
    v &= ~1 if not is64 else ~0   # strip thumb bit for 32-bit
    for va, off, sz in segs:
        if va <= v < va+sz:
            return off + (v-va)
    return None

for so in sys.argv[1:]:
    d, is64, syms, segs = parse(so)
    hit = [s for s in syms if s[0] == SYM]
    if not hit:
        print(f"{so}: 找不到 {SYM}")
        continue
    _, value, size, _ = hit[0]
    thumb = (not is64) and (value & 1)
    off = vaddr_to_off(value, segs, is64)
    patch = A64_RET if is64 else (THUMB_RET if thumb else ARM_RET)
    if off is None:
        print(f"{so}: 无法把 vaddr {value:#x} 映射到文件偏移")
        continue
    if size < len(patch):
        print(f"{so}: 函数只有 {size} 字节，太小")
        continue
    old = d[off:off+len(patch)]
    print(f"{so}: {'AArch64' if is64 else ('Thumb' if thumb else 'ARM')} vaddr={value:#x} off={off:#x} size={size} old={old.hex()} new={patch.hex()}")
    d = d[:off] + patch + d[off+len(patch):]
    open(so, 'wb').write(d)
